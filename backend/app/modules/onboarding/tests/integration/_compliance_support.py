"""Shared scaffolding for the compliance-engine tests.
Not a test module (no ``test_`` prefix).

Real Postgres, no per-test rollback — every helper mints its own company, the
convention the rest of the onboarding suite follows. Everything goes through the real
services and the shipped ``CLEAR_POLICY``; ``approve_as`` proposes as the maker and
approves as the checker. A company is cleared on the required checks too (KYB, AML
and sanctions passed — ``record_required_checks``).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.check_cycle import CheckCycleKind
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.tests.fixtures.compliance import (
    ComplianceUser,
    approve_as,
    propose_as,
    record_required_checks,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

#: Service-level actors (plain ids), for tests that do not go through the API.
MAKER = ComplianceUser(user_id="mc-maker", role=UserRole.COMPLIANCE)
CHECKER = ComplianceUser(user_id="mc-checker", role=UserRole.COMPLIANCE)


async def answer_screening(
    company_id: uuid.UUID,
    *,
    status: str = "PASSED",
    keys: tuple[str, ...] = SCREENING_CATALOGUE,
    evidence: VerificationEvidence | None = None,
) -> list[Any]:
    """Answer each of ``keys`` (default: the whole catalogue) with ``status``."""
    rows = []
    for key in keys:
        async with db_services.AsyncSessionLocal() as db:
            rows.append(
                await ScreeningReviewService(db).upsert_review_item(
                    company_id,
                    item_key=key,
                    status=status,
                    comment=f"answered {status.lower()}",
                    actor_id=MAKER.user_id,
                    evidence=evidence,
                )
            )
    return rows


async def start_review(company_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )


async def move(company_id: uuid.UUID, to_value: BackgroundCheckState, reason: str = "because"):
    """Record a move that needs no approval (MORE_INFO, an answer, a reassessment, a
    reopen); for FLAGGED / ON_HOLD use :func:`flag`."""
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).record_decision(
            company_id,
            to_value=to_value,
            reason=reason,
            risk=None,
            actor_id=MAKER.user_id,
            actor_role=UserRole.COMPLIANCE,
        )


async def clear(company_id: uuid.UUID):
    """``IN_REVIEW → CLEAR`` by a maker and a checker (``approve_as``)."""
    return await approve_as(CHECKER, company_id, maker=MAKER)


async def flag(
    company_id: uuid.UUID,
    to_value: BackgroundCheckState = BackgroundCheckState.FLAGGED,
    reason: str = "a concern",
):
    """``FLAGGED`` or ``ON_HOLD`` by a maker and a checker."""
    return await approve_as(CHECKER, company_id, maker=MAKER, to_value=to_value, reason=reason)


async def propose(company_id: uuid.UUID, **kwargs):
    """A proposal by the maker, left open."""
    return await propose_as(MAKER, company_id, **kwargs)


async def ready_to_clear(company_id: uuid.UUID) -> uuid.UUID:
    """Answer the checklist, record the required checks and start the check."""
    await answer_screening(company_id)
    await record_required_checks(company_id, actor_id=MAKER.user_id)
    await start_review(company_id)
    return company_id


async def cleared_company(company_id: uuid.UUID) -> uuid.UUID:
    """Answer the checklist, record the required checks, start the check and clear it."""
    await ready_to_clear(company_id)
    await clear(company_id)
    return company_id


async def start_cycle(
    company_id: uuid.UUID,
    *,
    kind: CheckCycleKind = CheckCycleKind.RE_KYC,
    reason: str = "Annual re-check",
    role: UserRole = UserRole.COMPLIANCE,
):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).start_cycle(
            company_id, kind=kind, reason=reason, actor_id=MAKER.user_id, actor_role=role
        )


async def inputs(company_id: uuid.UUID):
    from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService

    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceInputsService(db).company_inputs(company_id)


async def gauge(company_id: uuid.UUID) -> BackgroundCheckState:
    from sqlalchemy import select

    from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile

    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.background_check).where(
                ExporterProfile.customer_id == company_id
            )
        )


__all__ = [
    "CHECKER",
    "MAKER",
    "answer_screening",
    "clear",
    "cleared_company",
    "flag",
    "gauge",
    "inputs",
    "move",
    "propose",
    "ready_to_clear",
    "start_cycle",
    "start_review",
]
