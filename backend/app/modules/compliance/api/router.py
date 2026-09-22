import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.api.schemas import (
    ApprovalsStateResponse,
    ApprovalSubmittedResponse,
    ScreeningRunResponse,
    SubmitApprovalRequest,
)
from app.modules.compliance.application.services import ComplianceService
from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/screen/{transaction_id}",
    response_model=ScreeningRunResponse,
    summary="Run full compliance screening on a transaction",
    description=(
        "Performs KYB validation, OFAC/UN/EU/RBI sanctions screening, "
        "DNFBP classification, and AML risk scoring. "
        "Transitions the transaction from INITIATED to UNDER_REVIEW, BLOCKED, or VALIDATION_FAILED. "
        "In production this is invoked as a Temporal Activity; the endpoint exists for the thin slice."
    ),
    responses={
        200: {"model": ScreeningRunResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE role required"},
        404: {"description": "Transaction not found"},
        409: {"description": "Transaction has already been screened"},
    },
)
async def screen_transaction(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role(UserRole.COMPLIANCE))],
    db: AsyncSession = Depends(get_db),
) -> ScreeningRunResponse:
    svc = ComplianceService(db)
    return await svc.run_screening(transaction_id, current_user)


@router.post(
    "/approvals",
    response_model=ApprovalSubmittedResponse,
    summary="Submit a MAKER or CHECKER compliance approval",
    description=(
        "The system determines whether this is a MAKER or CHECKER submission based on "
        "existing approvals for the transaction. The same user cannot submit both roles "
        "on the same transaction (enforced at the application layer and by DB constraint). "
        "A REJECTION from either role moves the transaction to DECLINED."
    ),
    responses={
        200: {"model": ApprovalSubmittedResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE role required"},
        404: {"description": "Transaction not found"},
        409: {"description": "Duplicate approver or approval already complete"},
        422: {"description": "Transaction not in UNDER_REVIEW status"},
    },
)
async def submit_approval(
    body: SubmitApprovalRequest,
    current_user: Annotated[User, Depends(require_role(UserRole.COMPLIANCE))],
    db: AsyncSession = Depends(get_db),
) -> ApprovalSubmittedResponse:
    svc = ComplianceService(db)
    return await svc.submit_approval(body, current_user)


@router.get(
    "/approvals/{transaction_id}",
    response_model=ApprovalsStateResponse,
    summary="Get approval state for a transaction",
    responses={
        200: {"model": ApprovalsStateResponse},
        401: {"description": "Unauthorized"},
        404: {"description": "Transaction not found"},
    },
)
async def get_approvals(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> ApprovalsStateResponse:
    svc = ComplianceService(db)
    return await svc.get_approvals(transaction_id)


@router.get(
    "/screenings/{transaction_id}",
    response_model=ScreeningRunResponse,
    summary="Get screening results for a transaction",
    responses={
        200: {"model": ScreeningRunResponse},
        401: {"description": "Unauthorized"},
        404: {"description": "Transaction not found"},
    },
)
async def get_screenings(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningRunResponse:
    svc = ComplianceService(db)
    return await svc.get_screenings(transaction_id)
