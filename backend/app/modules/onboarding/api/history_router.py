"""Read routes for the shared CRM history log.

Its own file rather than rows in `exporter_router.py`: section 8.1 of the
architecture makes the company routes Developer 2's and says others add their
own route files beside them. The history log is Developer 1's, and the deal
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

from app.modules.onboarding.api.schemas.history import (
    HistoryEntryResponse,
    HistoryListResponse,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

# "See companies, contacts, deals, history" in the role matrix (architecture
# §3.7): OPERATIONS, COMPLIANCE and ADMIN yes, DEVELOPER read-only, API_USER
# no. Same gate as the other CRM reads.
#
# A history row carries an actor id and a free-text reason but no tax
# identifier, so there is nothing here for the masking rules to apply to — this
# route returns the same bytes to every role that may call it.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
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
        "`dimension`. " + _ORDERING
    ),
    responses={
        200: {"model": HistoryListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_company_history(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    dimension: str | None = Query(
        default=None,
        max_length=32,
        description=(
            "Restrict to one dimension: journey, qualification, conversation, "
            "background_check, deal, marker, profile or verification."
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
        customer_id, dimension=dimension, limit=limit, offset=offset
    )
    return HistoryListResponse(
        entries=[HistoryEntryResponse.from_row(row) for row in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/deals/{deal_id}/history",
    response_model=HistoryListResponse,
    summary="A deal's history",
    description=(
        "Every recorded change to one deal. Empty until deals exist "
        "(migration 0018). " + _ORDERING
    ),
    responses={
        200: {"model": HistoryListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_deal_history(
    deal_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """Returns an empty page today, and that is the right answer.

    Deals arrive in migration 0018 (Developer 3). The route ships now so the
    shape is settled before anything depends on it, and so Developer 3 has a
    working read the moment the first deal row is written. There is no
    `dimension` filter: everything about a deal is the deal.
    """
    entries, total = await HistoryService(db).list_for_deal(
        deal_id, limit=limit, offset=offset
    )
    return HistoryListResponse(
        entries=[HistoryEntryResponse.from_row(row) for row in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
