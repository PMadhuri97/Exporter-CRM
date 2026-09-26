"""Qualification routes — **owner: Developer 2** (L2-09, L2-10).

Criteria are managed by ADMIN only; results and outcomes are recorded by
OPERATIONS, COMPLIANCE and ADMIN; every CRM reader may read (architecture
§3.3, §3.7). All three gates are enforced here, on the server. The actor is
always the signed-in user.

Mounted by ``router.py`` under the module's ``/onboarding`` prefix.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.qualification import (
    CreateCriterionRequest,
    CriterionDefinitionRequest,
    CriterionListResponse,
    CriterionResponse,
    QualificationResponse,
    ReasonCodeListResponse,
    ReasonCodeResponse,
    RecordOutcomeRequest,
    RecordResultsRequest,
)
from app.modules.onboarding.application.qualification_service import QualificationService
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Qualification"])

#: Criterion administration and versions (architecture §3.7).
_ADMIN = require_role(UserRole.ADMIN)
#: Recording results and outcomes.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
#: Reading. DEVELOPER is read-only across the CRM.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)

_401 = {"description": "Unauthorized"}
_403_ADMIN = {"description": "ADMIN role required"}
_403_STAFF = {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}
_403_READER = {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"}


# ── Criteria ─────────────────────────────────────────────────────────────────


@router.get(
    "/qualification/criteria",
    response_model=CriterionListResponse,
    summary="List the current version of every qualification criterion",
    responses={401: _401, 403: _403_READER},
)
async def list_qualification_criteria(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> CriterionListResponse:
    criteria = await QualificationService(db).list_criteria()
    return CriterionListResponse(criteria=[CriterionResponse.of(c) for c in criteria])


@router.post(
    "/qualification/criteria",
    response_model=CriterionResponse,
    status_code=201,
    summary="Add a qualification criterion (version 1)",
    responses={
        401: _401,
        403: _403_ADMIN,
        409: {"description": "A criterion with this key already exists"},
        422: {"description": "Invalid criterion"},
    },
)
async def create_qualification_criterion(
    body: CreateCriterionRequest,
    current_user: Annotated[User, Depends(_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> CriterionResponse:
    criterion = await QualificationService(db).create_criterion(
        body.key, body.to_definition(), actor_id=str(current_user.id)
    )
    return CriterionResponse.of(criterion)


@router.get(
    "/qualification/criteria/{key}/versions",
    response_model=CriterionListResponse,
    summary="List every version of one criterion, oldest first",
    responses={401: _401, 403: _403_READER, 404: {"description": "Unknown criterion"}},
)
async def list_qualification_criterion_versions(
    key: str,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> CriterionListResponse:
    versions = await QualificationService(db).list_versions(key)
    return CriterionListResponse(criteria=[CriterionResponse.of(c) for c in versions])


@router.post(
    "/qualification/criteria/{key}/versions",
    response_model=CriterionResponse,
    status_code=201,
    summary="Change a criterion by adding its next version",
    description=(
        "Every change — threshold, allowed values, label, required, active — is a "
        "new version. Earlier versions are never altered, and results recorded "
        "against them keep pointing at them."
    ),
    responses={
        401: _401,
        403: _403_ADMIN,
        404: {"description": "Unknown criterion"},
        422: {"description": "Invalid criterion"},
    },
)
async def add_qualification_criterion_version(
    key: str,
    body: CriterionDefinitionRequest,
    current_user: Annotated[User, Depends(_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> CriterionResponse:
    criterion = await QualificationService(db).add_version(
        key, body.to_definition(), actor_id=str(current_user.id)
    )
    return CriterionResponse.of(criterion)


@router.get(
    "/qualification/reason-codes",
    response_model=ReasonCodeListResponse,
    summary="List the reason codes a NOT_QUALIFIED outcome may give",
    responses={401: _401, 403: _403_READER},
)
async def list_qualification_reason_codes(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ReasonCodeListResponse:
    codes = await QualificationService(db).list_reason_codes()
    return ReasonCodeListResponse(
        reason_codes=[ReasonCodeResponse.model_validate(c, from_attributes=True) for c in codes]
    )


# ── A company's qualification ────────────────────────────────────────────────


@router.get(
    "/exporters/{customer_id}/qualification",
    response_model=QualificationResponse,
    summary="A company's qualification: gauge, suggestion, results and outcomes",
    responses={401: _401, 403: _403_READER, 404: {"description": "Exporter profile not found"}},
)
async def get_exporter_qualification(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> QualificationResponse:
    view = await QualificationService(db).get_qualification(customer_id)
    return QualificationResponse.of(customer_id, view)


@router.post(
    "/exporters/{customer_id}/qualification/results",
    response_model=QualificationResponse,
    status_code=201,
    summary="Record criterion results for a company",
    description=(
        "Append-only: checking a criterion again adds a result, never changes one. "
        "Each result is pinned to the criterion's current version, which must be "
        "active. PASS and FAIL need evidence. Recorded as MANUAL, by the signed-in "
        "user. Results never move the gauge; they inform the suggestion."
    ),
    responses={
        401: _401,
        403: _403_STAFF,
        404: {"description": "Exporter profile not found"},
        409: {"description": "The company is already QUALIFIED"},
        422: {"description": "Invalid results"},
    },
)
async def record_exporter_qualification_results(
    customer_id: uuid.UUID,
    body: RecordResultsRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> QualificationResponse:
    service = QualificationService(db)
    await service.record_results(
        customer_id, [r.to_entry() for r in body.results], actor_id=str(current_user.id)
    )
    return QualificationResponse.of(customer_id, await service.get_qualification(customer_id))


@router.post(
    "/exporters/{customer_id}/qualification/outcome",
    response_model=QualificationResponse,
    status_code=201,
    summary="Record a qualification outcome (the reviewer's decision)",
    description=(
        "The signed-in reviewer's decision, stored beside the server's suggestion. "
        "Allowed from NOT_YET_REVIEWED and, as a re-review, from NOT_QUALIFIED; "
        "QUALIFIED is final. NOT_QUALIFIED needs at least one reason code. A "
        "QUALIFIED lead becomes a PROSPECT in the same transaction; qualification "
        "never makes a company a CUSTOMER."
    ),
    responses={
        401: _401,
        403: _403_STAFF,
        404: {"description": "Exporter profile not found"},
        409: {"description": "The company is already QUALIFIED"},
        422: {"description": "Missing or unknown reason codes, or other invalid input"},
    },
)
async def record_exporter_qualification_outcome(
    customer_id: uuid.UUID,
    body: RecordOutcomeRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> QualificationResponse:
    service = QualificationService(db)
    await service.record_outcome(
        customer_id,
        body.outcome,
        reason_codes=body.reason_codes,
        note=body.note,
        actor_id=str(current_user.id),
    )
    return QualificationResponse.of(customer_id, await service.get_qualification(customer_id))


__all__ = ["router"]
