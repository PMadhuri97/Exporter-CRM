"""Screening-review checklist and bank-activity routes — **owner:
Developer 4** (architecture §8.1, §9.4).

Split out of `exporter_router.py` (L2-01) so the company routes and the
background-check routes stop sharing one file. Every route below is unchanged:
same path, method, function name, roles, response model and description, so
the OpenAPI document and the frontend's generated types do not move.

Mounted by `router.py` beside `exporter_router`, with the same `/exporters`
prefix and `Exporter CRM` tag, so every path stays `/onboarding/exporters/...`.

The screening checklist is a compliance list inside the background check. It is
not qualification (architecture §5.5).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.screening import (
    BankActivityFindingResponse,
    BankActivityResponse,
    ScreeningReviewItemResponse,
    ScreeningReviewListResponse,
    UpdateScreeningReviewItemRequest,
)
from app.modules.onboarding.application.screening_review_service import ScreeningReviewService
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

# Compliance decisions (recording a screening-checklist decision) are
# compliance-owned; a plain API_USER must never be able to mark a sanctions
# check PASSED.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)
# Routine CRM reads by internal staff.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


# ── E9 screening review workspace ─────────────────────────────────────────

@router.get(
    "/{customer_id}/screening-review",
    response_model=ScreeningReviewListResponse,
    summary="List persisted screening-review checklist decisions",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_screening_review(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewListResponse:
    items = await ScreeningReviewService(db).list_review_items(customer_id)
    return ScreeningReviewListResponse(
        customer_id=customer_id,
        items=[ScreeningReviewItemResponse.model_validate(item) for item in items],
    )


@router.put(
    "/{customer_id}/screening-review/{item_key}",
    response_model=ScreeningReviewItemResponse,
    summary="Record or update one screening-review checklist decision",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
    },
)
async def update_screening_review(
    customer_id: uuid.UUID,
    item_key: str,
    body: UpdateScreeningReviewItemRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewItemResponse:
    item = await ScreeningReviewService(db).upsert_review_item(
        customer_id,
        item_key=item_key,
        status=body.status,
        comment=body.comment,
        actor_id=str(current_user.id),
    )
    return ScreeningReviewItemResponse.model_validate(item)


@router.get(
    "/{customer_id}/bank-activity",
    response_model=BankActivityResponse,
    summary="List bank-linked suspicious-activity findings",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
    description=(
        "E9 establishes the stable CRM contract for Surepass/Finpass-style "
        "bank monitoring. Until a provider feed is connected, this returns an "
        "empty, valid response instead of fabricated findings."
    ),
)
async def get_bank_activity(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> BankActivityResponse:
    findings = await ScreeningReviewService(db).list_bank_findings(customer_id)
    open_findings = sum(1 for finding in findings if finding.status == "OPEN")
    last_synced_at = max((finding.detected_at for finding in findings), default=None)
    return BankActivityResponse(
        customer_id=customer_id,
        connected_accounts=0,
        last_synced_at=last_synced_at,
        open_findings=open_findings,
        findings=[BankActivityFindingResponse.model_validate(finding) for finding in findings],
    )


__all__ = ["router"]
