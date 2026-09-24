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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# Importing the adapters package runs its module-level `register_adapter(...)`
# calls (see infrastructure/adapters/__init__.py's docstring) — the same way
# `kyb/__init__.py` imports `MiddeskAdapter` to register it. Nothing else in
# this module names a concrete adapter: this import exists solely so
# `get_adapter("manual")` has something to find.
import app.modules.onboarding.infrastructure.adapters  # noqa: F401
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.workflow_dependencies import (
    BatchVerificationAdapter,
    VerificationOutcome,
    VerificationRequest,
    get_adapter,
)
from app.modules.onboarding.exceptions import (
    ProviderCapabilityError,
    VerificationResultAlreadyReviewedError,
    VerificationResultNotReviewableError,
)
from app.shared.exceptions import NotFoundError, ValidationError

logger = structlog.get_logger(__name__)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


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
    # Composite risk banding — about a counterparty, never a trade object. The
    # rating is computed from entity type, country, sector, declared volume and
    # UBO/screening signals, none of which an invoice, vessel or shipment has.
    VerificationType.RISK_RATING: frozenset(
        {VerificationEntityType.EXPORTER, VerificationEntityType.BUYER}
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
    )


class VerificationService:
    """Trigger, poll, list and review `VerificationResult` rows."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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
            entity_reference: That entity's own id.
            provider: The registry name to resolve. Defaults to `"manual"`
                (`ManualEntryAdapter`) — the only adapter this ticket ships.
            payload: Type-specific input. For `ManualEntryAdapter`, this is
                where the manually-observed result itself travels (see its
                module docstring); for a future real vendor adapter, this is
                whatever that vendor's `verify()` needs to submit a check.
            actor_id: Who/what triggered this check, for the audit log line.

        Returns:
            The persisted, refreshed `VerificationResult`.
        """
        # Before the adapter is resolved or called: a pair this service
        # cannot interpret must not reach a provider or a row.
        _validate_type_pair(verification_type, entity_type)

        adapter_cls = get_adapter(provider)
        adapter = adapter_cls()

        reference = _as_uuid(entity_reference)
        request_payload = dict(payload or {})
        request = VerificationRequest(
            verification_type=verification_type,
            entity_type=entity_type,
            entity_reference=str(reference),
            payload=request_payload,
        )

        outcome = adapter.verify(request)

        result = _result_from_outcome(
            verification_type=verification_type,
            entity_type=entity_type,
            entity_reference=reference,
            raw_result=request_payload,
            outcome=outcome,
        )
        self._db.add(result)
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
        6), proven here end-to-end against `StubRxilAdapter`.

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

        All-or-nothing: if the adapter raises, or returns a mismatched number
        of outcomes, nothing is persisted — no partial batch ever lands in
        `verification_result`.
        """
        if not requests:
            raise ValidationError("trigger_verification_batch requires at least one request")

        # Validated up front, before the adapter is called, so an
        # uninterpretable pair anywhere in the batch fails the whole batch
        # rather than being rejected after a provider has already done work.
        for candidate in requests:
            _validate_type_pair(candidate.verification_type, candidate.entity_type)

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

        results: list[VerificationResult] = []
        for request, outcome in zip(requests, outcomes, strict=True):
            result = _result_from_outcome(
                verification_type=request.verification_type,
                entity_type=request.entity_type,
                entity_reference=_as_uuid(request.entity_reference),
                raw_result=dict(request.payload),
                outcome=outcome,
            )
            self._db.add(result)
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
        row if the status has changed. A synchronous adapter (e.g.
        `ManualEntryAdapter`) never has a `PENDING` row to poll in practice,
        since it resolves everything in `trigger_verification`'s call to
        `.verify()` — its `get_verification_status` raises rather than being
        reached here for a normal caller.

        Raises:
            NotFoundError: no `VerificationResult` carries this
                `provider_reference`.
        """
        stmt = (
            select(VerificationResult)
            .where(VerificationResult.provider_reference == provider_reference)
            .order_by(VerificationResult.performed_at.desc())
            .limit(1)
        )
        execution = await self._db.execute(stmt)
        result = execution.scalar_one_or_none()
        if result is None:
            raise NotFoundError(
                f"No verification_result found for provider_reference '{provider_reference}'"
            )

        adapter_cls = get_adapter(result.provider)
        adapter = adapter_cls()
        outcome = adapter.get_verification_status(provider_reference)

        if (
            outcome.status != result.status
            or outcome.risk_level != result.risk_level
            or outcome.normalized_result != result.normalized_result
            or outcome.valid_until != result.valid_until
        ):
            previous_status = result.status
            result.status = outcome.status
            result.risk_level = outcome.risk_level
            result.normalized_result = outcome.normalized_result
            result.valid_until = outcome.valid_until
            self._db.add(result)
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

    # ── List ─────────────────────────────────────────────────────────────────

    async def list_verification_results(
        self, entity_type: VerificationEntityType, entity_reference: uuid.UUID | str
    ) -> list[VerificationResult]:
        """Every check ever run against one exporter/buyer/director/invoice/
        vessel/shipment, most recent first."""
        reference = _as_uuid(entity_reference)
        stmt = (
            select(VerificationResult)
            .where(
                VerificationResult.entity_type == entity_type,
                VerificationResult.entity_reference == reference,
            )
            .order_by(VerificationResult.performed_at.desc())
        )
        execution = await self._db.execute(stmt)
        return list(execution.scalars().all())

    # ── Review ───────────────────────────────────────────────────────────────

    async def record_review(
        self,
        verification_result_id: uuid.UUID | str,
        *,
        reviewed_by: str,
        review_status: VerificationReviewStatus,
    ) -> VerificationResult:
        """Record a compliance reviewer's decision.

        `reviewed_by`/`review_status` are immutable once set — see
        `VerificationResultAlreadyReviewedError`'s docstring for the reasoning
        and the documented risk of that choice. This method raises that
        exception itself, as a clean domain error, before ever attempting the
        write; `trg_verification_result_field_immutability` (migration
        `onboarding_0006_verif_result`) is the defense-in-depth path if
        a write reaches Postgres some other way.

        Raises:
            NotFoundError: no such `VerificationResult`.
            VerificationResultAlreadyReviewedError: already reviewed.
            VerificationResultNotReviewableError: still `PENDING` — there is
                no finding yet, and a review cannot be undone.
        """
        result_id = _as_uuid(verification_result_id)
        stmt = (
            select(VerificationResult)
            .where(VerificationResult.id == result_id)
            .with_for_update()
        )
        execution = await self._db.execute(stmt)
        result = execution.scalar_one_or_none()
        if result is None:
            raise NotFoundError(f"No verification_result found with id '{result_id}'")

        if result.reviewed_by is not None or result.review_status is not None:
            raise VerificationResultAlreadyReviewedError(verification_result_id=result_id)

        if result.status == VerificationResultStatus.PENDING:
            raise VerificationResultNotReviewableError(verification_result_id=result_id)

        result.reviewed_by = reviewed_by
        result.review_status = review_status
        self._db.add(result)

        try:
            await self._db.commit()
        except DBAPIError:
            await self._db.rollback()
            raise

        await self._db.refresh(result)
        logger.info(
            "verification.reviewed",
            verification_result_id=str(result_id),
            reviewed_by=reviewed_by,
            review_status=review_status.value,
        )
        return result


__all__ = ["VerificationService"]
