"""Read routes for the shared CRM history log.

Its own file rather than rows in `exporter_router.py`: section 8.1 of the
architecture gives the company routes their own file and says other areas add their
own route files beside them. The history log is shared, and the deal
route is not a company route at all.

Read-only on purpose. History is written by the service that made the change,
inside that change's transaction; the table refuses UPDATE and DELETE at the
database. There is no POST, PATCH or DELETE here and there should never be one.

`GET /exporters/{customer_id}/history` unfiltered is the company timeline — the
journey, every gauge and every deal interleaved, which is the view section 3.1
of the architecture describes as "the full story of a company". `?dimension=`
narrows it to one gauge, which is what a gauge panel asks for.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.history import (
    HistoryEntryResponse,
    HistoryListResponse,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.history_dimensions import HIDDEN_FROM_DEVELOPER
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_permission
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_COMPANY_VIEW = require_permission("exporters", "view")
_DEAL_VIEW = require_permission("deals", "view")

# "See companies, contacts, deals, history" (`exporters:view`, `deals:view`):
# OPERATIONS, COMPLIANCE, ADMIN and DEVELOPER, API_USER no. Same gate as the other
# CRM reads.
#
# A history row carries an actor id and a free-text reason but no tax
# identifier, so there is nothing here for the masking rules to apply to. The
# actor's name is added for every reader (`api/actor_names.py`).

#: Dimensions DEVELOPER does not see here. The rule (settled 28 September 2026)
#: refuses DEVELOPER the background-check gauge, its decision reasons and evidence
#: ids, and the verification and screening routes (`background-check.md` §14,
#: `verification-and-screening.md` §11). Their history rows carry the same values, reasons, review notes
#: and screening comments, so serving them here would hand DEVELOPER exactly what
#: those routes refuse it. Every other dimension stays readable. The
#: background check's own newer dimensions, `check_cycle` and
#: `background_check_approval`, for the same reason (`domain/history_dimensions.py`).
_HIDDEN_FROM_DEVELOPER = HIDDEN_FROM_DEVELOPER

#: `details` keys DEVELOPER does not see on the rows it does receive. The move to
#: `CUSTOMER` is a journey row, and it records the clearing decision and its risk
#: rating — background-check data DEVELOPER is refused on the check's own route. The
#: row itself stays: the journey is readable, and `CUSTOMER` already says the check
#: cleared.
#: A GST registration's add and deactivate rows also carry the branch's
#: `flag_status`, which DEVELOPER is not served.
_DETAILS_HIDDEN_FROM_DEVELOPER = frozenset(
    {"risk_rating", "clearing_decision_id", "flag_status"}
)

#: Rows DEVELOPER does not see inside a dimension it otherwise reads: flagging and
#: unflagging a branch. Their from/to *is* the flag status and their reason the
#: flag's reason — the compliance judgement the rule of 4 October 2026
#: withholds from DEVELOPER on the registrations route as well.
_EVENTS_HIDDEN_FROM_DEVELOPER = frozenset(
    {"gst_registration_flagged", "gst_registration_unflagged"}
)


def _hidden_for(user: User) -> frozenset[str]:
    return _HIDDEN_FROM_DEVELOPER if user.role == UserRole.DEVELOPER else frozenset()


def _hidden_events_for(user: User) -> frozenset[str]:
    return _EVENTS_HIDDEN_FROM_DEVELOPER if user.role == UserRole.DEVELOPER else frozenset()


def _hidden_details_for(user: User) -> frozenset[str]:
    return _DETAILS_HIDDEN_FROM_DEVELOPER if user.role == UserRole.DEVELOPER else frozenset()


async def _page(
    db: AsyncSession, user: User, rows, total: int, limit: int, offset: int
) -> HistoryListResponse:
    names = await actor_names(db, user, (row.actor_id for row in rows))
    hidden = _hidden_details_for(user)
    return HistoryListResponse(
        entries=[
            HistoryEntryResponse.from_row(row, hidden_detail_keys=hidden, actor_names=names)
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )

_ORDERING = (
    "Newest first. `created_at` defaults to the transaction clock, so rows written "
    "in one transaction share a timestamp; `id` breaks the tie so paging is stable, "
    "though between two such rows the order is deterministic rather than chronological."
)


@router.get(
    "/exporters/{customer_id}/history",
    response_model=HistoryListResponse,
    summary="A company's history",
    description=(
        "Every recorded change to this company: its journey, each of its three "
        "gauges, its marker and its deals, interleaved. Filter to one with "
        "`dimension`. DEVELOPER does not receive `background_check`, "
        "`verification`, `screening`, `check_cycle` or `background_check_approval` "
        "rows, nor a row's `risk_rating` or `clearing_decision_id` details, "
        "nor a branch's flag and unflag rows or its `flag_status` "
        "detail. " + _ORDERING
    ),
    responses={
        200: {"model": HistoryListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:view` permission required"},
    },
)
async def list_company_history(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPANY_VIEW)],
    db: AsyncSession = Depends(get_db),
    dimension: str | None = Query(
        default=None,
        max_length=32,
        description=(
            "Restrict to one dimension: journey, qualification, conversation, "
            "background_check, deal, marker, profile, verification, screening, "
            "check_cycle, background_check_approval, gst_registration, trade or "
            "pipeline."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """An unknown company and an unknown dimension both return an empty page.

    Not a 404: a company with no recorded history and a company id that was
    never real are the same answer from this table, and distinguishing them
    would mean this route reaching into the company record to check — which
    would also turn it into a way to probe which company ids exist.
    """
    entries, total = await HistoryService(db).list_for_company(
        customer_id,
        dimension=dimension,
        exclude_dimensions=_hidden_for(current_user),
        exclude_event_types=_hidden_events_for(current_user),
        limit=limit,
        offset=offset,
    )
    return await _page(db, current_user, entries, total, limit, offset)


@router.get(
    "/deals/{deal_id}/history",
    response_model=HistoryListResponse,
    summary="A deal's history",
    description=(
        "Every recorded change to one deal, including the changes it caused "
        "elsewhere (the conversation it moved, checks on its buyer). DEVELOPER does "
        "not receive `background_check`, `verification` or `screening` rows, nor a "
        "row's `risk_rating` or `clearing_decision_id` details, nor a "
        "branch's flag and unflag rows or its `flag_status` detail. " + _ORDERING
    ),
    responses={
        200: {"model": HistoryListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "`deals:view` permission required"},
    },
)
async def list_deal_history(
    deal_id: uuid.UUID,
    current_user: Annotated[User, Depends(_DEAL_VIEW)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """An unknown deal is an empty page, like a deal with no history yet.

    There is no `dimension` filter: everything about a deal is the deal.
    """
    entries, total = await HistoryService(db).list_for_deal(
        deal_id,
        exclude_dimensions=_hidden_for(current_user),
        exclude_event_types=_hidden_events_for(current_user),
        limit=limit,
        offset=offset,
    )
    return await _page(db, current_user, entries, total, limit, offset)
