"""Deal and buyer routes — **owner: Developer 3B** (L3-05, L3-06).

Empty until now; see `follow_up_router.py`'s docstring for why it was mounted in
the seam commit rather than when it was filled.

No prefix: a deal is its own thing, not a company sub-resource, so its paths are
absolute (`/deals/...`) the way `history_router.py`'s deal route already is. The
one company-scoped path is the list, which reads as what it is — the deals *of* a
company.

Roles come from architecture §3.7: OPERATIONS, COMPLIANCE and ADMIN open deals,
move stages and record buyers; DEVELOPER reads; API_USER reaches nothing. The
stage rules themselves are `DealService`'s, and every gated route below has a row
in `GATED_ROUTES` and a refusal test.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.deal import (
    DealListItemResponse,
    DealListResponse,
    DealResponse,
    OpenDealRequest,
    SetDealBuyerRequest,
    TransitionDealStageRequest,
)
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

# Opening a deal, moving a stage and recording a buyer are routine CRM writes by
# internal staff (architecture §3.7), the same set `_STAFF` admits in
# `engagement_router.py`.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
# Reads additionally admit DEVELOPER, which may read the CRM and never writes.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)


@router.post(
    "/exporters/{company_id}/deals",
    response_model=DealResponse,
    status_code=201,
    summary="Open a deal on a company",
    description=(
        "Opens a deal at `OPEN` and sets the company's conversation to "
        "`READY_NOW` in the same transaction (architecture §3.3). A company may "
        "have any number of deals.\n\n"
        "The stage is not a field on this request: a deal always starts at "
        "`OPEN`, and accepting one would let a caller skip every stage guard."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        422: {"description": "Missing or empty reference"},
    },
)
async def open_deal(
    company_id: uuid.UUID,
    body: OpenDealRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> DealResponse:
    view = await DealService(db).open_deal(
        company_id, reference=body.reference, actor_id=str(current_user.id)
    )
    return DealResponse.from_view(view, current_user)


@router.get(
    "/exporters/{company_id}/deals",
    response_model=DealListResponse,
    summary="List a company's deals",
    description=(
        "Newest first. `stage` may be repeated to filter to several stages; "
        "omitted, every stage is returned, including withdrawn and handed-over "
        "deals — a company's deal history is part of its record."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
    },
)
async def list_company_deals(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    stage: Annotated[list[DealStage] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DealListResponse:
    views, total = await DealService(db).list_for_company(
        company_id,
        stages=tuple(stage) if stage else None,
        limit=limit,
        offset=offset,
    )
    return DealListResponse(
        deals=[DealListItemResponse.from_view(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/deals/{deal_id}",
    response_model=DealResponse,
    summary="Get one deal, its buyer, and the moves allowed from here",
    description=(
        "`allowed_stage_moves` is what **this** deal may do next, as data, so the "
        "screen does not keep its own copy of the stage graph (§7.5). A handover "
        "that is legal by the graph but blocked by assumption A5's guard is "
        "absent from that list, and `handover_blocked_reason` says why."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
        404: {"description": "Deal not found"},
    },
)
async def get_deal(
    deal_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> DealResponse:
    return DealResponse.from_view(await DealService(db).get_deal(deal_id), current_user)


@router.post(
    "/deals/{deal_id}/transitions",
    response_model=DealResponse,
    summary="Move a deal to another stage",
    description=(
        "The only way a deal's stage changes. The move must be one the stage graph "
        "allows (deal contract §1.1); `WITHDRAWN` requires a reason (assumption "
        "A7) and every other stage refuses one.\n\n"
        "`HANDED_OVER` additionally requires a buyer and assumption A5's guard — "
        "the company a `CUSTOMER` with a `CLEAR` background check. That check is "
        "Developer 4's column in migration 0015, which has not landed, so every "
        "handover is currently refused with `DEAL_HANDOVER_BLOCKED` rather than "
        "being allowed on the strength of a column that does not exist."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Deal not found"},
        409: {
            "description": (
                "The deal is already terminal, or the handover guard is unmet"
            )
        },
        422: {
            "description": (
                "The move is not allowed from this stage, a withdrawal reason is "
                "missing, a reason was sent for a non-withdrawal, or the deal has "
                "no buyer"
            )
        },
    },
)
async def transition_deal_stage(
    deal_id: uuid.UUID,
    body: TransitionDealStageRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> DealResponse:
    view = await DealService(db).transition_stage(
        deal_id,
        body.to_stage,
        reason=body.reason,
        actor_id=str(current_user.id),
    )
    return DealResponse.from_view(view, current_user)


@router.put(
    "/deals/{deal_id}/buyer",
    response_model=DealResponse,
    summary="Record or replace the deal's buyer",
    description=(
        "One buyer per deal, so this replaces that one row rather than adding "
        "another (deal contract §3). `PUT` rather than `POST` for the same "
        "reason.\n\n"
        "A buyer's problems stay on the buyer: a failed buyer check is recorded "
        "against this row and never against the company (architecture §3.5).\n\n"
        "The registration number, tax ID, contact email and contact phone are "
        "masked for OPERATIONS and DEVELOPER. Leave any of them out to keep its "
        "stored value — so a role that only sees the masked form can edit the "
        "rest — or send null to clear it. A masked value is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Deal not found"},
        409: {"description": "The deal is handed over or withdrawn"},
        422: {
            "description": (
                "Missing name, a country that is not ISO-3166-1 alpha-2, or a "
                "masked value sent back"
            )
        },
    },
)
async def set_deal_buyer(
    deal_id: uuid.UUID,
    body: SetDealBuyerRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> DealResponse:
    view = await DealService(db).set_buyer(
        deal_id,
        name=body.name,
        country=body.country,
        registration_number=body.registration_number,
        tax_id=body.tax_id,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
        keep=body.fields_to_keep(),
        actor_id=str(current_user.id),
    )
    return DealResponse.from_view(view, current_user)


__all__ = ["router"]
