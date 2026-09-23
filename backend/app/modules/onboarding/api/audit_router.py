"""Onboarding audit routes: read-only compliance artifacts.

`OnboardingQueryService.get_onboarding_evidence_package` (S7T2) was complete and
tested, but only one integration test called it. Its docstring leaves "restrict
the evidence package to compliance-officer callers" to the router layer. This
is that router.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.onboarding_query_service import OnboardingQueryService
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/audit", tags=["Onboarding audit"])

# Unredacted by design (the service assembles it as COMPLIANCE regardless of
# caller), so the gate here is the only thing standing between it and a reader.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)

SCREENING_EVIDENCE_UNAVAILABLE_REASON = (
    "Epic 3.2 (screening) is not present in this checkout, so there is no screening "
    "result API to fetch from. screening_evidence is always null here. That means "
    "absent, not 'screened and clear'."
)


class EvidencePackageResponse(BaseModel):
    onboarding_id: uuid.UUID
    detail: dict[str, Any] = Field(
        description="The full, unredacted onboarding record (OnboardingDetailView)"
    )
    screening_evidence: dict[str, Any] | None = Field(
        description="Always null in this checkout; see screening_evidence_status"
    )
    screening_evidence_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    screening_evidence_reason: str = SCREENING_EVIDENCE_UNAVAILABLE_REASON


@router.get(
    "/onboarding-requests/{onboarding_id}/evidence-package",
    response_model=EvidencePackageResponse,
    summary="Onboarding evidence package",
    description=(
        "The aggregated, unredacted onboarding record for compliance and regulatory "
        "use: entity details, UBOs, documents, events and KYB vendor results. "
        "Screening evidence is not included: Epic 3.2 is absent from this "
        "checkout, and the response says so (`screening_evidence_status`) rather "
        "than returning a silent null."
    ),
    responses={
        200: {"model": EvidencePackageResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Onboarding request not found"},
    },
)
async def get_onboarding_evidence_package(
    onboarding_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> EvidencePackageResponse:
    package = await OnboardingQueryService(db).get_onboarding_evidence_package(onboarding_id)
    return EvidencePackageResponse(
        onboarding_id=onboarding_id,
        detail=jsonable_encoder(dataclasses.asdict(package.detail)),
        screening_evidence=package.screening_evidence,
    )


__all__ = ["router"]
