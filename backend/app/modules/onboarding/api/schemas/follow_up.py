"""Request/response schemas for follow-ups and completions.

Created as a stub and filled here. The completion shape these
render is fixed by `docs/contracts/engagement.md` §5.

Two row types, not one. A **follow-up** is an activity with a due date, dealt with
by recording a completion. A **check-back** is a company parked at `NOT_NOW`, dealt
with by moving the conversation gauge. They are completed through different services
and only one of them has an activity, so merging them would make every row half
null — see `domain/follow_up_views.py` for the longer version.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.entities.engagement_enums import (
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.follow_up_completion import FollowUpOutcome
from app.modules.onboarding.domain.follow_up_views import (
    FollowUpListView,
    FollowUpState,
    FollowUpView,
)

_COMPLETED_BY_NAME = (
    "Who completed it, by name: the account's full name, or its email when it has "
    "none (DEVELOPER is given the full name only). Null when the platform acted or "
    "no account with a name matches `completed_by`."
)


class CompleteFollowUpRequest(BaseModel):
    """Record that a follow-up was dealt with.

    No `actor_id`: who completed it comes from the login session, never from this body
    (architecture §7.5). No `activity_id` either — it is the path parameter, so a body
    cannot disagree with the URL about which follow-up is being completed.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: FollowUpOutcome
    note: str | None = Field(
        default=None, description="What happened, in your words."
    )
    #: `AwareDatetime`, not `datetime`: a moment with no offset is ambiguous, and the
    #: service compares it with an aware "now" — a naive value would raise there and
    #: surface as a 500. Refused here instead, as the 422 every other bad body gets.
    next_due_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the follow-up was moved to, with a timezone offset (e.g. `Z` or "
            "`+05:30`). Required for RESCHEDULED and must be in the future; refused — "
            "not ignored — on any other outcome. Rescheduling also logs a new "
            "follow-up for this moment: the original activity is append-only and keeps "
            "the date it was promised for."
        ),
    )


class FollowUpCompletionResponse(BaseModel):
    """A completion, as recorded. Every field comes from the completion row and none
    from the activity — nothing may be written to an activity after it is logged."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_id: uuid.UUID
    customer_id: uuid.UUID
    outcome: FollowUpOutcome
    note: str | None
    next_due_at: datetime | None
    completed_by: str | None = Field(
        default=None,
        description=(
            "Who completed it, from their login session. Null means the platform "
            "itself acted."
        ),
    )
    completed_by_name: str | None = Field(default=None, description=_COMPLETED_BY_NAME)
    completed_at: datetime


class FollowUpCompletionSummary(BaseModel):
    """The completion as it appears inside a list row: the same facts without
    repeating `activity_id` and `customer_id`, which the row already carries."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    outcome: FollowUpOutcome
    note: str | None
    next_due_at: datetime | None
    completed_by: str | None
    completed_by_name: str | None = Field(default=None, description=_COMPLETED_BY_NAME)
    completed_at: datetime


class FollowUpResponse(BaseModel):
    """One follow-up: an activity with a due date, plus its completion if it has
    one."""

    model_config = ConfigDict(from_attributes=True)

    activity_id: uuid.UUID
    customer_id: uuid.UUID
    exporter_display_name: str | None = Field(
        default=None, description="The company's own name; null if it was created without one."
    )
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str = Field(description="Who logged the follow-up — not who completed it.")
    actor_name: str | None = Field(
        default=None,
        description=(
            "Who logged it, by name: the account's full name, or its email when it has "
            "none (DEVELOPER is given the full name only). Null when no account with a "
            "name matches `actor_id`."
        ),
    )
    occurred_at: datetime
    due_at: datetime
    is_overdue: bool = Field(
        description=(
            "Outstanding and past due. Always false once a completion exists: a "
            "follow-up dealt with late is done, not overdue."
        )
    )
    state: FollowUpState = Field(
        description=(
            "OUTSTANDING, OVERDUE or DONE. Derived from whether a completion exists — "
            "there is no status column on an activity, and there must not be one."
        )
    )
    completion: FollowUpCompletionSummary | None = Field(
        default=None, description="Null exactly when the follow-up is outstanding."
    )

    @classmethod
    def from_view(
        cls, view: FollowUpView, *, actor_names: Mapping[str, str] | None = None
    ) -> FollowUpResponse:
        """`state` is a property on the view, so it is passed explicitly rather than
        picked up by `from_attributes` — which reads fields, not properties.

        `actor_names` names both people on the row — who logged it and who completed
        it — from one lookup (`api/actor_names.py`)."""
        names = actor_names or {}
        completion = view.completion
        return cls(
            activity_id=view.activity_id,
            customer_id=view.customer_id,
            exporter_display_name=view.exporter_display_name,
            activity_type=view.activity_type,
            subject=view.subject,
            notes=view.notes,
            actor_id=view.actor_id,
            actor_name=names.get(view.actor_id),
            occurred_at=view.occurred_at,
            due_at=view.due_at,
            is_overdue=view.is_overdue,
            state=view.state,
            completion=(
                None
                if completion is None
                else FollowUpCompletionSummary(
                    id=completion.id,
                    outcome=completion.outcome,
                    note=completion.note,
                    next_due_at=completion.next_due_at,
                    completed_by=completion.completed_by,
                    completed_by_name=(
                        names.get(completion.completed_by)
                        if completion.completed_by is not None
                        else None
                    ),
                    completed_at=completion.completed_at,
                )
            ),
        )


class CheckBackResponse(BaseModel):
    """A company parked at `NOT_NOW`, due to be picked up on `check_back_on`.

    Not completable. It is dealt with by moving the conversation gauge —
    `POST /onboarding/exporters/{customer_id}/conversation` — which clears the date in
    the same transaction. There is deliberately no completion route for this.
    """

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    exporter_display_name: str | None
    conversation: ExporterConversation
    check_back_on: date
    is_overdue: bool = Field(
        description="The check-back date has passed. A check-back due today is due, not late."
    )


class FollowUpListResponse(BaseModel):
    """The Follow-ups screen's answer: both lists, each with its own total.

    Totals are the counts matching the same filters, not the lengths of the lists, so
    a caller can tell whether there is more without asking for it — the convention
    `HistoryListResponse` uses.
    """

    follow_ups: list[FollowUpResponse]
    follow_ups_total: int
    check_backs: list[CheckBackResponse]
    check_backs_total: int
    limit: int
    offset: int

    @classmethod
    def from_view(
        cls,
        view: FollowUpListView,
        *,
        limit: int,
        offset: int,
        actor_names: Mapping[str, str] | None = None,
    ) -> FollowUpListResponse:
        return cls(
            follow_ups=[
                FollowUpResponse.from_view(row, actor_names=actor_names)
                for row in view.follow_ups
            ],
            follow_ups_total=view.follow_ups_total,
            check_backs=[
                CheckBackResponse.model_validate(row) for row in view.check_backs
            ],
            check_backs_total=view.check_backs_total,
            limit=limit,
            offset=offset,
        )


__all__ = [
    "CheckBackResponse",
    "CompleteFollowUpRequest",
    "FollowUpCompletionResponse",
    "FollowUpCompletionSummary",
    "FollowUpListResponse",
    "FollowUpResponse",
]
