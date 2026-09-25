"""Contacts and activity-log routes — **owner: Developer 3** (architecture
§8.1, §9.3).

Split out of `exporter_router.py` (L2-01) so the company routes and the
engagement routes stop sharing one file. Every route below is unchanged: same
path, method, function name, roles, response model and description, so the
OpenAPI document and the frontend's generated types do not move.

Mounted by `router.py` beside `exporter_router`, with the same `/exporters`
prefix and `Exporter CRM` tag, so every path stays `/onboarding/exporters/...`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.engagement import (
    AddExporterContactRequest,
    ExporterActivityListResponse,
    ExporterActivityResponse,
    ExporterContactListResponse,
    ExporterContactResponse,
    LogExporterActivityRequest,
    PendingActivityListResponse,
    PendingActivityResponse,
)
from app.modules.onboarding.application import ExporterContactActivityService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

# Routine CRM reads and writes by internal staff (Relationship Managers are
# OPERATIONS, and may read every exporter). Contact email/phone are masked per
# viewer in the response schemas.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
# Masked CRM reads. DEVELOPER may read the CRM but never sees a raw
# identifier (`can_reveal_identifiers` is always False for it), per the role
# capability matrix in docs/exporter-crm-frontend-tickets.md.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)


# ── Contacts ──────────────────────────────────────────────────────────────


@router.post(
    "/{customer_id}/contacts",
    response_model=ExporterContactResponse,
    status_code=201,
    summary="Add a contact to an exporter relationship",
    description=(
        "Setting is_primary=true demotes any existing primary contact for this "
        "customer in the same transaction — never two primaries at once."
    ),
    responses={
        201: {"model": ExporterContactResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def add_exporter_contact(
    customer_id: uuid.UUID,
    body: AddExporterContactRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterContactResponse:
    contact = await ExporterContactActivityService(db).add_contact(
        customer_id,
        name=body.name,
        role=body.role,
        email=body.email,
        phone=body.phone,
        department=body.department,
        is_primary=body.is_primary,
    )
    return ExporterContactResponse.model_validate(contact).masked_for(current_user)


@router.get(
    "/{customer_id}/contacts",
    response_model=ExporterContactListResponse,
    summary="List an exporter's contacts",
    responses={
        200: {"model": ExporterContactListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_exporter_contacts(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ExporterContactListResponse:
    contacts = await ExporterContactActivityService(db).list_contacts(customer_id)
    return ExporterContactListResponse(
        customer_id=customer_id,
        contacts=[
            ExporterContactResponse.model_validate(c).masked_for(current_user)
            for c in contacts
        ],
    )


# ── Activities ────────────────────────────────────────────────────────────


@router.post(
    "/{customer_id}/activities",
    response_model=ExporterActivityResponse,
    status_code=201,
    summary="Log a relationship-history activity",
    description="Append-only: once logged, an activity can never be edited or deleted.",
    responses={
        201: {"model": ExporterActivityResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def log_exporter_activity(
    customer_id: uuid.UUID,
    body: LogExporterActivityRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterActivityResponse:
    activity = await ExporterContactActivityService(db).log_activity(
        customer_id,
        activity_type=body.activity_type,
        subject=body.subject,
        notes=body.notes,
        due_at=body.due_at,
        actor_id=str(current_user.id),
    )
    return ExporterActivityResponse.model_validate(activity)


@router.get(
    "/{customer_id}/activities",
    response_model=ExporterActivityListResponse,
    summary="List an exporter's relationship-history activities",
    description="Most recent first. Optionally filtered by activity_type.",
    responses={
        200: {"model": ExporterActivityListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_exporter_activities(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    activity_type: ExporterActivityType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExporterActivityListResponse:
    activities = await ExporterContactActivityService(db).list_activities(
        customer_id, activity_type=activity_type, limit=limit, offset=offset
    )
    return ExporterActivityListResponse(
        customer_id=customer_id,
        activities=[ExporterActivityResponse.model_validate(a) for a in activities],
    )


# ── Pending activities (Piece 2: cross-exporter follow-up list) ─────────────
#
# Deliberately `/activities/pending`, not nested under `/{customer_id}` — this
# route spans every exporter, unlike every other `/exporters` route. Two path
# segments after the `/exporters` prefix keeps it clear of every other
# route under that prefix (`/{customer_id}`, `/{customer_id}/contacts`,
# `/{customer_id}/activities`): none of them match a two-segment path whose
# first segment is the literal `activities`, so there is no ordering hazard
# regardless of where this route is declared relative to those.


@router.get(
    "/activities/pending",
    response_model=PendingActivityListResponse,
    summary="List pending/follow-up activities across every exporter",
    description=(
        "Everything pending, across every exporter — a Follow-ups/pending-work "
        "screen's own query. Omit actor_id for a manager's team-wide view; pass it "
        "to scope to one person's own pending items. 'Pending' means the activity "
        "carries a due_at (TASK/FOLLOW_UP entries, typically); each row already "
        "carries the exporter's display name and a computed is_overdue flag."
    ),
    responses={
        200: {"model": PendingActivityListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_pending_exporter_activities(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    actor_id: str | None = Query(default=None),
    activity_type: ExporterActivityType | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingActivityListResponse:
    views = await ExporterContactActivityService(db).list_pending_activities(
        actor_id=actor_id,
        activity_type=activity_type,
        due_before=due_before,
        due_after=due_after,
        limit=limit,
        offset=offset,
    )
    return PendingActivityListResponse(
        activities=[PendingActivityResponse.model_validate(v) for v in views],
        limit=limit,
        offset=offset,
    )


__all__ = ["router"]
