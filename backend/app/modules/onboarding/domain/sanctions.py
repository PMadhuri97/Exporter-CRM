"""The rules of sanctions screening, without a database.

* **A run's outcome** comes from its hits' current dispositions: FAILED when any is a
  confirmed true match; REVIEW while any is open, escalated or a true match awaiting
  approval; PASSED when there are none, or every one is a false positive.
* **A company's sanctions standing** is the worst outcome among its subjects' latest
  runs; it stays unknown until the company itself has been screened.
* **Who may confirm a true match** is ``CRM_SANCTIONS_TRUE_MATCH_APPROVAL``: SINGLE (the
  officer's own decision stands), SECOND_OFFICER (another officer confirms it) or HEAD
  (a holder of ``compliance:approve_true_match`` other than the proposer confirms it).
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Iterable

PASSED = "PASSED"
FAILED = "FAILED"
REVIEW = "REVIEW"

OPEN = "OPEN"
FALSE_POSITIVE = "FALSE_POSITIVE"
TRUE_MATCH_PROPOSED = "TRUE_MATCH_PROPOSED"
TRUE_MATCH = "TRUE_MATCH"
ESCALATED = "ESCALATED"

#: What an officer may record on a hit. A confirmed TRUE_MATCH is reached through the
#: approval rule, never set directly unless the mode is SINGLE.
RECORDABLE = frozenset({OPEN, FALSE_POSITIVE, TRUE_MATCH, ESCALATED})
#: Dispositions that put the company under a sanctions flag.
FLAGGING = frozenset({TRUE_MATCH_PROPOSED, TRUE_MATCH})

RECORD_PERMISSION = "screening:decide"
HEAD_PERMISSION = "compliance:approve_true_match"


class TrueMatchApproval(str, enum.Enum):
    SINGLE = "SINGLE"
    SECOND_OFFICER = "SECOND_OFFICER"
    HEAD = "HEAD"


def parse_true_match_approval(value: str) -> TrueMatchApproval:
    try:
        return TrueMatchApproval(value.strip().upper())
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TrueMatchApproval)
        raise ValueError(
            f"CRM_SANCTIONS_TRUE_MATCH_APPROVAL must be one of {allowed}, not {value!r}"
        ) from exc


def run_outcome(dispositions: Iterable[str]) -> str:
    """A run's outcome from its hits' current dispositions."""
    current = list(dispositions)
    if any(d == TRUE_MATCH for d in current):
        return FAILED
    if any(d in (OPEN, ESCALATED, TRUE_MATCH_PROPOSED) for d in current):
        return REVIEW
    return PASSED


def company_standing(outcomes: dict[str, str], *, company_screened: bool) -> str | None:
    """The worst of the subjects' latest outcomes, or ``None`` before the company itself
    has been screened."""
    if not company_screened:
        return None
    values = set(outcomes.values())
    if FAILED in values:
        return FAILED
    if REVIEW in values:
        return REVIEW
    return PASSED


def true_match_refusal(
    mode: TrueMatchApproval,
    *,
    proposer_id: str,
    approver_id: str,
    approver_permissions: Collection[str],
) -> str | None:
    """Why ``approver_id`` may not confirm this proposed true match, or ``None``."""
    if mode is TrueMatchApproval.SINGLE:
        return None
    if approver_id == proposer_id:
        return "the officer who proposed it cannot also confirm it"
    if mode is TrueMatchApproval.HEAD and HEAD_PERMISSION not in approver_permissions:
        return f"confirming a true match needs {HEAD_PERMISSION}"
    if mode is TrueMatchApproval.SECOND_OFFICER and RECORD_PERMISSION not in approver_permissions:
        return f"confirming a true match needs {RECORD_PERMISSION}"
    return None


__all__ = [
    "ESCALATED",
    "FAILED",
    "FALSE_POSITIVE",
    "FLAGGING",
    "OPEN",
    "PASSED",
    "RECORDABLE",
    "REVIEW",
    "TRUE_MATCH",
    "TRUE_MATCH_PROPOSED",
    "TrueMatchApproval",
    "company_standing",
    "parse_true_match_approval",
    "run_outcome",
    "true_match_refusal",
]
