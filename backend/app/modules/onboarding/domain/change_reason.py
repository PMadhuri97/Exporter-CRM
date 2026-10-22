"""Why a live rule was changed: the change-management record on every settings version.

Qualification criteria, deal required documents, payment terms and sanctions lists are
live rules — a change applies to the next lead qualified, deal handed over or company
screened. Every change writes a new version, and since migration 0063 that version also
carries ``change_reason``: the ticket number or explanation an administrator gave for
it. Without one a change is refused, so no rule moves on a single click.

A valid reason is a **ticket reference followed by a short explanation**, so a reviewer
can both find the ticket and read what was done without opening it:

* the ticket comes first, in capitals — ``CHG-1042``, ``JIRA-381`` or a
  ServiceNow-style ``CHG0031234`` — so "chg-7" or a ticket buried mid-sentence is
  refused;
* then a separator (``:``, a dash, or a space) and an explanation of at least
  ``MIN_TEXT_LENGTH`` characters and ``MIN_WORDS`` real words (two or more Latin
  letters each), so "CHG-7", "CHG-7: x" or a run of symbols or emoji are refused while
  "CHG-1042: raise the turnover floor" is not.

The front end applies the same rule as the administrator types (``changeReasonProblem``
in ``frontend/.../components/change-reason.ts``); this module is the authority.
"""

from __future__ import annotations

import re

from app.shared.exceptions import ValidationError

#: Longest reason kept. Long enough for a ticket and a sentence or two of context.
MAX_LENGTH = 500
#: The explanation after the ticket.
MIN_TEXT_LENGTH = 10
MIN_WORDS = 2

#: ``ABC-123`` (Jira and most trackers), or capitals followed by five or more digits
#: (``CHG0031234``, ``INC0012345``), at the start; then the explanation. ``[0-9]``,
#: not ``\d``: Python's ``\d`` takes any script's digits.
_REASON = re.compile(
    r"^(?P<ticket>[A-Z]{2,10}(?:-[0-9]+|[0-9]{5,}))(?:(?:\s*[:–—-]\s*|\s+)(?P<text>.*))?$"
)
_WORD = re.compile(r"[A-Za-z]{2,}")

REQUIRED_MESSAGE = (
    "A reason for the change is required: a ticket number and a short explanation"
)
NO_TICKET_MESSAGE = "Start with a ticket number in capitals, e.g. CHG-1042: …"
TOO_VAGUE_MESSAGE = (
    "After the ticket number, explain the change in at least "
    f"{MIN_WORDS} words and {MIN_TEXT_LENGTH} characters"
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
    match = _REASON.match(cleaned)
    if match is None:
        return NO_TICKET_MESSAGE
    explanation = match.group("text") or ""
    words = [word for word in explanation.split(" ") if _WORD.search(word)]
    if len(explanation) < MIN_TEXT_LENGTH or len(words) < MIN_WORDS:
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
    "MIN_TEXT_LENGTH",
    "MIN_WORDS",
    "change_reason_problem",
    "clean_change_reason",
    "require_change_reason",
]
