"""The rules of sanctions screening: a run's outcome, the company's standing, and who
may confirm a true match."""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain import sanctions as rules


@pytest.mark.parametrize(
    ("dispositions", "outcome"),
    [
        ([], "PASSED"),
        (["FALSE_POSITIVE", "FALSE_POSITIVE"], "PASSED"),
        (["FALSE_POSITIVE", "OPEN"], "REVIEW"),
        (["ESCALATED"], "REVIEW"),
        (["TRUE_MATCH_PROPOSED"], "REVIEW"),
        (["OPEN", "TRUE_MATCH"], "FAILED"),
    ],
)
def test_a_runs_outcome_comes_from_its_hits(dispositions, outcome):
    assert rules.run_outcome(dispositions) == outcome


def test_the_company_standing_is_the_worst_subject_and_unknown_until_screened():
    assert rules.company_standing({}, company_screened=False) is None
    assert rules.company_standing({"c": "PASSED", "u": "REVIEW"}, company_screened=True) == "REVIEW"
    assert rules.company_standing({"c": "PASSED", "u": "FAILED"}, company_screened=True) == "FAILED"
    assert rules.company_standing({"c": "PASSED"}, company_screened=True) == "PASSED"


@pytest.mark.parametrize(
    ("mode", "approver", "permissions", "allowed"),
    [
        (rules.TrueMatchApproval.SINGLE, "maker", set(), True),
        (rules.TrueMatchApproval.SECOND_OFFICER, "maker", {"screening:decide"}, False),
        (rules.TrueMatchApproval.SECOND_OFFICER, "other", {"screening:decide"}, True),
        (rules.TrueMatchApproval.SECOND_OFFICER, "other", set(), False),
        (rules.TrueMatchApproval.HEAD, "other", {"screening:decide"}, False),
        (rules.TrueMatchApproval.HEAD, "other", {"compliance:approve_true_match"}, True),
        (rules.TrueMatchApproval.HEAD, "maker", {"compliance:approve_true_match"}, False),
    ],
)
def test_who_may_confirm_a_true_match(mode, approver, permissions, allowed):
    refusal = rules.true_match_refusal(
        mode, proposer_id="maker", approver_id=approver, approver_permissions=permissions
    )
    assert (refusal is None) is allowed


def test_the_setting_is_checked():
    assert rules.parse_true_match_approval("head") is rules.TrueMatchApproval.HEAD
    with pytest.raises(ValueError, match="CRM_SANCTIONS_TRUE_MATCH_APPROVAL"):
        rules.parse_true_match_approval("ANYONE")
