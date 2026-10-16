"""Why a live rule was changed: the change-management record on every settings version.

Qualification criteria, deal required documents, payment terms and sanctions lists are
live rules — a change applies to the next lead qualified, deal handed over or company
screened. Every change writes a new version, and since migration 0063 that version also
carries ``change_reason``: the ticket number or explanation an administrator gave for
it. Without one a change is refused, so no rule moves on a single click.

"Valid" is deliberately simple, because the reader is a person, not a parser:

* a **ticket reference** on its own is enough — ``CHG-1042``, ``JIRA-381`` or a
  ServiceNow-style ``CHG0031234``; or
* a **description** of at least ``MIN_LENGTH`` characters and ``MIN_WORDS`` words, so
  "test", "update" or "." are refused while "Raise turnover floor per credit committee"
  is not.

The front end applies the same rule as the administrator types (``changeReasonProblem``
in ``frontend/.../components/change-reason.ts``); this module is the authority.
"""

from __future__ import annotations

import re

from app.shared.exceptions import ValidationError

#: Longest reason kept. Long enough for a ticket and a sentence or two of context.
MAX_LENGTH = 500
MIN_LENGTH = 15
MIN_WORDS = 3

#: ``ABC-123`` (Jira and most trackers), or letters followed by five or more digits
#: (``CHG0031234``, ``INC0012345``).
_TICKET = re.compile(r"\b[A-Za-z]{2,10}(?:-\d+|\d{5,})\b")

REQUIRED_MESSAGE = "A reason for the change is required: a ticket number or a short explanation"
TOO_VAGUE_MESSAGE = (
    "Give a ticket number (e.g. CHG-1042) or explain the change in at least "
    f"{MIN_WORDS} words and {MIN_LENGTH} characters"
)


def clean_change_reason(text: str | None) -> str:
    """The reason as it is stored: trimmed, with runs of whitespace collapsed."""
    return " ".join((text or "").split())


def change_reason_problem(text: str | None) -> str | None:
    """What is wrong with ``text`` as a change reason, or ``None`` when it will do."""
    cleaned = clean_change_reason(text)
    if not cleaned:
        return REQUIRED_MESSAGE
    if len(cleaned) > MAX_LENGTH:
        return f"Keep the reason to {MAX_LENGTH} characters"
    if _TICKET.search(cleaned):
        return None
    if len(cleaned) < MIN_LENGTH or len(cleaned.split(" ")) < MIN_WORDS:
        return TOO_VAGUE_MESSAGE
    return None


def require_change_reason(text: str | None) -> str:
    """The cleaned reason, or a 422 saying what is wrong with it. Every service that
    writes a settings version calls this before it writes anything."""
    problem = change_reason_problem(text)
    if problem is not None:
        raise ValidationError(problem)
    return clean_change_reason(text)


__all__ = [
    "MAX_LENGTH",
    "MIN_LENGTH",
    "MIN_WORDS",
    "change_reason_problem",
    "clean_change_reason",
    "require_change_reason",
]
