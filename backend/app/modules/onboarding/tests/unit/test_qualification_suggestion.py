"""The qualification suggestion, with and without required criteria.

With required criteria the rule is unchanged: every required one must pass. With none
required, a company that passed something and failed nothing is suggested
QUALIFIED — before, it read NOT_QUALIFIED whatever it passed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.onboarding.application.qualification_service import suggest_with_reason
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionResultValue as R,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue as Q,
)


def _standing(key: str, result: R | None, *, required=False, active=True, counts=True):
    return SimpleNamespace(
        criterion=SimpleNamespace(key=key, label=key.replace("_", " ").capitalize(),
                                  required=required, active=active),
        latest_result=None if result is None else SimpleNamespace(result=result),
        counts=counts,
    )


def test_with_nothing_required_a_pass_and_no_fail_suggests_qualified():
    outcome, reason = suggest_with_reason([
        _standing("deal_size", R.PASS),
        _standing("export_history", R.PASS),
        _standing("export_licence", R.PASS),
        _standing("geography", None),
        _standing("industry", None),
        _standing("revenue", None),
        _standing("years", None),
    ])
    assert outcome is Q.QUALIFIED
    assert reason == "3 of 7 criteria passed, none failed"


def test_with_nothing_required_one_fail_suggests_not_qualified_and_names_it():
    outcome, reason = suggest_with_reason([
        _standing("deal_size", R.PASS),
        _standing("annual_revenue", R.FAIL),
    ])
    assert outcome is Q.NOT_QUALIFIED
    assert reason == "Failed: Annual revenue"


@pytest.mark.parametrize("results", [[], [None, None], [R.UNKNOWN, None]])
def test_with_nothing_required_nothing_passed_suggests_not_qualified(results):
    outcome, reason = suggest_with_reason(
        [_standing(f"c{i}", r) for i, r in enumerate(results)]
    )
    assert outcome is Q.NOT_QUALIFIED
    assert reason == "No criterion has passed yet"


def test_a_result_against_an_older_version_does_not_count():
    outcome, _ = suggest_with_reason([_standing("deal_size", R.PASS, counts=False)])
    assert outcome is Q.NOT_QUALIFIED


def test_an_inactive_criterion_is_ignored():
    outcome, reason = suggest_with_reason([
        _standing("deal_size", R.PASS),
        _standing("retired", R.FAIL, active=False),
    ])
    assert outcome is Q.QUALIFIED
    assert reason == "1 of 1 criteria passed, none failed"


def test_with_required_criteria_every_one_must_pass_and_optional_ones_do_not_matter():
    standings = [
        _standing("deal_size", R.PASS, required=True),
        _standing("revenue", R.PASS, required=True),
        _standing("industry", R.FAIL),
    ]
    assert suggest_with_reason(standings) == (Q.QUALIFIED, "All 2 required criteria passed")


def test_with_required_criteria_a_missing_one_is_named():
    outcome, reason = suggest_with_reason([
        _standing("deal_size", R.PASS, required=True),
        _standing("years_in_business", None, required=True),
    ])
    assert outcome is Q.NOT_QUALIFIED
    assert reason == "Required criteria not yet passed: Years in business"


def test_with_required_criteria_a_failed_one_is_named():
    outcome, reason = suggest_with_reason([
        _standing("deal_size", R.FAIL, required=True),
        _standing("revenue", None, required=True),
    ])
    assert outcome is Q.NOT_QUALIFIED
    assert reason == "Required criteria failed: Deal size"
