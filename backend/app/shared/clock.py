"""The injectable clock — "now" for new code.

New code that needs the current time asks this module instead of calling
``datetime.now(...)`` inline, so a test can move "now" — past a Clear's expiry, for
instance — without sleeping and without patching ``datetime``. There is no
freezegun or time-machine in ``requirements-dev.txt``, and this is why.

Two ways in, both deliberately small:

* **``now()``** — the current UTC time from whichever clock is installed. The
  default is the system clock, so production code pays nothing for this.
* **``use_clock(clock)``** — a context manager that installs another clock (a
  ``FixedClock``) for the duration of a ``with`` block and restores the previous one
  afterwards, even on error. Tests use it; nothing else should.

A service that wants to be driven by an explicit clock may also take a ``Clock``
argument; ``Clock`` is the protocol both clocks satisfy.

**Always timezone-aware UTC.** A naive datetime compared with a ``timestamptz``
column is a bug waiting for a server in another timezone, so both clocks refuse to
hand one out and ``FixedClock`` refuses to be set to one.

Not a global mutable in disguise for production: the installed clock is only ever
changed by ``use_clock``, which restores it. It is process-wide rather than
per-task on purpose — a request served through the ASGI test transport runs in
tasks the test did not create, and a context variable set in the test would not be
guaranteed to reach them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that can say what time it is, as an aware UTC datetime."""

    def now(self) -> datetime: ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a clock deals in timezone-aware datetimes; got a naive one")
    return value.astimezone(UTC)


class FixedClock:
    """A clock that says whatever it was last told. For tests.

    ``set`` moves it anywhere; ``advance`` moves it forward (or back, with a negative
    delta). It never moves on its own.
    """

    def __init__(self, at: datetime | None = None) -> None:
        self._at = _require_aware(at) if at is not None else datetime.now(UTC)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = _require_aware(at)

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta


_SYSTEM_CLOCK = SystemClock()
_installed: Clock = _SYSTEM_CLOCK


def current_clock() -> Clock:
    """The clock ``now()`` reads — the system clock unless a test installed another."""
    return _installed


def now() -> datetime:
    """The current time, timezone-aware UTC, from the installed clock."""
    return _require_aware(_installed.now())


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    """Install ``clock`` for the ``with`` block, then put the previous one back."""
    global _installed
    previous = _installed
    _installed = clock
    try:
        yield clock
    finally:
        _installed = previous


__all__ = ["Clock", "FixedClock", "SystemClock", "current_clock", "now", "use_clock"]
