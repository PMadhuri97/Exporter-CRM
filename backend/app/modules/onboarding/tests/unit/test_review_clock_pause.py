"""The review clock's pause: business time spent waiting on information since the
reviewer was assigned does not count against the reviewer.

Pure, with fixed times on the default calendar (Monday–Friday 09:30–18:30,
Asia/Kolkata), so it does not depend on when the suite runs. 12 October 2026 is a
Monday.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modules.onboarding.application.compliance_worklists import info_pause
from app.modules.onboarding.domain.business_time import parse_hours
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckState as State,
)

IST = ZoneInfo("Asia/Kolkata")
CAL = parse_hours("MON-FRI 09:30-18:30", "Asia/Kolkata")


def ist(d, hh, mm=0) -> datetime:
    return datetime(2026, 10, d, hh, mm, tzinfo=IST)


def move(at: datetime, from_value: State | None, to_value: State) -> SimpleNamespace:
    return SimpleNamespace(decided_at=at, from_value=from_value, to_value=to_value)


def pause(chain, *, assigned_at, now=ist(14, 18, 30)) -> timedelta:
    return info_pause(chain, assigned_at=assigned_at, now=now, calendar=CAL)


def test_a_request_made_after_the_assignment_pauses_until_it_is_answered():
    chain = [
        move(ist(12, 9, 30), State.NOT_STARTED, State.IN_REVIEW),
        move(ist(12, 11, 0), State.IN_REVIEW, State.MORE_INFO),
        move(ist(12, 14, 0), State.MORE_INFO, State.IN_REVIEW),
    ]
    assert pause(chain, assigned_at=ist(12, 10, 0)) == timedelta(hours=3)


def test_a_reviewer_assigned_while_information_is_requested_starts_paused():
    chain = [
        move(ist(12, 9, 30), State.NOT_STARTED, State.IN_REVIEW),
        move(ist(12, 10, 0), State.IN_REVIEW, State.MORE_INFO),
        move(ist(12, 15, 0), State.MORE_INFO, State.IN_REVIEW),
    ]
    # Assigned at 12:00, during the request: 12:00–15:00 is the information clock's.
    assert pause(chain, assigned_at=ist(12, 12, 0)) == timedelta(hours=3)


def test_a_request_still_open_counts_up_to_now():
    chain = [
        move(ist(12, 9, 30), State.NOT_STARTED, State.IN_REVIEW),
        move(ist(12, 17, 30), State.IN_REVIEW, State.MORE_INFO),
    ]
    # 17:30–18:30 Monday, then all of Tuesday until 13:30: 1 h + 4 h.
    assert pause(chain, assigned_at=ist(12, 10, 0), now=ist(13, 13, 30)) == timedelta(hours=5)


def test_no_request_since_the_assignment_pauses_nothing():
    chain = [
        move(ist(12, 9, 30), State.NOT_STARTED, State.IN_REVIEW),
        move(ist(12, 10, 0), State.IN_REVIEW, State.MORE_INFO),
        move(ist(12, 11, 0), State.MORE_INFO, State.IN_REVIEW),
    ]
    assert pause(chain, assigned_at=ist(12, 12, 0)) == timedelta()


def test_two_requests_add_up_and_the_evening_does_not_count():
    chain = [
        move(ist(12, 10, 0), State.IN_REVIEW, State.MORE_INFO),
        move(ist(12, 11, 0), State.MORE_INFO, State.IN_REVIEW),
        move(ist(12, 18, 0), State.IN_REVIEW, State.MORE_INFO),
        move(ist(13, 10, 30), State.MORE_INFO, State.IN_REVIEW),
    ]
    # 1 h, then 18:00–18:30 and 09:30–10:30 the next day.
    assert pause(chain, assigned_at=ist(12, 9, 30)) == timedelta(hours=2, minutes=30)
