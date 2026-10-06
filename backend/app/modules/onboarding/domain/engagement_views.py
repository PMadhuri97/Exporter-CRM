"""Read-model view types for contacts and the activity log (architecture §8.1, §9.3).

Pure data structures — no I/O, no session — the same pattern as
``exporter_profile_views.py``, from which these were split unchanged.
``ExporterContactActivityService`` assembles the pending view; the company
detail view (``ExporterProfileDetail``) embeds the contact and
activity views because the company page shows them.
``ConversationService`` assembles ``ConversationView``.

Follow-ups add **no** view here: their due/overdue read models live in
``domain/follow_up_views.py``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.onboarding.domain.entities.engagement_enums import (
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney


@dataclass(frozen=True)
class ExporterContactView:
    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    role: str | None
    email: str | None
    phone: str | None
    department: str | None
    is_primary_contact: bool


@dataclass(frozen=True)
class ExporterActivityView:
    id: uuid.UUID
    customer_id: uuid.UUID
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    occurred_at: datetime
    due_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class PendingActivityView:
    """One row of `ExporterContactActivityService.list_pending_activities`'s
    cross-exporter pending/follow-up list.

    Carries the exporter's display name alongside the activity itself so a
    Follow-ups screen never needs a second, per-row query to answer "pending,
    for which exporter" — `exporter_display_name` is the company's own name,
    resolved via one join in `ExporterActivityRepository.list_pending`, not a
    Python-side loop calling back into the database. `None` for a company
    created without a name.

    `is_overdue` is computed once, at view-construction time, against the
    same `now` the query itself was run with — never recomputed from a stale
    `datetime.now()` deeper in a template or a second pass over the list.
    """

    id: uuid.UUID
    customer_id: uuid.UUID
    exporter_display_name: str | None
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    occurred_at: datetime
    due_at: datetime
    is_overdue: bool
    created_at: datetime


@dataclass(frozen=True)
class ConversationMove:
    """One conversation move the rules allow, as the server serves it.

    Architecture §7.5: "The frontend fetches the allowed journey, gauge and deal
    moves for the current user instead of keeping hand-copied tables." This is
    that answer for the conversation gauge, so no screen holds a copy of the
    values or of the `NOT_NOW` rule.

    `reason_required` and `check_back_required` come from the same table
    `ConversationService.set_conversation` enforces, so a screen asking what it
    may do and the server judging what it did can never disagree.
    """

    to: ExporterConversation
    reason_required: bool
    check_back_required: bool


@dataclass(frozen=True)
class ConversationView:
    """The conversation gauge as the Conversation panel reads it.

    Carries `journey` because the panel has to explain an empty `allowed_moves`
    to a person: on a `LEAD` the gauge does not apply yet, which
    is a different sentence from "your role may not move it". The list itself is
    empty in both cases on purpose — the *screen* never re-derives which — so the
    journey is here as the thing worth saying, not as an input to a rule.
    """

    company_id: uuid.UUID
    conversation: ExporterConversation
    check_back_on: date | None
    journey: ExporterJourney
    allowed_moves: tuple[ConversationMove, ...]


__all__ = [
    "ConversationMove",
    "ConversationView",
    "ExporterActivityView",
    "ExporterContactView",
    "PendingActivityView",
]
