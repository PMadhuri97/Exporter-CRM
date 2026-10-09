"""Who may approve a proposal, under each approval mode."""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.approval_mode import (
    ApprovalMode,
    approval_refusal,
    parse_approval_mode,
)

PROPOSE = "exporters:manage_bank_accounts"
APPROVE = "exporters:approve_bank_accounts"


def refusal(mode: ApprovalMode, *, approver: str, permissions: set[str]) -> str | None:
    return approval_refusal(
        mode,
        proposer_id="maker",
        approver_id=approver,
        approver_permissions=permissions,
        propose_permission=PROPOSE,
        approve_permission=APPROVE,
    )


@pytest.mark.parametrize(
    ("mode", "approver", "permissions", "allowed"),
    [
        (ApprovalMode.OFF, "maker", set(), True),
        (ApprovalMode.SECOND_PERSON, "maker", {PROPOSE, APPROVE}, False),
        (ApprovalMode.SECOND_PERSON, "other", {PROPOSE}, True),
        (ApprovalMode.SECOND_PERSON, "other", set(), False),
        (ApprovalMode.PERMISSION_HOLDER, "maker", {APPROVE}, True),
        (ApprovalMode.PERMISSION_HOLDER, "other", {PROPOSE}, False),
        (ApprovalMode.BOTH, "maker", {APPROVE}, False),
        (ApprovalMode.BOTH, "other", {APPROVE}, True),
        (ApprovalMode.BOTH, "other", {PROPOSE}, False),
    ],
)
def test_each_mode_admits_exactly_its_approvers(mode, approver, permissions, allowed):
    assert (refusal(mode, approver=approver, permissions=permissions) is None) is allowed


def test_a_refusal_says_why():
    assert "proposed it" in refusal(ApprovalMode.BOTH, approver="maker", permissions={APPROVE})
    assert APPROVE in refusal(ApprovalMode.PERMISSION_HOLDER, approver="x", permissions=set())


def test_the_setting_is_read_case_blind_and_refused_when_unknown():
    assert parse_approval_mode(" both ", setting="X") is ApprovalMode.BOTH
    with pytest.raises(ValueError, match="X must be one of"):
        parse_approval_mode("SOMETIMES", setting="X")
