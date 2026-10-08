"""Business time: service levels measured in working hours, not wall-clock hours.

Pure functions, so every case is pinned without a database: the default calendar
(Monday–Friday 09:30–18:30, Asia/Kolkata), a weekend, a holiday, a start outside
hours, a deadline landing exactly at closing, and the paused review clock.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.onboarding.application.compliance_settings import (
    business_calendar,
    enforce_compliance_settings,
    sla_approval,
    sla_info,
    sla_review,
)
from app.modules.onboarding.domain.business_time import (
    add,
    deadline,
    elapsed,
    parse_duration,
    parse_hours,
)
from app.platform.configuration.config import Settings

IST = ZoneInfo("Asia/Kolkata")
CAL = parse_hours("MON-FRI 09:30-18:30", "Asia/Kolkata")


def ist(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# 9 October 2026 is a Friday.


def test_a_business_day_is_one_opening_to_closing_span():
    assert CAL.day_length == timedelta(hours=9)
    assert parse_duration("1d", CAL) == timedelta(hours=9)
    assert parse_duration("4h", CAL) == timedelta(hours=4)
    assert parse_duration("90m", CAL) == timedelta(minutes=90)
    assert parse_duration("1d 2h", CAL) == timedelta(hours=11)


def test_friday_afternoon_plus_four_hours_is_monday_noon():
    assert add(ist(2026, 10, 9, 17), timedelta(hours=4), CAL) == ist(2026, 10, 12, 12)


def test_the_result_is_utc():
    assert add(ist(2026, 10, 9, 10), timedelta(hours=1), CAL).tzinfo == UTC


def test_a_start_outside_hours_counts_from_the_next_opening():
    # Saturday evening: the clock starts Monday 09:30.
    assert add(ist(2026, 10, 10, 20), timedelta(hours=2), CAL) == ist(2026, 10, 12, 11, 30)
    # Before opening on a working day: the same day's opening.
    assert add(ist(2026, 10, 12, 7), timedelta(hours=1), CAL) == ist(2026, 10, 12, 10, 30)


def test_a_holiday_is_skipped():
    with_holiday = parse_hours("MON-FRI 09:30-18:30", "Asia/Kolkata", "2026-10-12")
    # Friday 17:00 + 4h: 1.5h on Friday, Monday is a holiday, 2.5h on Tuesday.
    assert add(ist(2026, 10, 9, 17), timedelta(hours=4), with_holiday) == ist(2026, 10, 13, 12)


def test_a_deadline_landing_on_closing_stays_at_closing():
    assert add(ist(2026, 10, 9, 9, 30), timedelta(hours=9), CAL) == ist(2026, 10, 9, 18, 30)


def test_elapsed_counts_only_working_time():
    # Friday 17:00 to Monday 11:00: 1.5h + 1.5h.
    assert elapsed(ist(2026, 10, 9, 17), ist(2026, 10, 12, 11), CAL) == timedelta(hours=3)
    assert elapsed(ist(2026, 10, 12, 11), ist(2026, 10, 9, 17), CAL) == timedelta()


def test_an_evening_does_not_make_a_four_hour_approval_overdue():
    started = ist(2026, 10, 9, 16)  # Friday, 2.5h before closing
    saturday = ist(2026, 10, 10, 12)
    clock = deadline(
        started, timedelta(hours=4), now=saturday, calendar=CAL, due_soon_fraction=0.75
    )
    assert clock.due_at == ist(2026, 10, 12, 11)
    assert not clock.is_overdue
    # 2.5 of 4 hours used: not yet "due soon" at 75%.
    assert not clock.is_due_soon


def test_due_soon_then_overdue():
    started = ist(2026, 10, 12, 9, 30)
    allowance = timedelta(hours=4)
    soon = deadline(started, allowance, now=ist(2026, 10, 12, 12, 45), calendar=CAL,
                    due_soon_fraction=0.75)
    assert soon.is_due_soon and not soon.is_overdue
    late = deadline(started, allowance, now=ist(2026, 10, 12, 13, 31), calendar=CAL,
                    due_soon_fraction=0.75)
    assert late.is_overdue and not late.is_due_soon


def test_paused_time_moves_the_deadline_by_the_pause():
    started = ist(2026, 10, 12, 9, 30)
    clock = deadline(
        started,
        timedelta(hours=9),
        now=ist(2026, 10, 13, 9, 30),
        calendar=CAL,
        due_soon_fraction=0.75,
        paused=timedelta(hours=3),
    )
    assert clock.due_at == ist(2026, 10, 13, 12, 30)
    assert not clock.is_overdue


@pytest.mark.parametrize(
    "spec",
    ["", "MON-FRI", "FUNDAY 09:00-17:00", "MON-FRI 18:00-09:00", "MON-FRI 9-17"],
)
def test_unreadable_hours_are_refused(spec):
    with pytest.raises(ValueError):
        parse_hours(spec, "Asia/Kolkata")


def test_an_unknown_zone_or_holiday_is_refused():
    with pytest.raises(ValueError):
        parse_hours("MON-FRI 09:30-18:30", "Mars/Olympus")
    with pytest.raises(ValueError):
        parse_hours("MON-FRI 09:30-18:30", "Asia/Kolkata", "next tuesday")


@pytest.mark.parametrize("spec", ["", "4", "0h", "four hours", "4x"])
def test_unreadable_durations_are_refused(spec):
    with pytest.raises(ValueError):
        parse_duration(spec, CAL)


def test_the_configured_defaults_are_the_agreed_targets():
    calendar = business_calendar()
    assert calendar.tz.key == "Asia/Kolkata"
    assert calendar.workdays == frozenset({0, 1, 2, 3, 4})
    assert calendar.holidays == frozenset()
    assert sla_review() == timedelta(hours=9)
    assert sla_approval() == timedelta(hours=4)
    assert sla_info() == timedelta(hours=9)


def test_the_settings_are_configurable_and_checked_at_start_up():
    custom = Settings(
        CRM_BUSINESS_HOURS="MON-SAT 10:00-17:00",
        CRM_HOLIDAYS="2026-10-20,2026-11-08",
        CRM_SLA_REVIEW="2d",
    )
    calendar = business_calendar(custom)
    assert calendar.workdays == frozenset({0, 1, 2, 3, 4, 5})
    assert date(2026, 10, 20) in calendar.holidays
    assert sla_review(custom) == timedelta(hours=14)
    enforce_compliance_settings(custom)
    with pytest.raises(RuntimeError):
        enforce_compliance_settings(Settings(CRM_SLA_APPROVAL="soon"))
    with pytest.raises(RuntimeError):
        enforce_compliance_settings(Settings(CRM_SLA_DUE_SOON_PERCENT=0))
