"""The onboarding ↔ cases bridge: glue only, and all of it lives here.

`app.modules.cases` holds the case model and five tested application services,
but until now nothing called them. This module is the only caller. It imports
the cases facade and nothing below it, and cases never imports onboarding.
Remove this file, `events/case_bridge_consumer.py` and `api/cases_router.py`,
and the coupling is gone.

**What it does**

1. *Opens a case* (`handle_event`, called by `CaseBridgeConsumer`). The trigger
   is the `exporter.lifecycle.changed` event for entry into `COMPLIANCE_REVIEW`:
   one `ONBOARDING_REVIEW` case, `customer_id` set to the exporter. The case
   starts with the evidence that exists at that moment: every EXPORTER
   verification result, plus the current state of each screening-review item.
   The case row, its `CASE_CREATED` timeline entry and that evidence are
   written in one transaction.
2. *Adds later evidence.* A screening-review decision or verification review
   that arrives while the case is open becomes a new `case_evidence_item`. The
   existing items are never rewritten.
3. *Snapshots evidence at proposal time* (`_snapshot_evidence`). Just before a
   resolution is proposed, the ids and content digests of the case's evidence
   items are written into an append-only `case_timeline_event`. The database
   refuses UPDATE/DELETE on that table, so the record of what the decision
   rested on cannot drift. `get_review` then marks anything absent from the
   snapshot as a later addition, and any item whose data changed after it.
4. *Decides, then moves the exporter* (`decide`). The case resolution comes
   first; the lifecycle transition to `ONBOARDED` (or back to
   `DATA_COLLECTION` on rejection) follows it and depends on it. The
   transition is no longer the decision.

**The two-person rule** is `cases.REQUIRE_TWO_PERSON_RESOLUTION`, which is off.
With it off, one COMPLIANCE/ADMIN user proposes and approves in a single
`decide` call. With it on, the same call stops at `PENDING_APPROVAL`, and a
second, different user's `decide` completes the resolution.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases import (
    MIN_SUBSTANTIVE_NOTE_LENGTH,
    REQUIRE_TWO_PERSON_RESOLUTION,
    TERMINAL_CASE_STATUSES,
    ActorType,
    CaseDetail,
    CaseEvidenceItem,
    CaseLifecycleService,
    CaseNoteService,
    CaseQueryService,
    CaseSeverity,
    CaseStatus,
    CaseTimelineEvent,
    CaseType,
    ComplianceCase,
    EvidenceAggregationService,
    EvidenceType,
    ResolutionAction,
    SlaCalculationService,
    TimelineEventType,
    build_sla_calculation_service,
)
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.exporter_enums import ExporterLifecycleStatus
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.infrastructure.repositories import (
    ExporterProfileRepository,
    OnboardingRequestRepository,
)
from app.platform.messaging.schemas import EventEnvelope, EventType
from app.shared.exceptions import AnerBaseException, NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

#: `case_timeline_event.actor_id` for writes the bridge makes on its own.
SYSTEM_ACTOR_ID = "system:onboarding-case-bridge"
#: `compliance_case.originating_epic` / `case_evidence_item.source_epic`.
ORIGINATING_EPIC = "EXPORTER_CRM"
#: `case_timeline_event.payload["kind"]` of an evidence snapshot.
EVIDENCE_SNAPSHOT_KIND = "EVIDENCE_SNAPSHOT"

#: No risk signal reaches the bridge yet, so every onboarding-review case opens
#: at MEDIUM. SLA: 48h (sla-config.yaml, onboarding_review.medium).
DEFAULT_SEVERITY = CaseSeverity.MEDIUM
DEFAULT_PRIORITY = 3

DecisionOutcome = Literal["APPROVE", "REJECT"]

_RESOLUTION_FOR: dict[str, ResolutionAction] = {
    "APPROVE": ResolutionAction.APPROVE_ONBOARDING,
    "REJECT": ResolutionAction.REJECT_ONBOARDING,
}
#: The lifecycle move that follows each resolution. A rejection sends the
#: relationship back for more data (PERMITTED_LIFECYCLE_TRANSITIONS).
_LIFECYCLE_AFTER: dict[ResolutionAction, ExporterLifecycleStatus] = {
    ResolutionAction.APPROVE_ONBOARDING: ExporterLifecycleStatus.ONBOARDED,
    ResolutionAction.REJECT_ONBOARDING: ExporterLifecycleStatus.DATA_COLLECTION,
}

_SCREENING_VERIFICATION_TYPES = frozenset(
    {
        VerificationType.AML,
        VerificationType.CFT,
        VerificationType.SANCTIONS,
        VerificationType.PEP,
        VerificationType.ADVERSE_MEDIA,
    }
)

_sla_service: SlaCalculationService | None = None


def _sla() -> SlaCalculationService:
    """Built once from the GitOps YAML, then held — as the cases module intends."""
    global _sla_service
    if _sla_service is None:
        _sla_service = build_sla_calculation_service()
    return _sla_service


class CaseBridgeConflictError(AnerBaseException):
    """The case or the exporter is not in a state this operation can act on."""

    def __init__(self, detail: str, *, error_code: str = "CASE_BRIDGE_CONFLICT") -> None:
        super().__init__(detail=detail, error_code=error_code, status_code=409)


@dataclass(frozen=True)
class EvidenceSnapshot:
    """The evidence list as it stood when a resolution was proposed."""

    timeline_event_id: uuid.UUID
    taken_at: datetime
    taken_by: str
    items: list[dict]


@dataclass(frozen=True)
class CaseReview:
    """A case as the reviewer sees it: detail plus its evidence snapshot."""

    detail: CaseDetail
    snapshot: EvidenceSnapshot | None
    #: Evidence items that arrived after the snapshot was taken.
    added_after_snapshot: frozenset[uuid.UUID]
    #: Items in the snapshot whose data no longer matches the recorded digest.
    changed_since_snapshot: frozenset[uuid.UUID]


@dataclass(frozen=True)
class DecisionResult:
    case: ComplianceCase
    lifecycle_status: ExporterLifecycleStatus
    #: True only with the two-person rule on, when this call proposed and a
    #: second reviewer must still approve.
    awaiting_second_reviewer: bool


class CaseBridgeService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ExporterProfileRepository(db)
        self._requests = OnboardingRequestRepository(db)

    # ── Event subscriber ────────────────────────────────────────────────────

    async def handle_event(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if envelope.event_type is EventType.EXPORTER_LIFECYCLE_CHANGED:
            if payload.get("to_status") == ExporterLifecycleStatus.COMPLIANCE_REVIEW.value:
                await self.open_review_case(
                    uuid.UUID(payload["customer_id"]),
                    originating_event_id=uuid.UUID(envelope.event_id),
                    originating_event_type=envelope.event_type.value,
                )
        elif envelope.event_type is EventType.EXPORTER_SCREENING_REVIEW_UPDATED:
            item = await self._db.get(ScreeningReviewItem, uuid.UUID(payload["item_id"]))
            if item is not None:
                await self._add_later_evidence(item.customer_id, *_screening_evidence(item))
        elif envelope.event_type is EventType.EXPORTER_VERIFICATION_REVIEWED:
            if payload.get("entity_type") != VerificationEntityType.EXPORTER.value:
                return  # a director/buyer/... check has no exporter case to join
            result = await self._db.get(
                VerificationResult, uuid.UUID(payload["verification_result_id"])
            )
            if result is not None:
                await self._add_later_evidence(
                    result.entity_reference, *_verification_evidence(result)
                )

    # ── Case creation ───────────────────────────────────────────────────────

    async def open_review_case(
        self,
        customer_id: uuid.UUID,
        *,
        originating_event_id: uuid.UUID,
        originating_event_type: str,
    ) -> ComplianceCase | None:
        """Open the exporter's onboarding-review case, or do nothing if one is
        already open or this event already opened one. Returns the new case,
        or `None` when nothing was created.

        One per exporter: re-entering COMPLIANCE_REVIEW while a case is still
        open joins that case. Serialised per customer with a transaction-scoped
        advisory lock so two concurrent events cannot both pass the check.
        """
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"onboarding-review-case:{customer_id}"},
        )
        existing = await self.open_review_case_for(customer_id)
        if existing is not None:
            logger.info(
                "case_bridge.case_already_open",
                customer_id=str(customer_id),
                case_id=str(existing.id),
            )
            await self._db.commit()  # release the lock
            return None
        if await self._db.scalar(
            select(ComplianceCase.id).where(
                ComplianceCase.originating_event_id == originating_event_id
            )
        ):
            await self._db.commit()
            return None

        requests = await self._requests.list_by_customer(customer_id)
        latest_request = requests[0] if requests else None
        subject = latest_request.legal_name if latest_request else str(customer_id)
        now = datetime.now(UTC)

        case = ComplianceCase(
            case_type=CaseType.ONBOARDING_REVIEW,
            case_status=CaseStatus.OPEN,
            severity=DEFAULT_SEVERITY,
            priority=DEFAULT_PRIORITY,
            title=f"Onboarding review: {subject}"[:500],
            description=(
                f"Exporter {customer_id} entered COMPLIANCE_REVIEW. Decide whether "
                f"to onboard it; the exporter's lifecycle follows the decision."
            ),
            customer_id=customer_id,
            onboarding_id=latest_request.id if latest_request else None,
            originating_epic=ORIGINATING_EPIC,
            originating_event_type=originating_event_type,
            originating_event_id=originating_event_id,
            sla_deadline=_sla().calculate_sla_deadline(
                CaseType.ONBOARDING_REVIEW.value, DEFAULT_SEVERITY.value, now
            ),
            sla_breached=False,
        )
        self._db.add(case)
        await self._db.flush()

        evidence = await self._current_evidence(customer_id)
        self._db.add(
            CaseTimelineEvent(
                case_id=case.id,
                event_type=TimelineEventType.CASE_CREATED,
                from_status=None,
                to_status=CaseStatus.OPEN.value,
                actor_id=SYSTEM_ACTOR_ID,
                actor_type=ActorType.SYSTEM,
                payload={
                    "originating_event_id": str(originating_event_id),
                    "originating_event_type": originating_event_type,
                    "initial_evidence_count": len(evidence),
                },
            )
        )
        for evidence_type, source_reference_id, evidence_data in evidence:
            self._db.add(
                CaseEvidenceItem(
                    case_id=case.id,
                    evidence_type=evidence_type,
                    source_epic=ORIGINATING_EPIC,
                    source_reference_id=source_reference_id,
                    evidence_data=evidence_data,
                    added_by=SYSTEM_ACTOR_ID,
                )
            )
        await self._db.commit()
        await EvidenceAggregationService().aggregate_evidence_package(self._db, case.id)
        await self._db.refresh(case)

        logger.info(
            "case_bridge.case_opened",
            customer_id=str(customer_id),
            case_id=str(case.id),
            case_reference=case.case_reference,
            initial_evidence_count=len(evidence),
        )
        return case

    async def open_review_case_for(self, customer_id: uuid.UUID) -> ComplianceCase | None:
        return await self._db.scalar(
            select(ComplianceCase)
            .where(
                ComplianceCase.customer_id == customer_id,
                ComplianceCase.case_type == CaseType.ONBOARDING_REVIEW,
                ComplianceCase.case_status.notin_(TERMINAL_CASE_STATUSES),
            )
            .order_by(ComplianceCase.created_at.desc())
            .limit(1)
        )

    # ── Evidence ────────────────────────────────────────────────────────────

    async def _current_evidence(
        self, customer_id: uuid.UUID
    ) -> list[tuple[EvidenceType, uuid.UUID, dict]]:
        results = (
            await self._db.scalars(
                select(VerificationResult)
                .where(
                    VerificationResult.entity_type == VerificationEntityType.EXPORTER,
                    VerificationResult.entity_reference == customer_id,
                )
                .order_by(VerificationResult.created_at)
            )
        ).all()
        # Current state of each checklist item: the newest row per item_key.
        items = (
            await self._db.scalars(
                select(ScreeningReviewItem)
                .where(ScreeningReviewItem.customer_id == customer_id)
                .distinct(ScreeningReviewItem.item_key)
                .order_by(
                    ScreeningReviewItem.item_key.asc(),
                    ScreeningReviewItem.created_at.desc(),
                    ScreeningReviewItem.id.desc(),
                )
            )
        ).all()
        return [_verification_evidence(r) for r in results] + [
            _screening_evidence(i) for i in items
        ]

    async def _add_later_evidence(
        self,
        customer_id: uuid.UUID,
        evidence_type: EvidenceType,
        source_reference_id: uuid.UUID,
        evidence_data: dict,
    ) -> None:
        case = await self.open_review_case_for(customer_id)
        if case is None:
            return
        aggregation = EvidenceAggregationService()
        await aggregation.add_evidence_item(
            self._db,
            case.id,
            evidence_type=evidence_type,
            source_epic=ORIGINATING_EPIC,
            source_reference_id=source_reference_id,
            evidence_data=evidence_data,
            added_by=SYSTEM_ACTOR_ID,
        )
        await aggregation.aggregate_evidence_package(self._db, case.id)
        logger.info(
            "case_bridge.evidence_added",
            case_id=str(case.id),
            evidence_type=evidence_type.value,
            source_reference_id=str(source_reference_id),
        )

    async def _snapshot_evidence(
        self, case: ComplianceCase, *, actor_id: str, actor_type: ActorType
    ) -> CaseTimelineEvent:
        """Record the case's evidence list, as it stands now, in an append-only
        timeline entry. Not a live reference: ids plus a digest of each item's
        data at this moment."""
        items = (
            await self._db.scalars(
                select(CaseEvidenceItem)
                .where(CaseEvidenceItem.case_id == case.id)
                .order_by(CaseEvidenceItem.added_at, CaseEvidenceItem.id)
            )
        ).all()
        event = CaseTimelineEvent(
            case_id=case.id,
            event_type=TimelineEventType.EVIDENCE_UPDATED,
            from_status=case.case_status.value,
            to_status=case.case_status.value,
            actor_id=actor_id,
            actor_type=actor_type,
            note="Evidence snapshot taken for the resolution proposal",
            payload={
                "kind": EVIDENCE_SNAPSHOT_KIND,
                "evidence_items": [
                    {
                        "evidence_item_id": str(item.id),
                        "evidence_type": item.evidence_type.value,
                        "source_reference_id": str(item.source_reference_id),
                        "added_at": item.added_at.isoformat(),
                        "data_digest": _digest(item.evidence_data),
                    }
                    for item in items
                ],
            },
        )
        self._db.add(event)
        await self._db.commit()
        await self._db.refresh(event)
        return event

    async def _latest_snapshot(self, case_id: uuid.UUID) -> CaseTimelineEvent | None:
        return await self._db.scalar(
            select(CaseTimelineEvent)
            .where(
                CaseTimelineEvent.case_id == case_id,
                CaseTimelineEvent.event_type == TimelineEventType.EVIDENCE_UPDATED,
                CaseTimelineEvent.payload["kind"].astext == EVIDENCE_SNAPSHOT_KIND,
            )
            .order_by(CaseTimelineEvent.occurred_at.desc(), CaseTimelineEvent.id.desc())
            .limit(1)
        )

    # ── Queue / detail / note ───────────────────────────────────────────────

    async def list_queue(
        self,
        *,
        status: CaseStatus | None,
        case_type: CaseType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ComplianceCase], int]:
        query = select(func.count()).select_from(ComplianceCase)
        if status is not None:
            query = query.where(ComplianceCase.case_status == status)
        if case_type is not None:
            query = query.where(ComplianceCase.case_type == case_type)
        total = await self._db.scalar(query) or 0
        cases = await CaseQueryService().list_cases(
            self._db, status=status, case_type=case_type, limit=limit, offset=offset
        )
        return cases, total

    async def get_review(self, case_id: uuid.UUID, *, actor_type: ActorType) -> CaseReview:
        detail = await CaseQueryService().get_case_detail(
            self._db, case_id, caller_actor_type=actor_type
        )
        snapshot_event = await self._latest_snapshot(case_id)
        if snapshot_event is None:
            return CaseReview(detail, None, frozenset(), frozenset())

        recorded = {
            uuid.UUID(entry["evidence_item_id"]): entry["data_digest"]
            for entry in snapshot_event.payload["evidence_items"]
        }
        current = {item.id: item for item in detail.case.evidence_items}
        return CaseReview(
            detail=detail,
            snapshot=EvidenceSnapshot(
                timeline_event_id=snapshot_event.id,
                taken_at=snapshot_event.occurred_at,
                taken_by=snapshot_event.actor_id,
                items=list(snapshot_event.payload["evidence_items"]),
            ),
            added_after_snapshot=frozenset(i for i in current if i not in recorded),
            changed_since_snapshot=frozenset(
                i
                for i, digest in recorded.items()
                if i in current and _digest(current[i].evidence_data) != digest
            ),
        )

    async def add_note(
        self, case_id: uuid.UUID, note: str, *, actor_id: str, actor_type: ActorType
    ) -> CaseTimelineEvent:
        return await CaseNoteService().add_case_note(
            self._db, case_id, note, actor_id=actor_id, actor_type=actor_type
        )

    # ── Decision ────────────────────────────────────────────────────────────

    async def decide(
        self,
        case_id: uuid.UUID,
        *,
        outcome: DecisionOutcome,
        rationale: str,
        actor_id: str,
        actor_type: ActorType,
    ) -> DecisionResult:
        """Resolve the case, then move the exporter. In that order.

        1. Preconditions, before anything is written: a real rationale, an
           open ONBOARDING_REVIEW case, an exporter still in COMPLIANCE_REVIEW.
        2. The case walks its own permitted transitions via
           `CaseLifecycleService`: assign to the reviewer, begin
           investigation, snapshot the evidence, propose, then decide.
        3. Only once the case is RESOLVED does the exporter's lifecycle move,
           to ONBOARDED on approval or back to DATA_COLLECTION on rejection.
           The lifecycle event is then published.

        With the two-person rule on, and the caller being the proposer, this
        stops after step 2's proposal and reports `awaiting_second_reviewer`.
        """
        resolution = _RESOLUTION_FOR[outcome]
        if not rationale or len(rationale.strip()) < MIN_SUBSTANTIVE_NOTE_LENGTH:
            raise ValidationError(
                f"rationale must be at least {MIN_SUBSTANTIVE_NOTE_LENGTH} characters"
            )

        case = await self._db.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError(f"Case '{case_id}' not found")
        if case.case_type != CaseType.ONBOARDING_REVIEW or case.customer_id is None:
            raise CaseBridgeConflictError(
                f"Case '{case_id}' is not an exporter onboarding review",
                error_code="CASE_NOT_ONBOARDING_REVIEW",
            )
        if case.case_status in TERMINAL_CASE_STATUSES:
            raise CaseBridgeConflictError(
                f"Case '{case_id}' is already {case.case_status.value}",
                error_code="CASE_IS_TERMINAL",
            )
        customer_id = case.customer_id
        profile = await self._profiles.get_by_customer_id(customer_id)
        if profile is None or profile.lifecycle_status != ExporterLifecycleStatus.COMPLIANCE_REVIEW:
            raise CaseBridgeConflictError(
                f"Exporter '{customer_id}' is not in COMPLIANCE_REVIEW",
                error_code="EXPORTER_NOT_IN_COMPLIANCE_REVIEW",
            )

        lifecycle = CaseLifecycleService()
        if case.case_status == CaseStatus.OPEN:
            case = await lifecycle.assign_case(
                self._db, case_id, assigned_to=actor_id, actor_id=actor_id, actor_type=actor_type
            )
        if case.case_status in (
            CaseStatus.ASSIGNED,
            CaseStatus.PENDING_EXTERNAL,
            CaseStatus.ESCALATED,
        ):
            case = await lifecycle.begin_investigation(
                self._db, case_id, actor_id=actor_id, actor_type=actor_type
            )
        if case.case_status == CaseStatus.UNDER_INVESTIGATION:
            await self._snapshot_evidence(case, actor_id=actor_id, actor_type=actor_type)
            case = await lifecycle.propose_resolution(
                self._db,
                case_id,
                resolution_action=resolution,
                resolution_note=rationale,
                proposed_by=actor_id,
                actor_type=actor_type,
            )

        proposal = await self._latest_proposal(case_id)
        if proposal is None:  # pragma: no cover — propose_resolution always writes one
            raise CaseBridgeConflictError(f"Case '{case_id}' has no proposal to decide")
        if proposal.payload["proposed_resolution_action"] != resolution.value:
            raise CaseBridgeConflictError(
                f"Case '{case_id}' has a pending "
                f"{proposal.payload['proposed_resolution_action']} proposal; "
                f"{resolution.value} does not match it",
                error_code="PROPOSAL_MISMATCH",
            )
        if REQUIRE_TWO_PERSON_RESOLUTION and proposal.payload["proposed_by"] == actor_id:
            return DecisionResult(case, profile.lifecycle_status, awaiting_second_reviewer=True)

        case = await lifecycle.decide_resolution(
            self._db,
            case_id,
            decision="approve",
            checker_id=actor_id,
            actor_type=actor_type,
            checker_note=rationale,
        )

        # The case is resolved; only now does the exporter move.
        to_status = _LIFECYCLE_AFTER[resolution]
        profile = await ExporterProfileService(self._db).transition_lifecycle_status(
            customer_id, to_status, actor_id=actor_id, compliance_authorized=True
        )
        await OnboardingEventPublisher().exporter_lifecycle_changed(
            customer_id=customer_id,
            from_status=ExporterLifecycleStatus.COMPLIANCE_REVIEW.value,
            to_status=to_status.value,
            actor_id=actor_id,
        )
        logger.info(
            "case_bridge.decided",
            case_id=str(case_id),
            customer_id=str(customer_id),
            resolution_action=resolution.value,
            lifecycle_status=to_status.value,
            actor_id=actor_id,
        )
        return DecisionResult(case, profile.lifecycle_status, awaiting_second_reviewer=False)

    async def _latest_proposal(self, case_id: uuid.UUID) -> CaseTimelineEvent | None:
        return await self._db.scalar(
            select(CaseTimelineEvent)
            .where(
                CaseTimelineEvent.case_id == case_id,
                CaseTimelineEvent.event_type == TimelineEventType.APPROVAL_REQUESTED,
            )
            .order_by(CaseTimelineEvent.occurred_at.desc())
            .limit(1)
        )


# ── Evidence shaping ────────────────────────────────────────────────────────


def _verification_evidence(result: VerificationResult) -> tuple[EvidenceType, uuid.UUID, dict]:
    if result.verification_type == VerificationType.KYB:
        evidence_type = EvidenceType.KYB_RESULT
    elif result.verification_type in _SCREENING_VERIFICATION_TYPES:
        evidence_type = EvidenceType.SCREENING_RESULT
    else:
        evidence_type = EvidenceType.ONBOARDING_EVIDENCE
    return (
        evidence_type,
        result.id,
        _jsonable(
            {
                "source": "verification_result",
                "verification_result_id": result.id,
                "verification_type": result.verification_type,
                "provider": result.provider,
                "provider_reference": result.provider_reference,
                "status": result.status,
                "risk_level": result.risk_level,
                "performed_at": result.performed_at,
                "normalized_result": result.normalized_result,
                "evidence_reference": result.evidence_reference,
                "reviewed_by": result.reviewed_by,
                "review_status": result.review_status,
            }
        ),
    )


def _screening_evidence(item: ScreeningReviewItem) -> tuple[EvidenceType, uuid.UUID, dict]:
    return (
        EvidenceType.ONBOARDING_EVIDENCE,
        item.id,
        _jsonable(
            {
                "source": "screening_review_item",
                "item_key": item.item_key,
                "status": item.status,
                "comment": item.comment,
                "reviewed_by": item.reviewed_by,
                "reviewed_at": item.reviewed_at,
            }
        ),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _digest(evidence_data: dict) -> str:
    canonical = json.dumps(evidence_data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "EVIDENCE_SNAPSHOT_KIND",
    "CaseBridgeConflictError",
    "CaseBridgeService",
    "CaseReview",
    "DecisionResult",
    "EvidenceSnapshot",
]
