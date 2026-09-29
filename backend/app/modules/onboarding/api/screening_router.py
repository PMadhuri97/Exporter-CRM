"""Screening-review checklist and bank-activity routes — **owner:
Developer 4** (architecture §8.1, §9.4).

Split out of `exporter_router.py` (L2-01) so the company routes and the
background-check routes stop sharing one file. Mounted by `router.py` beside
`exporter_router`, with the same `/exporters` prefix and `Exporter CRM` tag, so
every path stays `/onboarding/exporters/...`.

Dev4B (4B-1): the list serves the one screening catalogue and the caller's
capabilities, so the frontend keeps neither a key list nor a role list; unknown
companies are 404; each item's history is readable. Roles are unchanged — read
OPERATIONS/COMPLIANCE/ADMIN, write COMPLIANCE/ADMIN; DEVELOPER stays refused
(**D8**, lead, 28 Sep 2026: no widening). Each decision is also recorded in the
company history under the `screening` dimension (**D9**).

The screening checklist is a compliance list inside the background check. It is
not qualification (architecture §5.5).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.screening import (
    BankActivityFindingResponse,
    BankActivityResponse,
    ScreeningCapabilities,
    ScreeningCatalogueItemResponse,
    ScreeningItemHistoryResponse,
    ScreeningReviewItemResponse,
    ScreeningReviewListResponse,
    UpdateScreeningReviewItemRequest,
)
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE_ITEMS,
    ScreeningReviewService,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

#: Who may record a screening decision. Compliance decisions are compliance-owned;
#: a plain API_USER must never be able to mark a sanctions check PASSED. The same
#: tuple gates the route and answers `can_record_decision`, so the two cannot drift.
_DECISION_ROLES = (UserRole.COMPLIANCE, UserRole.ADMIN)
_COMPLIANCE_OR_ADMIN = require_role(*_DECISION_ROLES)
# Routine CRM reads by internal staff.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)

_CATALOGUE = [ScreeningCatalogueItemResponse.model_validate(i) for i in SCREENING_CATALOGUE_ITEMS]


# ── E9 screening review workspace ─────────────────────────────────────────

@router.get(
    "/{customer_id}/screening-review",
    response_model=ScreeningReviewListResponse,
    summary="List persisted screening-review checklist decisions",
    description=(
        "The current decision on each checklist item that has one, the full checklist "
        "catalogue in display order, and whether the caller may record a decision."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
    },
)
async def list_screening_review(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewListResponse:
    items = await ScreeningReviewService(db).list_review_items(customer_id)
    names = await actor_names(db, current_user, (item.reviewed_by for item in items))
    return ScreeningReviewListResponse(
        customer_id=customer_id,
        items=[ScreeningReviewItemResponse.model_validate(item).named(names) for item in items],
        catalogue=_CATALOGUE,
        capabilities=ScreeningCapabilities(
            can_record_decision=current_user.role in _DECISION_ROLES
        ),
    )


@router.get(
    "/{customer_id}/screening-review/{item_key}/history",
    response_model=ScreeningItemHistoryResponse,
    summary="Every decision recorded on one screening-review checklist item",
    description=(
        "Newest first, paged. The checklist table is append-only, so this is the "
        "item's complete history; the first row of the first page is its current state."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        422: {"description": "Unknown checklist item"},
    },
)
async def list_screening_review_item_history(
    customer_id: uuid.UUID,
    item_key: str,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ScreeningItemHistoryResponse:
    rows, total = await ScreeningReviewService(db).list_item_history(
        customer_id, item_key, limit=limit, offset=offset
    )
    names = await actor_names(db, current_user, (row.reviewed_by for row in rows))
    return ScreeningItemHistoryResponse(
        customer_id=customer_id,
        item_key=item_key,
        items=[ScreeningReviewItemResponse.model_validate(row).named(names) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/{customer_id}/screening-review/{item_key}",
    response_model=ScreeningReviewItemResponse,
    summary="Record or update one screening-review checklist decision",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        422: {"description": "Unknown checklist item or status"},
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
    names = await actor_names(db, current_user, [item.reviewed_by])
    return ScreeningReviewItemResponse.model_validate(item).named(names)


@router.get(
    "/{customer_id}/bank-activity",
    response_model=BankActivityResponse,
    summary="List bank-linked suspicious-activity findings",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
    description=(
        "No bank-monitoring provider feed is connected: the response says so "
        "(`provider_feed_connected: false`, `provider_feed_status: NOT_CONNECTED`) "
        "and never carries fabricated findings."
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
        provider_feed_connected=False,
        connected_accounts=0,
        last_synced_at=last_synced_at,
        open_findings=open_findings,
        findings=[BankActivityFindingResponse.model_validate(finding) for finding in findings],
    )


__all__ = ["router"]
