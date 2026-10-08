"""Business time: adding a service level to a moment, and measuring time between two.

A 4-hour approval target must not turn "overdue" every evening, so service levels are
measured in a working calendar — working days, opening and closing times in one time
zone, and holidays — not in wall-clock time. Pure functions over aware datetimes and
a :class:`BusinessCalendar`; nothing here reads a setting or the clock, so a unit test
pins every case (``compliance_settings.business_calendar`` builds the configured one).

A **business day** is one opening-to-closing span, so ``1d`` and ``9h`` are the same
allowance in a 09:30–18:30 calendar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

#: The longest span a calculation walks, so a calendar with no working day (refused
#: on parse) or an absurd duration cannot loop forever.
_MAX_DAYS = 3660


@dataclass(frozen=True)
class BusinessCalendar:
    """Working days (0 = Monday), daily opening hours and holidays, in ``tz``."""

    tz: ZoneInfo
    workdays: frozenset[int]
    opens: time
    closes: time
    holidays: frozenset[date] = frozenset()

    @property
    def day_length(self) -> timedelta:
        return datetime.combine(date.min, self.closes) - datetime.combine(date.min, self.opens)

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.workdays and day not in self.holidays

    def window(self, day: date) -> tuple[datetime, datetime]:
        """The day's opening and closing moments, aware, in ``tz``."""
        return (
            datetime.combine(day, self.opens, tzinfo=self.tz),
            datetime.combine(day, self.closes, tzinfo=self.tz),
        )


def parse_hours(spec: str, tz_name: str, holidays: str = "") -> BusinessCalendar:
    """``MON-FRI 09:30-18:30`` (or ``MON,WED,FRI 10:00-17:00``) into a calendar.

    Raises:
        ValueError: an unreadable spec, no working day, closing at or before opening,
            an unknown time zone or a holiday that is not an ISO date.
    """
    match = re.fullmatch(
        r"\s*([A-Za-z,\-]+)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", spec or ""
    )
    if match is None:
        raise ValueError(f"business hours {spec!r} are not like 'MON-FRI 09:30-18:30'")
    days_part, oh, om, ch, cm = match.groups()
    workdays: set[int] = set()
    for chunk in days_part.upper().split(","):
        if "-" in chunk:
            first, _, last = chunk.partition("-")
            if first not in _DAYS or last not in _DAYS:
                raise ValueError(f"unknown day in business hours {spec!r}")
            start, end = _DAYS.index(first), _DAYS.index(last)
            span = range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
            workdays.update(span)
        else:
            if chunk not in _DAYS:
                raise ValueError(f"unknown day in business hours {spec!r}")
            workdays.add(_DAYS.index(chunk))
    opens, closes = time(int(oh), int(om)), time(int(ch), int(cm))
    if closes <= opens:
        raise ValueError(f"business hours {spec!r} close at or before they open")
    if not workdays:
        raise ValueError(f"business hours {spec!r} have no working day")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # ZoneInfoNotFoundError, or a malformed key
        raise ValueError(f"unknown time zone {tz_name!r}") from exc
    days: set[date] = set()
    for item in (holidays or "").split(","):
        if item.strip():
            try:
                days.add(date.fromisoformat(item.strip()))
            except ValueError as exc:
                raise ValueError(f"holiday {item.strip()!r} is not an ISO date") from exc
    return BusinessCalendar(
        tz=tz, workdays=frozenset(workdays), opens=opens, closes=closes, holidays=frozenset(days)
    )


def parse_duration(spec: str, calendar: BusinessCalendar) -> timedelta:
    """``1d``, ``4h``, ``90m`` or a sum (``1d 2h``) as business time.

    Raises:
        ValueError: an unreadable or non-positive duration.
    """
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([dhm])", (spec or "").lower())
    leftover = re.sub(r"(\d+(?:\.\d+)?)\s*([dhm])", "", (spec or "").lower()).strip()
    if not parts or leftover:
        raise ValueError(f"duration {spec!r} is not like '1d', '4h' or '90m'")
    total = timedelta()
    for amount, unit in parts:
        value = float(amount)
        if unit == "d":
            total += calendar.day_length * value
        elif unit == "h":
            total += timedelta(hours=value)
        else:
            total += timedelta(minutes=value)
    if total <= timedelta():
        raise ValueError(f"duration {spec!r} must be more than zero")
    return total


def add(start: datetime, duration: timedelta, calendar: BusinessCalendar) -> datetime:
    """The moment ``duration`` of business time after ``start``, in UTC.

    A start outside working time counts from the next opening. A due time that falls
    exactly at closing stays at closing rather than moving to the next opening.
    """
    _require_aware(start)
    remaining = duration
    current = start.astimezone(calendar.tz)
    day = current.date()
    for _ in range(_MAX_DAYS):
        if calendar.is_working_day(day):
            opens, closes = calendar.window(day)
            begin = max(current, opens)
            if begin < closes:
                available = closes - begin
                if remaining <= available:
                    return (begin + remaining).astimezone(UTC)
                remaining -= available
        day += timedelta(days=1)
        current = datetime.combine(day, time.min, tzinfo=calendar.tz)
    raise ValueError("business time ran past the calendar's limit")


def elapsed(start: datetime, end: datetime, calendar: BusinessCalendar) -> timedelta:
    """Business time between ``start`` and ``end`` (zero if ``end`` is not later)."""
    _require_aware(start)
    _require_aware(end)
    if end <= start:
        return timedelta()
    local_start, local_end = start.astimezone(calendar.tz), end.astimezone(calendar.tz)
    total = timedelta()
    day = local_start.date()
    last = local_end.date()
    for _ in range(_MAX_DAYS):
        if day > last:
            return total
        if calendar.is_working_day(day):
            opens, closes = calendar.window(day)
            begin, finish = max(opens, local_start), min(closes, local_end)
            if finish > begin:
                total += finish - begin
        day += timedelta(days=1)
    raise ValueError("business time ran past the calendar's limit")


@dataclass(frozen=True)
class Deadline:
    """One clock's state at ``now``: when it is due, and whether it is due soon or
    already overdue."""

    started_at: datetime
    due_at: datetime
    is_due_soon: bool
    is_overdue: bool


def deadline(
    started_at: datetime,
    allowance: timedelta,
    *,
    now: datetime,
    calendar: BusinessCalendar,
    due_soon_fraction: float,
    paused: timedelta = timedelta(),
) -> Deadline:
    """The clock started at ``started_at`` with ``allowance`` of business time, of
    which ``paused`` (business time) does not count — the review clock while
    information was requested."""
    due_at = add(started_at, allowance + paused, calendar)
    used = elapsed(started_at, now, calendar) - paused
    return Deadline(
        started_at=started_at,
        due_at=due_at,
        is_overdue=now >= due_at,
        is_due_soon=now < due_at and used >= allowance * due_soon_fraction,
    )


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("business time needs time-zone-aware datetimes")


__all__ = [
    "BusinessCalendar",
    "Deadline",
    "add",
    "deadline",
    "elapsed",
    "parse_duration",
    "parse_hours",
]
