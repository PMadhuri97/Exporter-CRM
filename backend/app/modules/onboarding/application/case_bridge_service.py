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
   transition is no longer the decision. The cases services commit after
   every step, so the case and the exporter cannot move in one transaction.
   Instead the whole decision holds a per-exporter lock (`_decision_lock`),
   and a case resolved without the exporter moving (a crash, a DB error)
   is finished by calling `decide` again, not left stranded.
5. *Closes the case on a send-back* (`send_back`). COMPLIANCE_REVIEW ->
   DATA_COLLECTION through the lifecycle route closes the open case
   (`CLOSED_WITHOUT_ACTION`) before the exporter moves, so no case is left
   open against an exporter that has left review.

**The two-person rule** is `cases.REQUIRE_TWO_PERSON_RESOLUTION`, which is off.
With it off, one COMPLIANCE/ADMIN user proposes and approves in a single
`decide` call. With it on, the same call stops at `PENDING_APPROVAL`, and a
second, different user's `decide` completes the resolution. A second user
who asks for the other outcome rejects the pending proposal and proposes
their own, which then waits for a reviewer other than them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
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
#: `compliance_case.originating_event_type` of a case opened on demand, with
#: no bus event behind it (see `ensure_review_case`).
ON_DEMAND_ORIGIN = "onboarding.case_bridge.on_demand"

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
    #: True when this call rejected someone else's pending proposal (its
    #: outcome differed) before proposing its own.
    proposal_rejected: bool = False


class CaseBridgeService:
    def __init__(self, db: AsyncSession, *, require_two_person: bool | None = None) -> None:
        """`require_two_person` defaults to `cases.REQUIRE_TWO_PERSON_RESOLUTION`
        (read here, not at import), and is handed to `CaseLifecycleService`
        so the bridge and the lifecycle service never disagree about it."""
        self._db = db
        self._profiles = ExporterProfileRepository(db)
        self._requests = OnboardingRequestRepository(db)
        self._require_two_person = (
            REQUIRE_TWO_PERSON_RESOLUTION if require_two_person is None else require_two_person
        )

    # ── Per-exporter decision lock ──────────────────────────────────────────

    @asynccontextmanager
    async def _decision_lock(self, customer_id: uuid.UUID) -> AsyncIterator[None]:
        """Serialise every write that moves an exporter out of COMPLIANCE_REVIEW
        (`decide`, `send_back`) per exporter.

        A session-level advisory lock on a connection of its own. The cases
        services commit after each step, which would end a transaction-scoped
        lock on `self._db` after the first one. A second caller does not
        queue behind the first: it gets a 409 and can retry.
        """
        key = f"onboarding-review-decision:{customer_id}"
        async with self._db.bind.connect() as conn:
            acquired = await conn.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}
            )
            if not acquired:
                raise CaseBridgeConflictError(
                    f"A compliance decision on exporter '{customer_id}' is already in "
                    f"progress; retry once it has finished",
                    error_code="DECISION_IN_PROGRESS",
                )
            try:
                yield
            finally:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key}
                )
                await conn.commit()

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
        originating_event_id: uuid.UUID | None,
        originating_event_type: str,
    ) -> ComplianceCase | None:
        """Open the exporter's onboarding-review case, or do nothing if one is
        already open, this event already opened one, or the exporter is no
        longer in COMPLIANCE_REVIEW (a late or redelivered event). Returns the
        new case, or `None` when nothing was created.

        One open case per exporter. Serialised per customer with a
        transaction-scoped advisory lock so two concurrent callers cannot
        both pass the check.
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
        if originating_event_id is not None and await self._db.scalar(
            select(ComplianceCase.id).where(
                ComplianceCase.originating_event_id == originating_event_id
            )
        ):
            await self._db.commit()
            return None
        lifecycle_status = await self._db.scalar(
            select(ExporterProfile.lifecycle_status).where(
                ExporterProfile.customer_id == customer_id
            )
        )
        if lifecycle_status != ExporterLifecycleStatus.COMPLIANCE_REVIEW:
            logger.info(
                "case_bridge.exporter_not_in_review",
                customer_id=str(customer_id),
                lifecycle_status=lifecycle_status.value if lifecycle_status else None,
            )
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
                    "originating_event_id": (
                        str(originating_event_id) if originating_event_id else None
                    ),
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

    async def ensure_review_case(self, customer_id: uuid.UUID) -> ComplianceCase | None:
        """The exporter's open review case, opened now if it has none.

        The bus is best-effort (a failed handler is logged and dropped, and
        there is no redelivery on the in-memory bus), and exporters already in
        COMPLIANCE_REVIEW before the bridge existed never had an event. This
        is the fallback for both: whoever next tries to decide gets a case.
        `None` only if the exporter is not in COMPLIANCE_REVIEW.
        """
        existing = await self.open_review_case_for(customer_id)
        if existing is not None:
            return existing
        opened = await self.open_review_case(
            customer_id, originating_event_id=None, originating_event_type=ON_DEMAND_ORIGIN
        )
        return opened or await self.open_review_case_for(customer_id)

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
        # At-least-once delivery: `add_evidence_item` commits before the
        # consumer marks the event processed, so a redelivery can land here
        # twice. The same source row with the same data is not new evidence.
        digest = _digest(evidence_data)
        already_on_case = (
            await self._db.scalars(
                select(CaseEvidenceItem.evidence_data).where(
                    CaseEvidenceItem.case_id == case.id,
                    CaseEvidenceItem.source_reference_id == source_reference_id,
                )
            )
        ).all()
        if any(_digest(data) == digest for data in already_on_case):
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

        1. Preconditions, before anything is written: a real rationale and an
           ONBOARDING_REVIEW case.
        2. Under the per-exporter `_decision_lock`: the case must be open and
           the exporter still in COMPLIANCE_REVIEW. A pending proposal for the
           other outcome, made by someone else, is rejected first.
        3. The case walks its own permitted transitions via
           `CaseLifecycleService`: assign to the reviewer, begin
           investigation, snapshot the evidence, propose, then decide.
        4. Only once the case is RESOLVED does the exporter's lifecycle move,
           to ONBOARDED on approval or back to DATA_COLLECTION on rejection.
           The lifecycle event is then published.

        Step 3 commits before step 4 (the cases services commit per step). If
        step 4 fails, the case is RESOLVED and the exporter has not moved.
        Calling `decide` again with the same outcome finishes the move
        (`_finish_resolved`) instead of answering 409.

        With the two-person rule on, and the caller being the proposer, this
        stops after step 3's proposal and reports `awaiting_second_reviewer`.
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
        customer_id = case.customer_id

        async with self._decision_lock(customer_id):
            # Re-read under the lock: a concurrent decision may just have ended.
            await self._db.refresh(case)
            if case.case_status in TERMINAL_CASE_STATUSES:
                return await self._finish_resolved(case, resolution, actor_id=actor_id)
            profile = await self._profiles.get_by_customer_id(customer_id)
            if (
                profile is None
                or profile.lifecycle_status != ExporterLifecycleStatus.COMPLIANCE_REVIEW
            ):
                raise CaseBridgeConflictError(
                    f"Exporter '{customer_id}' is not in COMPLIANCE_REVIEW",
                    error_code="EXPORTER_NOT_IN_COMPLIANCE_REVIEW",
                )

            lifecycle = CaseLifecycleService(require_two_person=self._require_two_person)
            proposal_rejected = False
            if case.case_status == CaseStatus.PENDING_APPROVAL:
                pending = await self._latest_proposal(case_id)
                if (
                    pending is not None
                    and pending.payload["proposed_resolution_action"] != resolution.value
                ):
                    if self._require_two_person and pending.payload["proposed_by"] == actor_id:
                        raise CaseBridgeConflictError(
                            f"Case '{case_id}' has your own pending "
                            f"{pending.payload['proposed_resolution_action']} proposal; a "
                            f"different reviewer must decide it",
                            error_code="PROPOSAL_MISMATCH",
                        )
                    # The reviewer disagrees with the pending proposal: reject
                    # it (back to UNDER_INVESTIGATION), then propose theirs.
                    case = await lifecycle.decide_resolution(
                        self._db,
                        case_id,
                        decision="reject",
                        checker_id=actor_id,
                        actor_type=actor_type,
                        checker_note=rationale,
                    )
                    proposal_rejected = True

            if case.case_status == CaseStatus.OPEN:
                case = await lifecycle.assign_case(
                    self._db,
                    case_id,
                    assigned_to=actor_id,
                    actor_id=actor_id,
                    actor_type=actor_type,
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

            # The pending proposal now matches `resolution`: it was just made,
            # or it already did.
            proposal = await self._latest_proposal(case_id)
            if proposal is None:  # pragma: no cover — propose_resolution always writes one
                raise CaseBridgeConflictError(f"Case '{case_id}' has no proposal to decide")
            if self._require_two_person and proposal.payload["proposed_by"] == actor_id:
                return DecisionResult(
                    case,
                    profile.lifecycle_status,
                    awaiting_second_reviewer=True,
                    proposal_rejected=proposal_rejected,
                )

            case = await lifecycle.decide_resolution(
                self._db,
                case_id,
                decision="approve",
                checker_id=actor_id,
                actor_type=actor_type,
                checker_note=rationale,
            )
            # The case is resolved; only now does the exporter move.
            return await self._move_exporter(
                case, resolution, actor_id=actor_id, proposal_rejected=proposal_rejected
            )

    async def _finish_resolved(
        self, case: ComplianceCase, resolution: ResolutionAction, *, actor_id: str
    ) -> DecisionResult:
        """A terminal case. Normally that is a 409. The exception: the case was
        RESOLVED with this same outcome, but the exporter move after it never
        happened (a crash or DB error between the two). Then the exporter is
        still in COMPLIANCE_REVIEW and has not moved since the resolution, and
        this call completes the move the resolution already decided."""
        terminal = CaseBridgeConflictError(
            f"Case '{case.id}' is already {case.case_status.value}",
            error_code="CASE_IS_TERMINAL",
        )
        if case.case_status != CaseStatus.RESOLVED or case.resolution_action != resolution:
            raise terminal
        profile = await self._profiles.get_by_customer_id(case.customer_id)
        if profile is None or profile.lifecycle_status != ExporterLifecycleStatus.COMPLIANCE_REVIEW:
            raise terminal
        last_move = await self._db.scalar(
            select(func.max(ExporterLifecycleHistory.created_at)).where(
                ExporterLifecycleHistory.customer_id == case.customer_id
            )
        )
        if case.resolved_at is None or (last_move is not None and last_move > case.resolved_at):
            # The exporter has moved since: this resolution is not the live one.
            raise terminal
        logger.warning(
            "case_bridge.finishing_stranded_resolution",
            case_id=str(case.id),
            customer_id=str(case.customer_id),
            resolution_action=resolution.value,
            actor_id=actor_id,
        )
        return await self._move_exporter(case, resolution, actor_id=actor_id)

    async def _move_exporter(
        self,
        case: ComplianceCase,
        resolution: ResolutionAction,
        *,
        actor_id: str,
        proposal_rejected: bool = False,
    ) -> DecisionResult:
        customer_id = case.customer_id
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
            case_id=str(case.id),
            customer_id=str(customer_id),
            resolution_action=resolution.value,
            lifecycle_status=to_status.value,
            actor_id=actor_id,
        )
        return DecisionResult(
            case,
            profile.lifecycle_status,
            awaiting_second_reviewer=False,
            proposal_rejected=proposal_rejected,
        )

    async def _latest_proposal(self, case_id: uuid.UUID) -> CaseTimelineEvent | None:
        return await self._db.scalar(
            select(CaseTimelineEvent)
            .where(
                CaseTimelineEvent.case_id == case_id,
                CaseTimelineEvent.event_type == TimelineEventType.APPROVAL_REQUESTED,
            )
            .order_by(CaseTimelineEvent.occurred_at.desc(), CaseTimelineEvent.id.desc())
            .limit(1)
        )

    # ── Send-back ───────────────────────────────────────────────────────────

    async def send_back(
        self, customer_id: uuid.UUID, *, actor_id: str, actor_type: ActorType
    ) -> ExporterProfile:
        """COMPLIANCE_REVIEW -> DATA_COLLECTION through the lifecycle route, for a
        compliance caller. The open case is closed (`CLOSED_WITHOUT_ACTION`)
        first, then the exporter moves, both under `_decision_lock`.

        Closing first is deliberate. If the move then fails, the exporter is
        still in review with no open case, and `ensure_review_case` opens a new
        one on the next attempt. The other order could leave an open case
        against an exporter that has left review, with no way to close it.
        """
        async with self._decision_lock(customer_id):
            lifecycle_status = await self._db.scalar(
                select(ExporterProfile.lifecycle_status).where(
                    ExporterProfile.customer_id == customer_id
                )
            )
            case = (
                await self.open_review_case_for(customer_id)
                if lifecycle_status == ExporterLifecycleStatus.COMPLIANCE_REVIEW
                else None
            )
            if case is not None:
                await self._close_for_send_back(case, actor_id=actor_id, actor_type=actor_type)
            # Not in COMPLIANCE_REVIEW: the service raises its usual 404/409.
            return await ExporterProfileService(self._db).transition_lifecycle_status(
                customer_id,
                ExporterLifecycleStatus.DATA_COLLECTION,
                actor_id=actor_id,
                compliance_authorized=True,
            )

    async def _close_for_send_back(
        self, case: ComplianceCase, *, actor_id: str, actor_type: ActorType
    ) -> None:
        if case.case_status == CaseStatus.PENDING_APPROVAL:
            raise CaseBridgeConflictError(
                f"Exporter '{case.customer_id}' has a resolution pending approval on "
                f"case {case.case_reference}; decide it on the case "
                f"(POST /compliance-cases/{case.id}/decision)",
                error_code="CASE_PENDING_APPROVAL",
            )
        lifecycle = CaseLifecycleService(require_two_person=self._require_two_person)
        if case.case_status == CaseStatus.OPEN:
            case = await lifecycle.assign_case(
                self._db, case.id, assigned_to=actor_id, actor_id=actor_id, actor_type=actor_type
            )
        if case.case_status in (
            CaseStatus.ASSIGNED,
            CaseStatus.PENDING_EXTERNAL,
            CaseStatus.ESCALATED,
        ):
            case = await lifecycle.begin_investigation(
                self._db, case.id, actor_id=actor_id, actor_type=actor_type
            )
        await lifecycle.close_case_without_action(
            self._db,
            case.id,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=(
                f"Closed without a case decision: the exporter was sent back from "
                f"COMPLIANCE_REVIEW to DATA_COLLECTION through the lifecycle route by "
                f"{actor_id}."
            ),
        )
        logger.info(
            "case_bridge.closed_for_send_back",
            case_id=str(case.id),
            customer_id=str(case.customer_id),
            actor_id=actor_id,
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
