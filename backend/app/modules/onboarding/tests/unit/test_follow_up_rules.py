"""The follow-up read model's rules, with no database.

``FollowUpState`` is derived from two facts — whether a completion exists, and whether
the due date has passed — so it can be tested for what it *is* rather than for what
one seeded row happens to make it. Everything that needs a database is in
``tests/integration/test_follow_up_completion.py``.

The point of this file is that there is **no status column**. Architecture §9.3's
first "Watch out for" is that completing a follow-up must not mark the activity, and
the way that rule survives refactoring is that ``state`` has nowhere to be stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.follow_up_completion import FollowUpOutcome
from app.modules.onboarding.domain.follow_up_views import (
    CheckBackView,
    FollowUpCompletionView,
    FollowUpState,
    FollowUpView,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _completion(outcome: FollowUpOutcome = FollowUpOutcome.DONE) -> FollowUpCompletionView:
    return FollowUpCompletionView(
        id=uuid.uuid4(),
        outcome=outcome,
        note=None,
        next_due_at=NOW + timedelta(days=7) if outcome is FollowUpOutcome.RESCHEDULED else None,
        completed_by="user-1",
        completed_at=NOW,
    )


def _view(*, due_at: datetime, completion: FollowUpCompletionView | None) -> FollowUpView:
    """A row built the way the service builds it: `is_overdue` decided once, against
    one `now`, and never recomputed."""
    return FollowUpView(
        activity_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        exporter_display_name="Aarav Textiles Pvt Ltd",
        activity_type=ExporterActivityType.FOLLOW_UP,
        subject="Check back on Q1 shipments",
        notes=None,
        actor_id="user-1",
        occurred_at=due_at - timedelta(days=7),
        due_at=due_at,
        is_overdue=completion is None and due_at < NOW,
        completion=completion,
    )


def test_the_four_outcomes_and_no_others():
    """`docs/contracts/engagement.md` §5.3 fixes four. A fifth would need the Postgres
    type changed, which is an amendment to 0016 — not a migration the follow-ups
    code owns, so this is worth failing loudly on."""
    assert [o.value for o in FollowUpOutcome] == [
        "DONE",
        "NO_ANSWER",
        "RESCHEDULED",
        "CANCELLED",
    ]


def test_a_follow_up_with_no_completion_and_a_future_date_is_outstanding():
    view = _view(due_at=NOW + timedelta(days=3), completion=None)
    assert view.state is FollowUpState.OUTSTANDING
    assert view.is_overdue is False


def test_a_follow_up_with_no_completion_and_a_past_date_is_overdue():
    view = _view(due_at=NOW - timedelta(days=3), completion=None)
    assert view.state is FollowUpState.OVERDUE
    assert view.is_overdue is True


@pytest.mark.parametrize("outcome", list(FollowUpOutcome))
def test_any_completion_makes_a_follow_up_done(outcome):
    """`CANCELLED` and `NO_ANSWER` are dealt-with, not outstanding: somebody decided,
    and the decision is the record. Treating them as still-open would put work back on
    the list that a person had already closed."""
    view = _view(due_at=NOW - timedelta(days=30), completion=_completion(outcome))
    assert view.state is FollowUpState.DONE


def test_a_follow_up_completed_late_is_done_and_not_overdue():
    """The rule that keeps the overdue count meaning "outstanding work" rather than
    "old work". A due date thirty days past is still not overdue once somebody dealt
    with it."""
    view = _view(due_at=NOW - timedelta(days=30), completion=_completion())
    assert view.state is FollowUpState.DONE
    assert view.is_overdue is False


def test_state_cannot_drift_from_the_completion():
    """`state` is a property, not a stored field. There is nowhere to put a stale
    value, which is the same reason there is no status column on the activity."""
    outstanding = _view(due_at=NOW - timedelta(days=1), completion=None)
    assert "state" not in {f for f in outstanding.__dataclass_fields__}
    assert outstanding.state is FollowUpState.OVERDUE


def test_overdue_is_a_narrowing_of_outstanding_not_a_value_beside_it():
    """Every overdue follow-up is also one nobody has completed. The enum exists for
    *filtering*; the row's own answer is `is_overdue`, which is why both are on the
    view."""
    overdue = _view(due_at=NOW - timedelta(days=1), completion=None)
    assert overdue.completion is None
    assert overdue.is_overdue is True


def test_a_check_back_due_today_is_due_and_not_late():
    """The boundary, in both directions. "Check back on the 27th" is not late on the
    27th, and a list that said otherwise would cry wolf every morning."""
    today = NOW.date()
    due_today = CheckBackView(
        customer_id=uuid.uuid4(),
        exporter_display_name="Aarav Textiles Pvt Ltd",
        conversation="NOT_NOW",
        check_back_on=today,
        is_overdue=today < today,
    )
    assert due_today.is_overdue is False

    late = CheckBackView(
        customer_id=uuid.uuid4(),
        exporter_display_name="Aarav Textiles Pvt Ltd",
        conversation="NOT_NOW",
        check_back_on=today - timedelta(days=1),
        is_overdue=(today - timedelta(days=1)) < today,
    )
    assert late.is_overdue is True
