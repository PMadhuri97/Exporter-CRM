"""Contacts and activity-log routes — **owner: Developer 3** (architecture
§8.1, §9.3).

Split out of `exporter_router.py` (L2-01) so the company routes and the
engagement routes stop sharing one file. That split moved every contact and
activity route unchanged — same path, method, function name, roles, response model
and description — so the OpenAPI document did not move for it. The conversation
routes below are new in L3-03 and do move the document, which is why
`frontend/openapi.json` and `src/lib/api/schema.ts` are regenerated with them
(plan §7.7: regenerate, never merge).

Mounted by `router.py` beside `exporter_router`, with the same `/exporters`
prefix and `Exporter CRM` tag, so every path stays `/onboarding/exporters/...`.

The conversation-gauge routes (L3-03, L3-04a) are added at the end. Phase 2 adds
**no** route here: its completion routes live in its own `follow_up_router.py`,
which the seam commit already mounted (phase agreement §6.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.engagement import (
    AddExporterContactRequest,
    ConversationMoveListResponse,
    ConversationMoveResponse,
    ConversationResponse,
    ExporterActivityListResponse,
    ExporterActivityResponse,
    ExporterContactListResponse,
    ExporterContactResponse,
    LogExporterActivityRequest,
    PendingActivityListResponse,
    PendingActivityResponse,
    SetConversationRequest,
)
from app.modules.onboarding.application import (
    ConversationService,
    ExporterContactActivityService,
)
from app.modules.onboarding.domain.engagement_views import ConversationMove
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
# matrix in docs/architecture.md, "Roles and masking" (architecture §3.7).
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
#: Who may set the conversation — the roles `_STAFF` admits
#: (`docs/contracts/engagement.md` §3). Declared as a set as well as a dependency
#: because the reads below have to answer "what may *this caller* do", and a
#: `require_role` dependency cannot be asked that. Same pattern, and the same
#: reason, as `_MARKER_ROLES` in `exporter_router.py`.
_CONVERSATION_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})


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
    names = await actor_names(db, current_user, [activity.actor_id])
    return ExporterActivityResponse.model_validate(activity).named(names)


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
    names = await actor_names(db, current_user, (a.actor_id for a in activities))
    return ExporterActivityListResponse(
        customer_id=customer_id,
        activities=[ExporterActivityResponse.model_validate(a).named(names) for a in activities],
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


# ── Conversation gauge (L3-03, L3-04a) ──────────────────────────────────
#
# Under `/{customer_id}/conversation`, beside the company's other gauges: the
# conversation is a field on the company record, and every route here is about one
# company.
#
# Two reads, deliberately. `GET .../conversation` is what the Conversation panel
# asks for — value, check-back date and the moves in one request, so the screen
# makes one call. `GET .../conversation/moves` is the allowed-moves route
# architecture §7.5 asks for on its own, for a caller that wants nothing but the
# moves. Both answer from the same service method, so they cannot disagree.


def _conversation_moves(
    moves: tuple[ConversationMove, ...] | list[ConversationMove], viewer: User
) -> list[ConversationMoveResponse]:
    """The moves this viewer may make: the service's rules, and none at all for a
    role the write route refuses.

    Returning an empty list rather than the rules' answer is what keeps a screen
    from offering a button that would come back 403. The service already returns an
    empty list on a LEAD, so both reasons for "no moves" arrive the same way —
    which is the point: the screen does not re-derive which.
    """
    if viewer.role not in _CONVERSATION_ROLES:
        return []
    return [ConversationMoveResponse.model_validate(move) for move in moves]


@router.get(
    "/{customer_id}/conversation",
    response_model=ConversationResponse,
    summary="A company's conversation gauge",
    description=(
        "How the sales conversation is going (NOT_CONTACTED … READY_NOW), the "
        "check-back date if it is NOT_NOW, and the moves the signed-in user may "
        "make. The moves are served rather than derived: there is no transition "
        "table, because any value may follow any other, but which moves need a "
        "reason or a check-back date is a rule, and the server owns it. Empty for a "
        "role that may not set the conversation, and empty on a LEAD — the gauge "
        "applies from PROSPECT onward."
    ),
    responses={
        200: {"model": ConversationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
        404: {"description": "Exporter profile not found"},
    },
)
async def get_exporter_conversation(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    view = await ConversationService(db).get_conversation(customer_id)
    return ConversationResponse.from_view(
        view, allowed_moves=_conversation_moves(view.allowed_moves, current_user)
    )


@router.get(
    "/{customer_id}/conversation/moves",
    response_model=ConversationMoveListResponse,
    summary="The conversation moves the signed-in user may make",
    description=(
        "The allowed-moves route (architecture §7.5): the frontend fetches the "
        "moves for the current user instead of keeping a hand-copied table. The "
        "same answer as the `allowed_moves` field of GET /conversation, from the "
        "same service method, for a caller that wants only this."
    ),
    responses={
        200: {"model": ConversationMoveListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
        404: {"description": "Exporter profile not found"},
    },
)
async def list_exporter_conversation_moves(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ConversationMoveListResponse:
    view = await ConversationService(db).get_conversation(customer_id)
    return ConversationMoveListResponse(
        company_id=view.company_id,
        conversation=view.conversation,
        allowed_moves=_conversation_moves(view.allowed_moves, current_user),
    )


@router.post(
    "/{customer_id}/conversation",
    response_model=ConversationResponse,
    summary="Move a company's conversation gauge",
    description=(
        "Any value may follow any other — a conversation is a judgement, not a "
        "pipeline — except a move to the value already held, which records nothing "
        "(409). Moving to NOT_NOW needs a reason **and** a check-back date of today "
        "or later; moving away from NOT_NOW clears that date. A check-back date on "
        "any other move is refused rather than ignored. The gauge applies from "
        "PROSPECT onward, so a move on a LEAD is refused (409). Every change is "
        "recorded in the company's history with the signed-in user as the actor, in "
        "the same transaction as the change."
    ),
    responses={
        200: {"model": ConversationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Exporter profile not found"},
        409: {
            "description": (
                "The company is a LEAD (CONVERSATION_NOT_AVAILABLE), or the move is "
                "to the value already held (INVALID_CONVERSATION_TRANSITION)"
            )
        },
        422: {
            "description": (
                "Invalid request body; NOT_NOW without a reason; NOT_NOW without a "
                "check-back date (CONVERSATION_CHECK_BACK_REQUIRED); a check-back "
                "date in the past (CONVERSATION_CHECK_BACK_IN_PAST); or a check-back "
                "date on a move that is not to NOT_NOW "
                "(CONVERSATION_CHECK_BACK_NOT_ALLOWED)"
            )
        },
    },
)
async def set_exporter_conversation(
    customer_id: uuid.UUID,
    body: SetConversationRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    profile = await ConversationService(db).set_conversation(
        customer_id,
        body.conversation,
        reason=body.reason,
        check_back_on=body.check_back_on,
        # From the session, never from the body (architecture §7.5).
        actor_id=str(current_user.id),
    )
    moves = ConversationService.allowed_moves(profile.conversation, profile.journey)
    return ConversationResponse(
        company_id=customer_id,
        conversation=profile.conversation,
        check_back_on=profile.conversation_check_back_on,
        journey=profile.journey,
        allowed_moves=_conversation_moves(moves, current_user),
    )


__all__ = ["router"]
