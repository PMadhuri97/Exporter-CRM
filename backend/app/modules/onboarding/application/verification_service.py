"""`VerificationService` — EXP-2's application service for `VerificationResult`.

The whole point of this ticket: triggering a `KYC` check against a
`DIRECTOR` and a `BANK_ACCOUNT` check against an `EXPORTER` both go through
`trigger_verification` below, and `trigger_verification` never inspects
`verification_type` to decide what to do. It resolves `provider` to an
adapter class via `workflow_dependencies.get_adapter` (the generalized
registry — see that module's EXP-2 section), asks the adapter to `.verify()`
the request, and persists whatever `VerificationOutcome` comes back. Adding a
new check type is a new `VerificationType` member plus, where a real vendor
is involved, a new adapter — never a new branch here.
`tests/unit/test_verification_service_no_branching.py` proves this
structurally (an AST scan of this method's source); `tests/integration/
test_exp2_verification_service.py::test_kyc_director_and_bank_account_
exporter_share_identical_code_path` proves it behaviourally.

`provider` fidelity
--------------------
`VerificationOutcome.provider` (the adapter's own, self-reported name) is
written to `VerificationResult.provider` verbatim, in exactly one place
(`_result_from_outcome` below), and never compared, rewritten, or defaulted
elsewhere in this module. A result recorded with `provider="RXIL"` reads back
as `provider="RXIL"` everywhere — never silently renamed to the registry key
the caller passed as `provider=` (which need not be the same string; see
`ManualEntryAdapter`'s module docstring for why they happen to coincide for
that one adapter) or to anything else.

Integrity (Developer 4B, 4b-task.md §5)
---------------------------------------
* **Subjects are real** (§5.3, §5.7). An `EXPORTER` reference must be a company
  (404, `ExporterProfileNotFoundError`); a `BUYER` reference must be a
  `deal_buyer.id` (404, `ComplianceInputsBuyerNotFoundError`) — never a company id
  or a deal id. DIRECTOR, INVOICE, VESSEL and SHIPMENT have no table to check.
* **Buyer snapshot** (§5.7). A BUYER result stores the buyer's identity as it was
  when the check was recorded (`subject_snapshot`), because `DealService.set_buyer`
  rewrites the buyer row in place under the same id.
* **Evidence** (§5.3). `evidence_note` / `evidence_refs` are stored on the result.
  `document` references must exist, belong to the subject (the company for
  EXPORTER; the buyer's deal or its company for BUYER) and be `AVAILABLE` (scanned
  clean), read through Developer 3B's `CrmDocumentRepository`. What a *manual* outcome must carry is
  `domain.verification_evidence.check_manual_outcome` (D16, decided: a note or at
  least one reference), applied by `ManualEntryAdapter`.
* **Reviews supersede** (§5.1). `record_review` appends a `verification_review`
  that must name the current review; nothing is edited.
* **A reviewed result's outcome is frozen** (§5.2). `get_verification_status`
  ignores and logs a later provider answer for it; the database refuses it too.
* **History** (history-row contract §2, dimension `verification`). Recording a
  result, a polled status change and every review write one row, in the same
  transaction as the change: on the company for EXPORTER; on the deal's company
  with `deal_id` set for BUYER. DIRECTOR, INVOICE, VESSEL and SHIPMENT subjects
  have no company to hang a row on — **D15** (lead, 28 Sep 2026): no row is written
  for them, and that is logged.
* **Terminal deals** (D17, lead, 28 Sep 2026). A new BUYER check on a HANDED_OVER
  or WITHDRAWN deal is refused (409, `DEAL_CLOSED`).
* **Company lock** (§6.2 invariant 6). Writers of company-scoped inputs (EXPORTER
  subjects) take `FOR SHARE` on the company after any provider call and before the
  write. Buyer checks are not company inputs and never touch `background_check`.
* **Cycles** (Developer 1, plan P2-3a). Under that lock, a new EXPORTER result is
  stamped with the company's current check cycle (cycle 1 is created on the company's
  first input), so a Re-KYC's results are its own. BUYER results — legacy deal
  buyers, which have no background check — carry no cycle.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Importing the adapters package runs its module-level `register_adapter(...)`
# calls (see infrastructure/adapters/__init__.py's docstring) — the same way
# `kyb/__init__.py` imports `MiddeskAdapter` to register it. Nothing else in
# this module names a concrete adapter: this import exists solely so
# `get_adapter("manual")` has something to find.
import app.modules.onboarding.infrastructure.adapters  # noqa: F401
from app.modules.onboarding.application.company_input_lock import share_lock_companies
from app.modules.onboarding.application.evidence_documents import check_evidence_documents
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import (
    VerificationResult,
    about_company,
)
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.domain.workflow_dependencies import (
    BatchVerificationAdapter,
    VerificationOutcome,
    VerificationRequest,
    get_adapter,
)
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    ExporterProfileNotFoundError,
    ProviderCapabilityError,
    VerificationBuyerDealClosedError,
    VerificationLegacyReviewUnchainedError,
    VerificationResultNotReviewableError,
    VerificationReviewStaleError,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
)
from app.modules.onboarding.infrastructure.repositories.deal_buyer_repository import (
    DealBuyerRepository,
)
from app.modules.onboarding.infrastructure.repositories.deal_repository import DealRepository
from app.modules.onboarding.infrastructure.repositories.verification_review_repository import (
    VerificationReviewRepository,
)
from app.shared import clock
from app.shared.exceptions import NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

#: The history dimension this service writes (history-row contract §2).
HISTORY_DIMENSION = "verification"
#: `event_type` of a review's history row. Results use the contract's derived
#: `verification_initial` / `verification_transition`.
REVIEW_EVENT = "verification_reviewed"


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _company_subjects(
    subjects: Iterable[tuple[VerificationEntityType, uuid.UUID]],
) -> list[uuid.UUID]:
    """The company ids among `(entity_type, entity_reference)` pairs.

    A result whose subject is the company (`EXPORTER`) is an input to Developer 4A's
    background-check decision, so its writer takes `FOR SHARE` on the company row
    first (4b-task.md §6.2 invariant 6; `company_input_lock.py`). Other subjects —
    BUYER, DIRECTOR, INVOICE, VESSEL, SHIPMENT — are not company-scoped inputs and
    take no company lock.
    """
    return [
        reference
        for entity_type, reference in subjects
        if entity_type == VerificationEntityType.EXPORTER
    ]


def _subject_companies(result: VerificationResult) -> list[uuid.UUID]:
    """The company to share-lock before changing an existing result (a poll or a
    review): the company it is about (P4-5) — for a legacy ``BUYER`` result the
    deal-buyer migration mapped to a company, that company, whose background check
    now reads it. None for a subject with no company."""
    company = result.subject_company
    return [company] if company is not None else []


@dataclass(frozen=True)
class _Subject:
    """What a result's subject resolves to.

    `company_id` / `deal_id` place its history rows; `None` company means the subject
    has no company link (D15). `snapshot` is the BUYER identity to store.
    `subject_company_id` is the company the result is *about* (P4-5): the company itself
    for an `EXPORTER` subject; `None` for a legacy deal buyer (its company, if any, is
    set by the deal-buyer migration, P4-6) and for subjects with no company.
    """

    company_id: uuid.UUID | None
    deal_id: uuid.UUID | None = None
    snapshot: dict[str, Any] | None = None
    subject_company_id: uuid.UUID | None = None


@dataclass(frozen=True)
class VerificationResultView:
    """A result with its review chain, first review first, current review last."""

    result: VerificationResult
    reviews: tuple[VerificationReview, ...]

    @property
    def latest_review(self) -> VerificationReview | None:
        return self.reviews[-1] if self.reviews else None


# ── verification_type / entity_type cross-validation ─────────────────────────
#
# `VerificationType` (what kind of check) and `VerificationEntityType` (what
# kind of subject) are independent axes, and four names — BUYER, INVOICE,
# VESSEL, SHIPMENT — appear on both with *different* meanings. Nothing used to
# validate the pair, so `verification_type=VESSEL, entity_type=DIRECTOR` was
# accepted and persisted as a row no reader could interpret.
#
# Deliberately permissive: a check billed against the exporter is legitimate
# for every check type (that is how trade-object checks are commissioned —
# the exporter is the customer of record), so EXPORTER appears nearly
# everywhere. What this blocks is only the genuinely uninterpretable, such as
# a VESSEL check on a DIRECTOR or a GST lookup on a SHIPMENT.
#
# Kept as a table rather than `if` branches on purpose: `trigger_verification`
# must stay free of `verification_type` branching (EXP-2's central acceptance
# criterion, proven structurally by
# `tests/unit/test_verification_service_no_branching.py`). The service calls
# `_validate_type_pair` and never inspects the type itself.
_VALID_ENTITY_TYPES_FOR_CHECK: dict[
    VerificationType, frozenset[VerificationEntityType]
] = {
    # Identity / entity checks.
    VerificationType.KYC: frozenset(
        {VerificationEntityType.DIRECTOR, VerificationEntityType.BUYER}
    ),
    VerificationType.KYB: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    # Screening checks — run against any legal or natural person.
    VerificationType.AML: frozenset(
        {
            VerificationEntityType.EXPORTER,
            VerificationEntityType.BUYER,
            VerificationEntityType.DIRECTOR,
        }
    ),
    VerificationType.CFT: frozenset(
        {
            VerificationEntityType.EXPORTER,
            VerificationEntityType.BUYER,
            VerificationEntityType.DIRECTOR,
        }
    ),
    VerificationType.SANCTIONS: frozenset(
        {
            VerificationEntityType.EXPORTER,
            VerificationEntityType.BUYER,
            VerificationEntityType.DIRECTOR,
        }
    ),
    VerificationType.PEP: frozenset(
        {
            VerificationEntityType.EXPORTER,
            VerificationEntityType.BUYER,
            VerificationEntityType.DIRECTOR,
        }
    ),
    VerificationType.ADVERSE_MEDIA: frozenset(
        {
            VerificationEntityType.EXPORTER,
            VerificationEntityType.BUYER,
            VerificationEntityType.DIRECTOR,
        }
    ),
    # Registry / statutory lookups — about an organisation, never a person.
    VerificationType.COMPANY_REGISTRY: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    VerificationType.UBO: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    VerificationType.GST: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    VerificationType.IEC: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    VerificationType.BANK_ACCOUNT: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
    ),
    # Counterparty check — the BUYER *check*, not the BUYER *subject*.
    VerificationType.BUYER: frozenset(
        {VerificationEntityType.BUYER, VerificationEntityType.EXPORTER}
    ),
    # Trade-object checks. The subject is the object itself, or the exporter
    # the check was commissioned for.
    VerificationType.INVOICE: frozenset(
        {VerificationEntityType.INVOICE, VerificationEntityType.EXPORTER}
    ),
    VerificationType.INVOICE_DUPLICATION: frozenset(
        {VerificationEntityType.INVOICE, VerificationEntityType.EXPORTER}
    ),
    VerificationType.SHIPMENT: frozenset(
        {
            VerificationEntityType.SHIPMENT,
            VerificationEntityType.INVOICE,
            VerificationEntityType.EXPORTER,
        }
    ),
    VerificationType.VESSEL: frozenset(
        {
            VerificationEntityType.VESSEL,
            VerificationEntityType.SHIPMENT,
            VerificationEntityType.EXPORTER,
        }
    ),
    VerificationType.INSURANCE: frozenset(
        {
            VerificationEntityType.INVOICE,
            VerificationEntityType.SHIPMENT,
            VerificationEntityType.EXPORTER,
        }
    ),
}

# `VerificationType` is documented as extended additively (new member + new
# migration). A new member with no entry above would raise KeyError from
# whichever request happened to use it first; this turns that into an
# import-time failure with a name in it.
_UNMAPPED_CHECK_TYPES = set(VerificationType) - set(_VALID_ENTITY_TYPES_FOR_CHECK)
if _UNMAPPED_CHECK_TYPES:  # pragma: no cover — guards a source edit, not input
    raise RuntimeError(
        "_VALID_ENTITY_TYPES_FOR_CHECK is missing an entry for: "
        + ", ".join(sorted(t.value for t in _UNMAPPED_CHECK_TYPES))
    )


def _validate_type_pair(
    verification_type: VerificationType,
    entity_type: VerificationEntityType,
) -> None:
    """Reject a check/subject pair that cannot be meaningfully interpreted.

    Raises:
        ValidationError: `entity_type` is not a valid subject for this check.
    """
    permitted = _VALID_ENTITY_TYPES_FOR_CHECK[verification_type]
    if entity_type not in permitted:
        raise ValidationError(
            f"verification_type '{verification_type.value}' cannot be run "
            f"against entity_type '{entity_type.value}' — valid subjects are: "
            + ", ".join(sorted(e.value for e in permitted))
        )


def _result_from_outcome(
    *,
    verification_type: VerificationType,
    entity_type: VerificationEntityType,
    entity_reference: uuid.UUID,
    raw_result: dict[str, Any],
    outcome: VerificationOutcome,
    evidence: VerificationEvidence | None = None,
    subject_snapshot: dict[str, Any] | None = None,
    subject_company_id: uuid.UUID | None = None,
) -> VerificationResult:
    """The one place `VerificationOutcome` becomes a `VerificationResult` row.

    `raw_result` is the request payload the caller supplied to the adapter —
    the closest thing to "the provider's original response, unmodified" that
    exists in this ticket's exact `VerificationOutcome` shape, which carries
    no raw-response field of its own (unlike `KYBVerificationResult.
    raw_response_reference`). A real vendor adapter (RxilAdapter, the next
    ticket) is free to echo its own raw vendor payload back inside
    `VerificationOutcome.normalized_result` under a convention of its own
    choosing; nothing here prevents that. Flagged as a judgment call — see
    this ticket's report.

    `evidence` and `subject_snapshot` (Dev4B) are facts about the moment of
    recording and are frozen once written. The legacy `evidence_reference`,
    `reviewed_by` and `review_status` are never written. `subject_company_id` (P4-5)
    is the company the result is about, frozen once set.
    """
    return VerificationResult(
        verification_type=verification_type,
        entity_type=entity_type,
        entity_reference=entity_reference,
        provider=outcome.provider,
        provider_reference=outcome.provider_reference,
        status=outcome.status,
        risk_level=outcome.risk_level,
        performed_at=datetime.now(UTC),
        valid_until=outcome.valid_until,
        raw_result=raw_result,
        normalized_result=outcome.normalized_result,
        evidence_note=evidence.cleaned_note if evidence is not None else None,
        evidence_refs=[ref.as_json() for ref in evidence.refs] if evidence is not None else [],
        subject_snapshot=subject_snapshot,
        subject_company_id=subject_company_id,
    )


class VerificationService:
    """Trigger, poll, list and review `VerificationResult` rows."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._reviews = VerificationReviewRepository(db)

    # ── Subjects, evidence and history ───────────────────────────────────────

    async def _resolve_subject(
        self,
        entity_type: VerificationEntityType,
        reference: uuid.UUID,
        *,
        new_check: bool = False,
    ) -> _Subject:
        """Check the subject exists and find where its history belongs.

        `new_check` is true when a check is being recorded (not reviewed or polled):
        only then does D17's terminal-deal rule apply.

        Raises:
            ExporterProfileNotFoundError: an EXPORTER reference that is not a company.
            ComplianceInputsBuyerNotFoundError: a BUYER reference that is not a
                `deal_buyer.id` — including a company id or a deal id.
            VerificationBuyerDealClosedError: a new check on a buyer whose deal is
                HANDED_OVER or WITHDRAWN (D17).
        """
        if entity_type == VerificationEntityType.EXPORTER:
            exists = await self._db.scalar(
                select(ExporterProfile.customer_id).where(
                    ExporterProfile.customer_id == reference
                )
            )
            if exists is None:
                raise ExporterProfileNotFoundError(reference)
            # Any company — a seller, a buyer-only company, both (P4-5, P4-11).
            return _Subject(company_id=reference, subject_company_id=reference)
        if entity_type == VerificationEntityType.BUYER:
            buyer = await DealBuyerRepository(self._db).get(reference)
            if buyer is None:
                raise ComplianceInputsBuyerNotFoundError(reference)
            deal = await DealRepository(self._db).get_by_id(buyer.deal_id)
            if deal is None:  # pragma: no cover — deal_buyer.deal_id is a NOT NULL FK
                raise ComplianceInputsBuyerNotFoundError(reference)
            # D17 (lead, 28 Sep 2026): no new check on a buyer of a HANDED_OVER or
            # WITHDRAWN deal. Existing checks stay readable and reviewable.
            if new_check and deal.stage.is_terminal:
                raise VerificationBuyerDealClosedError(
                    deal_buyer_id=reference, deal_id=deal.id, stage=deal.stage.value
                )
            return _Subject(
                company_id=deal.company_id,
                deal_id=deal.id,
                snapshot={
                    "deal_buyer_id": str(buyer.id),
                    "deal_id": str(deal.id),
                    "name": buyer.name,
                    "country": buyer.country,
                    "registration_number": buyer.registration_number,
                    "tax_id": buyer.tax_id,
                },
            )
        # DIRECTOR, INVOICE, VESSEL, SHIPMENT: no table to validate against and no
        # company link. D15 (lead, 28 Sep 2026): they get no history row.
        return _Subject(company_id=None)

    async def _history_target(self, result: VerificationResult) -> _Subject:
        """Where a later history row for `result` goes. A BUYER whose row has since
        disappeared (or a pre-4B-5 row naming no real buyer) has no target."""
        try:
            subject = await self._resolve_subject(result.entity_type, result.entity_reference)
        except (ExporterProfileNotFoundError, ComplianceInputsBuyerNotFoundError):
            subject = _Subject(company_id=None)
        # P4-5: a legacy buyer result the deal-buyer migration mapped to a company is
        # that company's input now, so what happens to it next goes on that company's
        # timeline, with the deal as context (history carries no deal-company FK).
        if result.subject_company_id is not None and subject.company_id != result.subject_company_id:
            return _Subject(company_id=result.subject_company_id, deal_id=subject.deal_id)
        return subject

    async def _check_evidence_documents(
        self,
        evidence: VerificationEvidence | None,
        entity_type: VerificationEntityType,
        subject: _Subject,
    ) -> None:
        """Every `document` reference exists, belongs to the subject and is
        `AVAILABLE`.

        EXPORTER: a document of that company. BUYER: a document of the buyer's deal
        or of the deal's company (4b-task.md §5.3; which of those Dev4A's evidence
        snapshot may use is its D4). Subjects with no company link cannot own a
        document, so a document reference on one is refused. A document that is not
        `AVAILABLE` (`PENDING_SCAN`, `QUARANTINED`, `SCAN_FAILED`) is refused: it can
        never be opened (`storage-and-documents.md` §4), so it cannot be what an
        outcome rests on — the same scan gate as Dev4A's evidence snapshot (D4).
        """
        await check_evidence_documents(
            self._db,
            evidence,
            company_id=subject.company_id,
            deal_id=subject.deal_id,
            subject_label=entity_type.value,
        )

    async def _record_history(
        self,
        subject: _Subject,
        *,
        to_value: str,
        from_value: str | None,
        actor_id: str | None,
        source: str,
        details: dict[str, Any],
        reason: str | None = None,
        event_type: str | None = None,
    ) -> None:
        """One `verification` history row, flushed in the caller's transaction."""
        if subject.company_id is None:
            # D15 (lead, 28 Sep 2026): no company to write a history row against.
            logger.info(
                "verification.history.skipped_no_company",
                reason="D15: subject has no company link",
                **{k: v for k, v in details.items() if isinstance(v, str)},
            )
            return
        await HistoryService(self._db).record(
            subject.company_id,
            dimension=HISTORY_DIMENSION,
            to_value=to_value,
            from_value=from_value,
            actor_id=actor_id,
            source=source,
            reason=reason,
            deal_id=subject.deal_id,
            details=details,
            event_type=event_type,
        )

    async def _stamp_cycle(self, result: VerificationResult, *, actor_id: str, source: str) -> None:
        """Put a new company-subject result in its company's current cycle. Call with
        the company row already share-locked (the cycle cannot change under it)."""
        company = result.subject_company
        if company is None:
            return
        cycle = await CheckCycleRepository(self._db).current_or_initial(
            company, actor_id=actor_id, source_ref=source, at=clock.now()
        )
        result.cycle_id = cycle.id

    async def _is_reviewed(self, result: VerificationResult) -> bool:
        if result.review_status is not None:  # legacy column, pre-0021 or raw SQL
            return True
        return bool(await self._reviews.chain_for(result.id))

    # ── Trigger ──────────────────────────────────────────────────────────────

    async def trigger_verification(
        self,
        verification_type: VerificationType,
        entity_type: VerificationEntityType,
        entity_reference: uuid.UUID | str,
        *,
        provider: str = "manual",
        payload: dict[str, Any] | None = None,
        actor_id: uuid.UUID | str,
        evidence: VerificationEvidence | None = None,
    ) -> VerificationResult:
        """Run one verification check and persist its outcome.

        Resolves `provider` to an adapter class via the EXP-2 registry
        (`workflow_dependencies.get_adapter`), builds a `VerificationRequest`,
        calls `.verify()`, and stores the returned `VerificationOutcome` as a
        new `VerificationResult` row. This method's own source contains no
        `verification_type` comparison of any kind — see the module docstring.

        Args:
            verification_type: What kind of check to run.
            entity_type: What kind of thing is being checked.
            entity_reference: That entity's own id — a company id for EXPORTER,
                a `deal_buyer.id` for BUYER.
            provider: The registry name to resolve. Defaults to `"manual"`
                (`ManualEntryAdapter`).
            payload: Type-specific input. For `ManualEntryAdapter`, this is
                where the manually-observed result itself travels (see its
                module docstring); for a future real vendor adapter, this is
                whatever that vendor's `verify()` needs to submit a check.
            actor_id: Who triggered this check — from the session, never a body.
            evidence: What the outcome rests on (note and/or references).

        Returns:
            The persisted, refreshed `VerificationResult`.

        Raises:
            ValidationError: an uninterpretable type/subject pair, malformed or
                foreign evidence, or an outcome the adapter's rule refuses.
            ExporterProfileNotFoundError / ComplianceInputsBuyerNotFoundError:
                the subject does not exist.
        """
        # Before the adapter is resolved or called: a pair this service
        # cannot interpret must not reach a provider or a row.
        _validate_type_pair(verification_type, entity_type)

        reference = _as_uuid(entity_reference)
        subject = await self._resolve_subject(entity_type, reference, new_check=True)
        await self._check_evidence_documents(evidence, entity_type, subject)

        adapter_cls = get_adapter(provider)
        adapter = adapter_cls()

        request_payload = dict(payload or {})
        request = VerificationRequest(
            verification_type=verification_type,
            entity_type=entity_type,
            entity_reference=str(reference),
            payload=request_payload,
            evidence=evidence,
        )

        outcome = adapter.verify(request)

        result = _result_from_outcome(
            verification_type=verification_type,
            entity_type=entity_type,
            entity_reference=reference,
            raw_result=request_payload,
            outcome=outcome,
            evidence=evidence,
            subject_snapshot=subject.snapshot,
            subject_company_id=subject.subject_company_id,
        )
        # After the provider call, so no lock is held while a provider works.
        await share_lock_companies(self._db, _company_subjects([(entity_type, reference)]))
        await self._stamp_cycle(
            result, actor_id=str(actor_id), source="verification_service.trigger_verification"
        )
        self._db.add(result)
        await self._db.flush()
        await self._record_history(
            subject,
            to_value=outcome.status.value,
            from_value=None,
            actor_id=str(actor_id),
            source="verification_service.trigger_verification",
            details=_result_details(result),
        )
        await self._db.commit()
        await self._db.refresh(result)

        logger.info(
            "verification.triggered",
            verification_result_id=str(result.id),
            verification_type=verification_type.value,
            entity_type=entity_type.value,
            entity_reference=str(reference),
            provider=outcome.provider,
            status=outcome.status.value,
            actor_id=str(actor_id),
        )
        return result

    # ── Batch trigger (Exporter CRM Piece 3) ────────────────────────────────

    async def trigger_verification_batch(
        self,
        requests: list[VerificationRequest],
        *,
        provider: str,
        actor_id: uuid.UUID | str,
    ) -> list[VerificationResult]:
        """Run a batch of checks submitted together as one payload and
        persist one `VerificationResult` per check, all in a single
        transaction — the "one payload produces many `VerificationResult`
        rows" shape a real RXIL integration will need (the EXP-2 plan's point
        6), proven here end-to-end against `StubRxilAdapter`. RXIL results
        intake itself is BLOCKED on the RXIL package contract (D12); this has
        no production caller.

        Resolves `provider` via the exact same registry
        `trigger_verification` uses (`workflow_dependencies.get_adapter`),
        but additionally requires the resolved adapter to satisfy
        `BatchVerificationAdapter` — raises `ProviderCapabilityError` for a
        provider that doesn't (e.g. `manual`), rather than silently looping
        single `.verify()` calls, which would neither be one transaction nor
        honestly represent a provider that never declared batch support as
        supporting it.

        Like `trigger_verification`, this method's own source contains no
        `verification_type` branching — each request in the batch can be a
        different `verification_type`/`entity_type` combination (that's the
        point: one RXIL payload can carry KYB + AML + INVOICE_DUPLICATION
        together), and every one of them is handled by the exact same loop.
        Subjects are validated exactly as `trigger_verification` validates
        them, before the adapter is called.

        All-or-nothing: if the adapter raises, or returns a mismatched number
        of outcomes, nothing is persisted — no partial batch ever lands in
        `verification_result`.
        """
        if not requests:
            raise ValidationError("trigger_verification_batch requires at least one request")

        # Validated up front, before the adapter is called, so an
        # uninterpretable pair or a ghost subject anywhere in the batch fails the
        # whole batch rather than being rejected after a provider has already
        # done work.
        subjects: list[_Subject] = []
        for candidate in requests:
            _validate_type_pair(candidate.verification_type, candidate.entity_type)
            candidate_subject = await self._resolve_subject(
                candidate.entity_type, _as_uuid(candidate.entity_reference), new_check=True
            )
            await self._check_evidence_documents(
                candidate.evidence, candidate.entity_type, candidate_subject
            )
            subjects.append(candidate_subject)

        adapter_cls = get_adapter(provider)
        adapter = adapter_cls()
        if not isinstance(adapter, BatchVerificationAdapter):
            raise ProviderCapabilityError(provider, "verify_batch")

        outcomes = adapter.verify_batch(requests)
        if len(outcomes) != len(requests):
            raise ValidationError(
                f"provider '{provider}' returned {len(outcomes)} outcomes for "
                f"{len(requests)} requests in the batch"
            )

        await share_lock_companies(
            self._db,
            _company_subjects(
                (request.entity_type, _as_uuid(request.entity_reference)) for request in requests
            ),
        )
        results: list[VerificationResult] = []
        for request, outcome, subject in zip(requests, outcomes, subjects, strict=True):
            result = _result_from_outcome(
                verification_type=request.verification_type,
                entity_type=request.entity_type,
                entity_reference=_as_uuid(request.entity_reference),
                raw_result=dict(request.payload),
                outcome=outcome,
                evidence=request.evidence,
                subject_snapshot=subject.snapshot,
                subject_company_id=subject.subject_company_id,
            )
            await self._stamp_cycle(
                result,
                actor_id=str(actor_id),
                source="verification_service.trigger_verification_batch",
            )
            self._db.add(result)
            await self._db.flush()
            await self._record_history(
                subject,
                to_value=outcome.status.value,
                from_value=None,
                actor_id=str(actor_id),
                source="verification_service.trigger_verification_batch",
                details=_result_details(result),
            )
            results.append(result)

        await self._db.commit()
        for result in results:
            await self._db.refresh(result)

        logger.info(
            "verification.batch_triggered",
            provider=provider,
            count=len(results),
            verification_result_ids=[str(r.id) for r in results],
            actor_id=str(actor_id),
        )
        return results

    # ── Poll ─────────────────────────────────────────────────────────────────

    async def get_verification_status(self, provider_reference: str) -> VerificationResult:
        """Poll the owning adapter for an asynchronous check's current status.

        Looks up the stored row by `provider_reference` (the most recently
        performed one, if more than one shares it — a caller retrying a
        submission with the same reference is the expected case), asks that
        row's own `provider` adapter for its current status, and updates the
        row if the answer has changed. A synchronous adapter (e.g.
        `ManualEntryAdapter`) never has a `PENDING` row to poll in practice,
        since it resolves everything in `trigger_verification`'s call to
        `.verify()` — its `get_verification_status` raises rather than being
        reached here for a normal caller.

        **A reviewed result is never changed** (4b-task.md §5.2, L4-02): once it
        has any review, a different provider answer is logged
        (`verification.status_polled.ignored_reviewed`, with the provider's new
        values) and the row is returned untouched. The provider is asked first,
        with no lock held while it works (as in `trigger_verification`); the row is
        then re-read `FOR UPDATE` — the same lock `record_review` takes — and the
        answer is judged against the row as it is *then*, so a review that landed
        while the provider was working is seen, and a review and a poll's write
        cannot interleave. `trg_verification_result_outcome_freeze` refuses the
        write at the database for anything that does not come through here.

        Polling has no production caller and no scheduler; none is added.

        Raises:
            NotFoundError: no `VerificationResult` carries this
                `provider_reference`.
        """
        not_found = NotFoundError(
            f"No verification_result found for provider_reference '{provider_reference}'"
        )
        found = (
            await self._db.execute(
                select(VerificationResult)
                .where(VerificationResult.provider_reference == provider_reference)
                .order_by(VerificationResult.performed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if found is None:
            raise not_found

        # The provider works with no row lock held.
        adapter_cls = get_adapter(found.provider)
        adapter = adapter_cls()
        outcome = adapter.get_verification_status(provider_reference)

        # Then the row as it is now, under the lock `record_review` takes.
        result = (
            await self._db.execute(
                select(VerificationResult)
                .where(VerificationResult.id == found.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if result is None:  # pragma: no cover — results are never deleted
            raise not_found

        changed = (
            outcome.status != result.status
            or outcome.risk_level != result.risk_level
            or outcome.normalized_result != result.normalized_result
            or outcome.valid_until != result.valid_until
        )
        if not changed:
            await self._db.commit()  # ends the transaction and releases the row lock
            return result

        if await self._is_reviewed(result):
            await self._db.commit()
            logger.warning(
                "verification.status_polled.ignored_reviewed",
                verification_result_id=str(result.id),
                provider=result.provider,
                provider_reference=provider_reference,
                stored_status=result.status.value,
                provider_status=outcome.status.value,
                provider_risk_level=(
                    outcome.risk_level.value if outcome.risk_level is not None else None
                ),
                provider_normalized_result=outcome.normalized_result,
                provider_valid_until=(
                    outcome.valid_until.isoformat() if outcome.valid_until is not None else None
                ),
            )
            return result

        previous_status = result.status
        await share_lock_companies(self._db, _subject_companies(result))
        result.status = outcome.status
        result.risk_level = outcome.risk_level
        result.normalized_result = outcome.normalized_result
        result.valid_until = outcome.valid_until
        self._db.add(result)
        await self._db.flush()
        if previous_status != outcome.status:
            await self._record_history(
                await self._history_target(result),
                to_value=outcome.status.value,
                from_value=previous_status.value,
                actor_id=None,  # the provider, not a person
                source="verification_service.get_verification_status",
                details=_result_details(result),
            )
        await self._db.commit()
        await self._db.refresh(result)
        logger.info(
            "verification.status_polled.changed",
            verification_result_id=str(result.id),
            provider=result.provider,
            previous_status=previous_status.value,
            new_status=result.status.value,
        )
        return result

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_verification_results(
        self, entity_type: VerificationEntityType, entity_reference: uuid.UUID | str
    ) -> list[VerificationResult]:
        """Every check ever run against one exporter/buyer/director/invoice/
        vessel/shipment, most recent first (ties broken by `created_at`, `id`).

        A company (`EXPORTER`) is read by the company-keyed rule (P4-5,
        `about_company`): its own results, and a deal buyer's results the deal-buyer
        migration mapped to it — one set of checks per company, wherever the company
        appears. A `BUYER` reference still lists that deal buyer's own results (legacy
        deals)."""
        reference = _as_uuid(entity_reference)
        subject_filter = (
            about_company(reference)
            if entity_type == VerificationEntityType.EXPORTER
            else (
                (VerificationResult.entity_type == entity_type)
                & (VerificationResult.entity_reference == reference)
            )
        )
        stmt = (
            select(VerificationResult)
            .where(subject_filter)
            .order_by(
                VerificationResult.performed_at.desc(),
                VerificationResult.created_at.desc(),
                VerificationResult.id.desc(),
            )
        )
        execution = await self._db.execute(stmt)
        return list(execution.scalars().all())

    async def accepts_new_check(
        self, entity_type: VerificationEntityType, entity_reference: uuid.UUID | str
    ) -> bool:
        """Whether a new check may be recorded on this subject now: false for a
        buyer whose deal is ``HANDED_OVER`` or ``WITHDRAWN`` (D17), so the served
        ``can_record_result`` agrees with the 409 ``trigger_verification`` would
        give. Any other subject — including one that does not exist, whose write
        would be a 404 rather than a closed door — answers true."""
        if entity_type != VerificationEntityType.BUYER:
            return True
        buyer = await DealBuyerRepository(self._db).get(_as_uuid(entity_reference))
        if buyer is None:
            return True
        deal = await DealRepository(self._db).get_by_id(buyer.deal_id)
        return deal is None or not deal.stage.is_terminal

    async def views_for(
        self, results: Sequence[VerificationResult]
    ) -> list[VerificationResultView]:
        """Attach each result's review chain, in one query."""
        chains = await self._reviews.chains_for(result.id for result in results)
        return [
            VerificationResultView(result=result, reviews=chains.get(result.id, ()))
            for result in results
        ]

    async def get_result_view(self, verification_result_id: uuid.UUID) -> VerificationResultView:
        """One result with its review chain.

        Raises:
            NotFoundError: no such result.
        """
        result = await self._db.get(VerificationResult, verification_result_id)
        if result is None:
            raise NotFoundError(f"No verification_result found with id '{verification_result_id}'")
        return (await self.views_for([result]))[0]

    # ── Review ───────────────────────────────────────────────────────────────

    async def record_review(
        self,
        verification_result_id: uuid.UUID | str,
        *,
        reviewed_by: str,
        review_status: VerificationReviewStatus,
        note: str | None = None,
        supersedes_review_id: uuid.UUID | None = None,
    ) -> VerificationReview:
        """Record a compliance reviewer's decision as a new, immutable review.

        The first review names no `supersedes_review_id`. Every later review must
        name the result's **current** review (the chain head) and give a `note`;
        otherwise `VerificationReviewStaleError` (409) — a reviewer never silently
        overrules a review they did not see. Earlier reviews are never edited: the
        table refuses it, and the unique supersedes pointer and the one-first-
        review index mean two concurrent reviewers cannot fork the chain — the one
        that loses the race gets the same 409.

        The result row is taken `FOR UPDATE` first (the lock polling takes too), so
        reviews of one result are judged one at a time. The legacy
        `reviewed_by`/`review_status` columns are not written.

        Writes one `verification` history row: `from_value` the previous review's
        status (or `None`), `to_value` the new one, `reason` the note.

        Raises:
            NotFoundError: no such `VerificationResult`.
            VerificationResultNotReviewableError: still `PENDING` (422).
            VerificationLegacyReviewUnchainedError: the result has a legacy
                `review_status` but no review record to supersede (409; only
                reachable if the legacy columns were written outside the service).
            VerificationReviewStaleError: `supersedes_review_id` is not the current
                review (409).
            ValidationError: a superseding review without a note (422).
        """
        result_id = _as_uuid(verification_result_id)
        stmt = (
            select(VerificationResult)
            .where(VerificationResult.id == result_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        execution = await self._db.execute(stmt)
        result = execution.scalar_one_or_none()
        if result is None:
            raise NotFoundError(f"No verification_result found with id '{result_id}'")

        if result.status == VerificationResultStatus.PENDING:
            raise VerificationResultNotReviewableError(verification_result_id=result_id)

        chain = await self._reviews.chain_for(result_id)
        if not chain and result.review_status is not None:
            # A legacy verdict with no review record (set outside the service after
            # migration 0021, which copied every earlier one). A "first" review here
            # would overrule it with no supersede link and no reason — refused.
            raise VerificationLegacyReviewUnchainedError(
                verification_result_id=result_id,
                legacy_review_status=result.review_status.value,
            )
        head = chain[-1] if chain else None
        current_head_id = head.id if head is not None else None
        if supersedes_review_id != current_head_id:
            raise VerificationReviewStaleError(
                verification_result_id=result_id, current_review_id=current_head_id
            )

        cleaned_note = (note or "").strip() or None
        if head is not None and cleaned_note is None:
            raise ValidationError("a review that supersedes another must say why (note)")

        await share_lock_companies(self._db, _subject_companies(result))
        review = VerificationReview(
            verification_result_id=result_id,
            review_status=review_status,
            reviewed_by=reviewed_by,
            note=cleaned_note,
            supersedes_review_id=supersedes_review_id,
        )
        try:
            review = await self._reviews.create(review)
        except IntegrityError:
            await self._db.rollback()
            latest = await self._reviews.chain_for(result_id)
            raise VerificationReviewStaleError(
                verification_result_id=result_id,
                current_review_id=latest[-1].id if latest else None,
            ) from None

        await self._record_history(
            await self._history_target(result),
            to_value=review_status.value,
            from_value=head.review_status.value if head is not None else None,
            actor_id=reviewed_by,
            source="verification_service.record_review",
            reason=cleaned_note,
            event_type=REVIEW_EVENT,
            details={
                "verification_result_id": str(result_id),
                "review_id": str(review.id),
                "supersedes_review_id": (
                    str(supersedes_review_id) if supersedes_review_id is not None else None
                ),
                "verification_type": result.verification_type.value,
            },
        )

        try:
            await self._db.commit()
        except DBAPIError:
            await self._db.rollback()
            raise

        await self._db.refresh(review)
        logger.info(
            "verification.reviewed",
            verification_result_id=str(result_id),
            review_id=str(review.id),
            supersedes_review_id=(
                str(supersedes_review_id) if supersedes_review_id is not None else None
            ),
            reviewed_by=reviewed_by,
            review_status=review_status.value,
        )
        return review


def _result_details(result: VerificationResult) -> dict[str, Any]:
    details = {
        "verification_result_id": str(result.id),
        "verification_type": result.verification_type.value,
        "entity_type": result.entity_type.value,
        "entity_reference": str(result.entity_reference),
        "provider": result.provider,
    }
    if result.cycle_id is not None:
        details["cycle_id"] = str(result.cycle_id)
    return details


__all__ = ["VerificationResultView", "VerificationService"]
