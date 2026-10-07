"""Sample data for the background check, with the screening inputs through
``ScreeningReviewService``.

Called from ``sample_data.py``'s hook, after every sample company exists and before
the deals hook: company B must be a ``CUSTOMER`` before one of its deals can be handed
over.

Architecture §3.9: company B's check is ``CLEAR`` — which makes the qualified
``PROSPECT`` a ``CUSTOMER`` in the same transaction
(``ExporterProfileService.promote_to_customer_if_ready``) — and company C's is
``FLAGGED``, so its deal cannot be handed over.

**Through the services, nothing written directly.** The screening decisions (seven
items) go through ``ScreeningReviewService``; every move goes through
``BackgroundCheckService`` with its default reader and the shipped ``CLEAR_POLICY``. So B
is cleared only because its inputs really meet the four prerequisites, and C is flagged the
way the architecture says a failed screening item leads to: a ``FAILED`` item, then
``FLAGGED`` with a reason.

Converges like every other seeder: an item already at its sample answer is not
answered again, and a company already at its target value records no decision, so a
repeat run reports zero. A company found somewhere else on the gauge (someone moved it
by hand) is left alone and logged, never forced.

**Maker-checker and the passed-checks rule.** No single seeded actor
takes a company to ``CLEAR`` or ``FLAGGED``: ``SAMPLE_DATA_ACTOR`` proposes and a second
seeded officer, ``SAMPLE_DATA_CHECKER``, approves — the two-person path every user
takes. Company B's KYB, AML and sanctions are recorded as manual ``PASSED`` results
(through ``VerificationService``) before it is proposed, because a Clear
needs them. A proposal a previous run left open for the sample's target is
approved rather than proposed again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    ScreeningReviewService,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_POLICY,
    required_check_states,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

_State = BackgroundCheckState

#: The second seeded compliance officer, who approves what ``SAMPLE_DATA_ACTOR``
#: proposes (maker-checker). Not a user account, like the first.
SAMPLE_DATA_CHECKER = "sample-data-checker"


@dataclass(frozen=True)
class _SampleCheck:
    """Where one sample company's check should end up, and on what inputs."""

    target: BackgroundCheckState
    #: Screening answers that differ from ``PASSED``; every other catalogue item is
    #: answered ``PASSED``.
    exceptions: tuple[tuple[str, str, str], ...] = ()  # (item_key, status, comment)
    reason: str = ""
    risk: BackgroundCheckRisk | None = None


#: Keyed by the sample company's slug, from ``sample_data.COMPANIES``.
SAMPLE_CHECKS: dict[str, _SampleCheck] = {
    # §3.9 company B: cleared at LOW risk, and so a customer.
    "company-b": _SampleCheck(
        target=_State.CLEAR,
        reason="Sample data: every screening item passed; nothing adverse found.",
        risk=BackgroundCheckRisk.LOW,
    ),
    # §3.9 company C: flagged. A failed screening item is what FLAGGED is for.
    "company-c": _SampleCheck(
        target=_State.FLAGGED,
        exceptions=(
            (
                "suspicious-bank-indicators",
                "FAILED",
                "Sample data: unexplained round-tripping between two related accounts.",
            ),
        ),
        reason="Sample data: suspicious bank indicators need a closer look.",
    ),
}


async def load_background_check_sample_data() -> int:
    """Bring each sample company's check to its §3.9 value.

    Returns the number of background-check decisions this run recorded — ``0`` on a
    repeat run.
    """
    # Imported here: `sample_data` imports this module (same reason as the deals hook).
    from app.modules.onboarding.sample_data import COMPANIES, SAMPLE_DATA_ACTOR

    slugs = {company.slug: company.customer_id for company in COMPANIES}
    decided = 0
    for slug, sample in SAMPLE_CHECKS.items():
        company_id = slugs.get(slug)
        if company_id is None:  # pragma: no cover - a renamed sample company
            logger.warning("sample_background_check.company_missing", slug=slug)
            continue
        await _ensure_screening(company_id, sample, actor_id=SAMPLE_DATA_ACTOR)
        decided += await _ensure_gauge(company_id, sample, actor_id=SAMPLE_DATA_ACTOR)
    return decided


async def _ensure_required_checks(company_id: uuid.UUID, *, actor_id: str) -> None:
    """The passed-checks rule: record a manual ``PASSED`` result of each type a Clear
    requires that has not passed in the current cycle yet."""
    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)
    for required in required_check_states(inputs, CLEAR_POLICY):
        if required.state == "PASSED":
            continue
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).trigger_verification(
                VerificationType(required.verification_type),
                VerificationEntityType.EXPORTER,
                company_id,
                provider="manual",
                payload={"status": "PASSED"},
                actor_id=actor_id,
                evidence=VerificationEvidence(
                    note=(
                        f"Sample data: {required.verification_type} checked manually; "
                        "nothing found."
                    )
                ),
            )


async def _ensure_screening(company_id: uuid.UUID, sample: _SampleCheck, *, actor_id: str) -> None:
    """Answer every catalogue item as the sample says, skipping any already answered
    that way. Read through the compliance-inputs seam, written through the screening service."""
    exceptions = {key: (status, comment) for key, status, comment in sample.exceptions}
    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)
    current = {item.item_key: item.status for item in inputs.screening_items}
    for key in SCREENING_CATALOGUE:
        status, comment = exceptions.get(key, ("PASSED", None))
        if current.get(key) == status:
            continue
        async with db_services.AsyncSessionLocal() as db:
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key=key, status=status, comment=comment, actor_id=actor_id
            )


async def _ensure_gauge(company_id: uuid.UUID, sample: _SampleCheck, *, actor_id: str) -> int:
    """Walk the gauge to the sample's target by the architecture's own moves."""
    decided = 0
    state = await _state(company_id)
    if state is _State.NOT_STARTED:
        async with db_services.AsyncSessionLocal() as db:
            # The platform's own loader, like an import: it names no RM.
            await BackgroundCheckService(db).start_review(
                company_id,
                actor_id=actor_id,
                actor_role=UserRole.OPERATIONS,
                require_relationship_manager=False,
            )
        decided += 1
        state = _State.IN_REVIEW
    if state is sample.target:
        return decided
    if state is not _State.IN_REVIEW:
        logger.warning(
            "sample_background_check.left_alone",
            company_id=str(company_id),
            state=state.value,
            target=sample.target.value,
        )
        return decided

    # Maker-checker: the sample actor proposes, the second seeded officer approves. A
    # proposal an earlier run left open for this target is approved, not repeated.
    async with db_services.AsyncSessionLocal() as db:
        awaiting = await BackgroundCheckService(db).open_proposal(company_id)
    if awaiting is not None and awaiting[0].to_value is not sample.target:
        logger.warning(
            "sample_background_check.left_alone",
            company_id=str(company_id),
            open_proposal=awaiting[0].to_value.value,
            target=sample.target.value,
        )
        return decided
    if awaiting is None:
        if sample.target is _State.CLEAR:
            # Only now, on a company about to be proposed for CLEAR: one already at its
            # target is left exactly as it is.
            await _ensure_required_checks(company_id, actor_id=actor_id)
        async with db_services.AsyncSessionLocal() as db:
            proposal = await BackgroundCheckService(db).propose(
                company_id,
                to_value=sample.target,
                risk=sample.risk if sample.target is _State.CLEAR else None,
                reason=sample.reason,
                actor_id=actor_id,
                actor_role=UserRole.COMPLIANCE,
            )
        proposal_id = proposal.id
    else:
        proposal_id = awaiting[0].id
    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).approve(
            company_id, proposal_id, actor_id=SAMPLE_DATA_CHECKER, actor_role=UserRole.COMPLIANCE
        )
    logger.info(
        "sample_background_check.decided",
        company_id=str(company_id),
        target=sample.target.value,
    )
    return decided + 1


async def _state(company_id: uuid.UUID) -> BackgroundCheckState:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.background_check).where(
                ExporterProfile.customer_id == company_id
            )
        )


__all__ = ["SAMPLE_CHECKS", "SAMPLE_DATA_CHECKER", "load_background_check_sample_data"]
