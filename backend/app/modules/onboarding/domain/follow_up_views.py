"""Read-model view types for follow-ups — **owner: Developer 3A, Phase 2**
(L3-04b).

Pure data structures — no I/O, no session — the same pattern as
``engagement_views.py`` and ``qualification_views.py``.

**These live here rather than in ``engagement_views.py``**, which is Phase 1's file:
the phase agreement (§6.3) gives no file to both phases, and a read model that spans
two tables is ordinary while reaching into another owner's module for one type is
what creates the conflict the split exists to avoid.

**Two lists, not one.** The Follow-ups screen answers "what do we owe an exporter
next", and there are two different answers in this CRM:

* a **follow-up** — an ``ExporterActivity`` with a ``due_at``, dealt with by
  recording a ``FollowUpCompletion`` (``FollowUpView``);
* a **check-back** — a company parked at ``NOT_NOW``, whose
  ``conversation_check_back_on`` says when to try again, and which is dealt with by
  *moving the conversation gauge*, not by completing anything
  (``CheckBackView``).

They are deliberately not merged into one row type. They are completed through
different services, only one of them has a completion record, and only one of them
has an activity — a single type would be half-null on every row and would invite
code that treats a check-back as a completable thing. It is not: a check-back date
moves only through ``ConversationService`` (``docs/contracts/engagement.md`` §2.1),
and Phase 2 never writes it.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.onboarding.domain.entities.engagement_enums import (
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.follow_up_completion import FollowUpOutcome


class FollowUpState(str, enum.Enum):
    """Where a follow-up stands. **Derived, never stored** — architecture §9.3's
    first "Watch out for": there is no status column on an activity, and adding one
    would mean updating an append-only row.

    The rules, from ``docs/contracts/engagement.md`` §5.6 and this prompt's §7.1:

    * ``OUTSTANDING`` — the activity has a ``due_at`` and **no** completion row.
    * ``OVERDUE`` — outstanding, and ``due_at`` is in the past. A narrowing of
      ``OUTSTANDING``, not a value beside it: everything overdue is also
      outstanding, which is why ``is_overdue`` is a flag on the row and this enum is
      only what a caller may *filter* by.
    * ``DONE`` — a completion row exists, whatever its outcome. ``CANCELLED`` and
      ``NO_ANSWER`` are dealt-with, not outstanding: someone decided, and that
      decision is the record.
    """

    OUTSTANDING = "OUTSTANDING"
    OVERDUE = "OVERDUE"
    DONE = "DONE"


@dataclass(frozen=True)
class FollowUpCompletionView:
    """The completion of a follow-up, as the list shows it.

    Every field here comes from the ``follow_up_completion`` row and **none** from
    the activity: "who completed it and when" is the completion's to say, and the
    activity cannot carry it because nothing may write to the activity after it is
    logged.
    """

    id: uuid.UUID
    outcome: FollowUpOutcome
    note: str | None
    next_due_at: datetime | None
    completed_by: str | None
    completed_at: datetime


@dataclass(frozen=True)
class FollowUpView:
    """One row of the Follow-ups list: an activity with a due date, plus its
    completion if it has one.

    ``completion`` is ``None`` exactly when the follow-up is outstanding, so the two
    halves of the row cannot contradict each other — there is no state field to
    forget to update, because ``state`` is computed from this one fact.

    ``is_overdue`` is computed once, at view-construction time, against the same
    ``now`` the query was run with — never recomputed from a fresh
    ``datetime.now()`` deeper in a template, which would let two parts of one
    response disagree. The same rule ``PendingActivityView`` states.
    """

    activity_id: uuid.UUID
    customer_id: uuid.UUID
    #: The company's own name. `None` for a company created without one. Resolved by
    #: one join in the repository, never by a per-row query.
    exporter_display_name: str | None
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    #: Who logged the follow-up. Not who completed it — that is on `completion`.
    actor_id: str
    occurred_at: datetime
    #: Never `None`: a row without a due date is not a follow-up, and the query does
    #: not return one.
    due_at: datetime
    is_overdue: bool
    completion: FollowUpCompletionView | None

    @property
    def state(self) -> FollowUpState:
        """``DONE`` once a completion exists; otherwise ``OVERDUE`` or
        ``OUTSTANDING``. A property rather than a stored field so it cannot drift
        from ``completion``."""
        if self.completion is not None:
            return FollowUpState.DONE
        return FollowUpState.OVERDUE if self.is_overdue else FollowUpState.OUTSTANDING


@dataclass(frozen=True)
class CheckBackView:
    """One company parked at ``NOT_NOW``, due to be picked up on
    ``check_back_on``.

    Not a follow-up and not completable. It is dealt with by moving the conversation
    gauge — ``POST /exporters/{id}/conversation`` — which clears the date in the same
    transaction (``docs/contracts/engagement.md`` §2.3). **Phase 2 never writes
    this date**, exactly as Developer 3B never writes ``conversation``.

    ``conversation`` is carried even though it is always ``NOT_NOW`` today, because
    ``ck_exporter_profile_conversation_check_back`` is what makes that true and this
    view should not be the place that quietly assumes it.
    """

    customer_id: uuid.UUID
    exporter_display_name: str | None
    conversation: ExporterConversation
    check_back_on: date
    is_overdue: bool


@dataclass(frozen=True)
class FollowUpListView:
    """The Follow-ups screen's answer: both lists, each with its own total.

    Totals are the counts matching the same filters, not the lengths of the lists, so
    a caller can tell whether there is more without asking for it — the same
    convention ``HistoryListResponse`` uses.
    """

    follow_ups: tuple[FollowUpView, ...]
    follow_ups_total: int
    check_backs: tuple[CheckBackView, ...]
    check_backs_total: int


__all__ = [
    "CheckBackView",
    "FollowUpCompletionView",
    "FollowUpListView",
    "FollowUpState",
    "FollowUpView",
]
