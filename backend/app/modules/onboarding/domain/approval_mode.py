"""Who may approve a proposal — one rule for every propose-then-approve flow that is not
the background check's own maker-checker (bank-detail changes first).

``ApprovalMode`` comes from a setting per flow:

* ``OFF`` — no approval: a proposal takes effect when it is made.
* ``SECOND_PERSON`` — anyone allowed to propose, except the proposer.
* ``PERMISSION_HOLDER`` — a holder of the flow's approve permission, the proposer
  included.
* ``BOTH`` — a holder of the approve permission who is not the proposer.

The route admits whoever may propose **or** approve; :func:`approval_refusal` then
says whether this person may approve this proposal, and why not.
"""

from __future__ import annotations

import enum
from collections.abc import Collection

#: Where a flow's approval may be switched off.
APPROVAL_OFF_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test", "testing"})


class ApprovalMode(str, enum.Enum):
    OFF = "OFF"
    SECOND_PERSON = "SECOND_PERSON"
    PERMISSION_HOLDER = "PERMISSION_HOLDER"
    BOTH = "BOTH"


def parse_approval_mode(value: str, *, setting: str) -> ApprovalMode:
    try:
        return ApprovalMode(value.strip().upper())
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in ApprovalMode)
        raise ValueError(f"{setting} must be one of {allowed}, not {value!r}") from exc


def approval_refusal(
    mode: ApprovalMode,
    *,
    proposer_id: str | None,
    approver_id: str,
    approver_permissions: Collection[str],
    propose_permission: str,
    approve_permission: str,
) -> str | None:
    """Why ``approver_id`` may not approve, or ``None`` when they may.

    Permissions are ``module:action`` strings, as the user's resolved grants hold them.
    """
    is_proposer = proposer_id is not None and proposer_id == approver_id
    holds_approve = approve_permission in approver_permissions
    if mode is ApprovalMode.OFF:
        return None
    if mode is ApprovalMode.SECOND_PERSON:
        if is_proposer:
            return "the person who proposed it cannot also approve it"
        if not (holds_approve or propose_permission in approver_permissions):
            return f"approving needs {propose_permission} or {approve_permission}"
        return None
    if not holds_approve:
        return f"approving needs {approve_permission}"
    if mode is ApprovalMode.BOTH and is_proposer:
        return "the person who proposed it cannot also approve it"
    return None


__all__ = [
    "APPROVAL_OFF_ALLOWED_ENVIRONMENTS",
    "ApprovalMode",
    "approval_refusal",
    "parse_approval_mode",
]
