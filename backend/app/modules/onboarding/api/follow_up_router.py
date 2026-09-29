"""Follow-up and completion routes — **owner: Developer 3A, Phase 2** (L3-04b).

Mounted by `router.py` in the seam commit, empty, so that neither Phase 2 nor
Developer 3B has to touch the router index again. These routes appear simply by being
added here; `api/router.py` is not opened.

**The paths are absolute, not under `/exporters/{customer_id}`.** The seam commit's
stub carried `prefix="/exporters"` as a placeholder. It is dropped here, for two
reasons:

1. A follow-ups list spans every company, so it is not a company sub-resource — the
   same reasoning that gives `history_router.py`'s deal route and
   `qualification_router.py`'s criteria routes absolute paths.
2. With that prefix, `GET /exporters/follow-ups` would be matched by
   `GET /exporters/{customer_id}` first — `exporter_router` is included before this
   one — and FastAPI would try to parse the literal `follow-ups` as a UUID and return
   422. Phase 1's cross-company route avoided that by using two segments
   (`/exporters/activities/pending`); this avoids it by not being under `/exporters`
   at all, which is also the truer description of what these routes are.

So the paths are `/onboarding/follow-ups` and
`/onboarding/follow-ups/{activity_id}/completion`.

**Follow-ups are the whole team's** (decision D2), so the list is a reader route with
no default owner filter. `actor_id` is a query parameter that narrows the list; it is
never a permission.

There is deliberately **no route that edits or deletes a completion**, and there must
never be one. Both tables are append-only, and a correction is a new activity plus
its own completion.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.follow_up import (
    CompleteFollowUpRequest,
    FollowUpCompletionResponse,
    FollowUpListResponse,
)
from app.modules.onboarding.application import FollowUpService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.follow_up_views import FollowUpState
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

# Completing a follow-up is a routine CRM write: OPERATIONS, COMPLIANCE, ADMIN
# (`docs/contracts/engagement.md` §5.5) — the same three that may set the conversation
# gauge, and for the same reason.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
# Reads admit DEVELOPER, like every other CRM read. A follow-up carries a subject, a
# note and an actor id but no tax identifier, so there is nothing here for the masking
# rules to apply to and this route returns the same bytes to every role that may call
# it — the same situation `history_router.py` documents.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)


@router.get(
    "/follow-ups",
    response_model=FollowUpListResponse,
    summary="What we owe exporters next, across every company",
    description=(
        "Two lists. **Follow-ups** are activities with a due date: outstanding while "
        "no completion row points at them, overdue while outstanding and past due, and "
        "done once one does — derived from the completion, never from a status column "
        "on the activity, which is append-only. **Check-backs** are companies parked "
        "at NOT_NOW, due to be picked up on their check-back date; they are not "
        "completable and are dealt with by moving the conversation gauge. "
        "Soonest-due first, so overdue items sort to the front. Visible to the whole "
        "team (decision D2): pass `actor_id` to narrow the list to one person, which "
        "filters and never gates."
    ),
    responses={
        200: {"model": FollowUpListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_follow_ups(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    state: FollowUpState | None = Query(
        default=None,
        description=(
            "OUTSTANDING (no completion), OVERDUE (outstanding and past due) or DONE "
            "(a completion exists). Omit for all three."
        ),
    ),
    customer_id: uuid.UUID | None = Query(default=None, description="One company only."),
    actor_id: str | None = Query(
        default=None, description="Whoever logged the follow-up. Narrows; never gates."
    ),
    activity_type: ExporterActivityType | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    include_check_backs: bool = Query(
        default=True,
        description=(
            "Include companies parked at NOT_NOW. They ignore state, actor_id and "
            "activity_type, none of which applies to a company with no activity, and "
            "they ignore offset — that pages the follow-ups. `check_backs` is the "
            "first `limit` of them with a true `check_backs_total` beside it."
        ),
    ),
    check_backs_due_only: bool = Query(
        default=False,
        description=(
            "Only the check-backs that are due — on or before today (UTC). For an "
            "overdue view, so a company parked until next quarter is not listed "
            "beside work that is late. `check_backs_total` counts the same set."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FollowUpListResponse:
    view = await FollowUpService(db).list_follow_ups(
        state=state,
        customer_id=customer_id,
        actor_id=actor_id,
        activity_type=activity_type,
        due_before=due_before,
        due_after=due_after,
        include_check_backs=include_check_backs,
        check_backs_due_only=check_backs_due_only,
        limit=limit,
        offset=offset,
    )
    names = await actor_names(db, current_user, (row.actor_id for row in view.follow_ups))
    return FollowUpListResponse.from_view(
        view, limit=limit, offset=offset, actor_names=names
    )


@router.post(
    "/follow-ups/{activity_id}/completion",
    response_model=FollowUpCompletionResponse,
    status_code=201,
    summary="Record that a follow-up was dealt with",
    description=(
        "Inserts a locked record; it never updates the activity, which is append-only "
        "and has no place to mark. One completion per follow-up: a second is refused, "
        "never an upsert, because a correction is a new activity plus its own "
        "completion. RESCHEDULED needs a future `next_due_at` and also logs a new "
        "follow-up for that moment, in the same transaction — the original keeps the "
        "date it was promised for. Any other outcome carrying a `next_due_at` is "
        "refused rather than ignored. Who completed it comes from the signed-in user."
    ),
    responses={
        201: {"model": FollowUpCompletionResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "No such activity (FOLLOW_UP_NOT_FOUND)"},
        409: {
            "description": (
                "The activity has no due date, so it is not a follow-up "
                "(ACTIVITY_IS_NOT_A_FOLLOW_UP); or it was already completed "
                "(FOLLOW_UP_ALREADY_COMPLETED)"
            )
        },
        422: {
            "description": (
                "Invalid request body; RESCHEDULED with no next due date "
                "(FOLLOW_UP_RESCHEDULE_NEEDS_DATE); a next due date in the past "
                "(FOLLOW_UP_RESCHEDULE_IN_PAST); or a next due date on an outcome that "
                "is not RESCHEDULED (FOLLOW_UP_NEXT_DUE_NOT_ALLOWED)"
            )
        },
    },
)
async def complete_follow_up(
    activity_id: uuid.UUID,
    body: CompleteFollowUpRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> FollowUpCompletionResponse:
    completion = await FollowUpService(db).complete_follow_up(
        activity_id,
        body.outcome,
        note=body.note,
        next_due_at=body.next_due_at,
        # From the session, never from the body (architecture §7.5).
        actor_id=str(current_user.id),
    )
    return FollowUpCompletionResponse.model_validate(completion)


__all__ = ["router"]
