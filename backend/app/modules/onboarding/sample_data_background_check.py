"""Sample data for the background check — **owner: Developer 4A**, with the screening
inputs through Developer 4B's service.

Called from ``sample_data.py``'s hook, after every sample company exists and before
the deals hook: company B must be a ``CUSTOMER`` before one of its deals can be handed
over.

Architecture §3.9: company B's check is ``CLEAR`` — which makes the qualified
``PROSPECT`` a ``CUSTOMER`` in the same transaction (L2-11,
``ExporterProfileService.promote_to_customer_if_ready``) — and company C's is
``FLAGGED``, so its deal cannot be handed over.

**Through the services, nothing written directly.** The eight screening decisions go
through ``ScreeningReviewService``; every move goes through ``BackgroundCheckService``
with its default reader and the shipped ``CLEAR_POLICY``. So B is cleared only because
its inputs really meet A3's prerequisites, and C is flagged the way the architecture
says a failed screening item leads to (D3): a ``FAILED`` item, then ``FLAGGED`` with a
reason.

Converges like every other seeder: an item already at its sample answer is not
answered again, and a company already at its target value records no decision, so a
repeat run reports zero. A company found somewhere else on the gauge (someone moved it
by hand) is left alone and logged, never forced.
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
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

_State = BackgroundCheckState


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
        reason="Sample data: all eight screening items passed; nothing adverse found.",
        risk=BackgroundCheckRisk.LOW,
    ),
    # §3.9 company C: flagged. A failed screening item is what FLAGGED is for (D3).
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


async def _ensure_screening(company_id: uuid.UUID, sample: _SampleCheck, *, actor_id: str) -> None:
    """Answer every catalogue item as the sample says, skipping any already answered
    that way. Read through Developer 4B's seam, written through their service."""
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
            await BackgroundCheckService(db).start_review(
                company_id, actor_id=actor_id, actor_role=UserRole.OPERATIONS
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

    async with db_services.AsyncSessionLocal() as db:
        service = BackgroundCheckService(db)
        if sample.target is _State.CLEAR:
            await service.clear(
                company_id,
                risk=sample.risk,
                reason=sample.reason,
                actor_id=actor_id,
                actor_role=UserRole.COMPLIANCE,
            )
        else:
            await service.flag(
                company_id, reason=sample.reason, actor_id=actor_id, actor_role=UserRole.COMPLIANCE
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


__all__ = ["SAMPLE_CHECKS", "load_background_check_sample_data"]
