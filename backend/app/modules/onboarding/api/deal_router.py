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
    DealRequiredDocumentResponse,
    DealRequiredDocumentsResponse,
    DealResponse,
    DealSide,
    OpenDealRequest,
    SetDealBuyerRequest,
    SetDealRequiredDocumentRequest,
    TransitionDealStageRequest,
)
from app.modules.onboarding.application.deal_required_documents_service import (
    DealRequiredDocumentsService,
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
#: The same three, as data: who `can_open_deal` may say yes to.
_OPENING_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})
# Reads additionally admit DEVELOPER, which may read the CRM and never writes.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
# Changing which paperwork a handover needs is a settings change, so ADMIN only —
# the same gate `/qualification/criteria` writes use (plan P2-5a).
_SETTINGS_ADMIN = require_role(UserRole.ADMIN)
#: The same, as data: who `can_edit` may say yes to.
_SETTINGS_WRITE_ROLES = frozenset({UserRole.ADMIN})


@router.post(
    "/exporters/{company_id}/deals",
    response_model=DealResponse,
    status_code=201,
    summary="Open a deal on a company",
    description=(
        "Opens a deal at `OPEN` and sets the company's conversation to "
        "`READY_NOW` in the same transaction (architecture §3.3). A company may "
        "have any number of deals.\n\n"
        "Only a `PROSPECT` or a `CUSTOMER` may have a deal opened: the conversation "
        "gauge applies from `PROSPECT` onward (assumption A4), so a `LEAD` is refused "
        "with 409 `DEAL_COMPANY_NOT_READY` and nothing is written.\n\n"
        "The stage is not a field on this request: a deal always starts at "
        "`OPEN`, and accepting one would let a caller skip every stage guard."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        409: {"description": "The company is still a LEAD (`DEAL_COMPANY_NOT_READY`)"},
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
    summary="List a company's deals, as seller or as buyer",
    description=(
        "Newest first. `stage` may be repeated to filter to several stages; "
        "omitted, every stage is returned, including withdrawn and handed-over "
        "deals — a company's deal history is part of its record.\n\n"
        "`as` chooses which side: `seller` (the default) lists the deals this "
        "company sells on, `buyer` the deals it buys on (task 2.7). The two are "
        "separate lists on purpose — the same company can be the seller on one deal "
        "and the buyer on another, and one list mixing them would show rows whose "
        "meaning changed line by line. On the buyer side, `buyer_name` carries **the "
        "seller's** name, because the company whose page this is would otherwise be "
        "repeated in every row.\n\n"
        "The buyer side matches `buyer_company_id` only. A deal whose buyer is still "
        "a legacy `deal_buyer` row does not appear, because nothing yet says that "
        "buyer is this company; the buyer migration (P4-6) is what makes it appear."
        "\n\n"
        "`can_open_deal` says whether this caller may open another deal on the "
        "company now — always about selling, whichever side is listed."
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
    as_: Annotated[DealSide, Query(alias="as")] = DealSide.SELLER,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DealListResponse:
    service = DealService(db)
    views, total = await service.list_for_company(
        company_id,
        stages=tuple(stage) if stage else None,
        as_buyer=as_ is DealSide.BUYER,
        limit=limit,
        offset=offset,
    )
    return DealListResponse(
        deals=[DealListItemResponse.from_view(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
        # The role half is this route's (the same three `_STAFF` admits on open);
        # the company half is the service's rule.
        can_open_deal=current_user.role in _OPENING_ROLES
        and await service.can_open_deal(company_id),
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
        "`HANDED_OVER` additionally requires a buyer, and every condition of the "
        "handover guard (deal contract §6.1). Live today: the company must be a "
        "`CUSTOMER` with a `CLEAR` background check (assumption A5), and the deal "
        "must have an `AVAILABLE` document in every category "
        "`/settings/deal-required-documents` requires.\n\n"
        "A refusal is 409 `DEAL_HANDOVER_BLOCKED` and names **every** unmet "
        "condition, not the first — so an operator does not have to fix one to "
        "discover the next."
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
    summary="Record the deal's buyer, as a company or as details",
    description=(
        "Two forms, exactly one per request.\n\n"
        "**`{buyer_company_id}`** names the company the buyer **is** (plan P4-4). "
        "Use this one. The buyer is then a full company record: it can be screened "
        "on its own timeline, the handover guard reads its sanctions and AML "
        "(decision BQ-4), and the same company can be the seller on another deal. "
        "It is **set once** — a deal pointed at the wrong buyer is withdrawn and a "
        "new one opened, so that the correction leaves a trail. Setting the same "
        "company again changes nothing and is not an error. The company must exist "
        "and must not be the seller on this deal.\n\n"
        "**`{name, country, ...}`** records a legacy `deal_buyer` row — one buyer "
        "per deal, so it replaces that row rather than adding another (deal "
        "contract §3); `PUT` rather than `POST` for the same reason. Still accepted "
        "because deals written before the buyer migration have one, and because a "
        "`deal_buyer`'s own sanctions and AML are the only thing BQ-4's rule can "
        "read for such a deal. These writes retire in P4-10.\n\n"
        "A buyer's problems stay on the buyer: a failed buyer check is recorded "
        "against the buyer and never against the selling company "
        "(architecture §3.5).\n\n"
        "In the legacy form the registration number, tax ID, contact email and "
        "contact phone are masked for OPERATIONS and DEVELOPER. Leave any of them "
        "out to keep its stored value — so a role that only sees the masked form "
        "can edit the rest — or send null to clear it. A masked value is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Deal not found, or no such buyer company"},
        409: {
            "description": (
                "The deal is handed over or withdrawn, or it already names a "
                "different buyer company"
            )
        },
        422: {
            "description": (
                "Both forms at once, neither form complete, a country that is not "
                "ISO-3166-1 alpha-2, a buyer company that is the seller, or a "
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
    service = DealService(db)
    if body.is_company_form:
        # `SetDealBuyerRequest` has already refused a body carrying both forms, so
        # this branch cannot also write a `deal_buyer` row.
        view = await service.set_buyer_company(
            deal_id,
            buyer_company_id=body.buyer_company_id,
            actor_id=str(current_user.id),
        )
    else:
        view = await service.set_buyer(
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


# ── Settings: which paperwork a handover needs (plan P2-5a) ──────────────────
#
# Under `/settings/...` rather than `/deals/...` because it is a rule about every
# deal, not a property of one — the same shape `/qualification/criteria` already
# has. Read by any staff role, because the deal page explains a refusal in these
# terms; written by ADMIN only.


@router.get(
    "/settings/deal-required-documents",
    response_model=DealRequiredDocumentsResponse,
    summary="Which document categories a deal must have before handover",
    description=(
        "`requirements` is the current version of every requirement, whether or "
        "not it is still `active` — a removed requirement is shown as inactive "
        "rather than hidden, because the table is append-only and the record of "
        "what was required when is part of the rule.\n\n"
        "`history` is every version ever written. `can_edit` says whether **this** "
        "caller may change the rule, so the screen offers the controls from the "
        "server rather than from the role (§7.5)."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
    },
)
async def list_deal_required_documents(
    # `_READER`, not `_STAFF`: the plan says "read Staff", but every other
    # settings read in the CRM admits DEVELOPER (`GET /qualification/criteria`),
    # which is read-only across the module, and this rule carries no identifiers
    # and nothing decision D8 protects. One convention beats two.
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> DealRequiredDocumentsResponse:
    service = DealRequiredDocumentsService(db)
    return DealRequiredDocumentsResponse(
        requirements=[
            DealRequiredDocumentResponse.from_entity(row) for row in await service.current()
        ],
        history=[
            DealRequiredDocumentResponse.from_entity(row) for row in await service.history()
        ],
        can_edit=current_user.role in _SETTINGS_WRITE_ROLES,
    )


@router.post(
    "/settings/deal-required-documents",
    response_model=DealRequiredDocumentResponse,
    status_code=201,
    summary="Require a document category before handover, or stop requiring it",
    description=(
        "Writes a **new version** of the requirement. There is no delete: send "
        "`active: false` to stop requiring a category, which records that it was "
        "removed, by whom and when.\n\n"
        "`document_type` is optional — left out, any document in the category "
        "satisfies the requirement, which is how the seeded `PRE_SHIPMENT` rule "
        "works. Named, it must be a type the document settings configure under "
        "that category (the same list the upload route accepts), or no deal could "
        "ever meet it.\n\n"
        "**This changes which deals can be handed over.** A deal with no "
        "`AVAILABLE` document in a required category is refused with 409 "
        "`DEAL_HANDOVER_BLOCKED`, naming the category. Deals already handed over "
        "are unaffected: the guard runs on the move, never retrospectively."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "ADMIN role required"},
        409: {
            "description": (
                "`DEAL_REQUIRED_DOCUMENT_CHANGED`: another administrator changed the "
                "same requirement first; nothing was saved"
            )
        },
        422: {
            "description": (
                "A category a deal cannot hold (it belongs to a company), a "
                "`document_type` not configured under the category "
                "(`DOCUMENT_TYPE_NOT_ALLOWED`), or a change that would leave the rule "
                "as it already is"
            )
        },
    },
)
async def set_deal_required_document(
    body: SetDealRequiredDocumentRequest,
    current_user: Annotated[User, Depends(_SETTINGS_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> DealRequiredDocumentResponse:
    row = await DealRequiredDocumentsService(db).set_requirement(
        category=body.category,
        document_type=body.document_type,
        active=body.active,
        actor_id=str(current_user.id),
    )
    return DealRequiredDocumentResponse.from_entity(row)


__all__ = ["router"]
