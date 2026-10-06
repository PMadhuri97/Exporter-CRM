"""Console set-up for the onboarding data commands — the buyer migration and
the trade relationship backfill.

Both are run by an operator at a terminal, often a Windows one, and both print a
report somebody has to read and attach to a ticket. Two things went wrong there:

* **A cp1252 console cannot encode every character.** The commands printed ``→``,
  which crashed the backfill with ``UnicodeEncodeError`` *before* ``--apply`` wrote
  anything, and the buyer migration as soon as a conflict row was printed. The
  commands' own text is now ASCII; this also makes the streams replace what they
  cannot encode, because a report prints data too — a buyer's name in another script
  must print as an escape, not stop the run.
* **The development ``.env`` buries the report.** ``DEBUG=true`` makes the engine echo
  every SQL statement and ``LOG_LEVEL=DEBUG``/``INFO`` interleaves log lines with the
  report. The documented way to run them is ``LOG_LEVEL=WARNING DEBUG=false``; this
  says so when the settings differ, and changes no logging itself.
"""

from __future__ import annotations

import sys

from app.platform.configuration.config import get_settings

#: How to run a data command so its output is the report and nothing else.
QUIET_SETTINGS = "LOG_LEVEL=WARNING DEBUG=false"

_NOISY_LEVELS = frozenset({"DEBUG", "INFO", "NOTSET"})


def prepare_console() -> None:
    """Make stdout and stderr replace what the console cannot encode, and point at
    the quiet settings when the current ones will interleave SQL or log lines."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")

    settings = get_settings()
    if settings.DEBUG or str(settings.LOG_LEVEL).upper() in _NOISY_LEVELS:
        print(
            f"note: DEBUG={settings.DEBUG} LOG_LEVEL={settings.LOG_LEVEL} will mix SQL and "
            f"log lines into the report; run with {QUIET_SETTINGS} for the report alone.",
            file=sys.stderr,
        )


__all__ = ["QUIET_SETTINGS", "prepare_console"]
