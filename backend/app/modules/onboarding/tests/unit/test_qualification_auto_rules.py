"""The rules an automatic qualification answer follows."""

from __future__ import annotations

from decimal import Decimal

from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionResultValue,
    ThresholdComparison,
)
from app.modules.onboarding.domain.qualification_auto import (
    allowed_result,
    incorporation_year,
    threshold_result,
)


def test_the_incorporation_year_is_read_from_a_cin():
    assert incorporation_year("U12345MH2010PTC123456") == 2010
    assert incorporation_year("l74999dl1995plc067890") == 1995
    assert incorporation_year("not a cin") is None
    assert incorporation_year(None) is None


def test_a_threshold_passes_or_fails_and_says_nothing_without_a_value():
    at_least_3 = (ThresholdComparison.AT_LEAST, Decimal(3))
    assert threshold_result(5, *at_least_3) is CriterionResultValue.PASS
    assert threshold_result(2, *at_least_3) is CriterionResultValue.FAIL
    assert threshold_result(None, *at_least_3) is None
    assert threshold_result(10, ThresholdComparison.AT_MOST, Decimal(5)) is CriterionResultValue.FAIL


def test_allowed_values_ignore_case_and_spacing_and_any_one_passes():
    assert allowed_result(["  textiles "], ["Textiles"]) is CriterionResultValue.PASS
    assert allowed_result(["US", "DE"], ["de"]) is CriterionResultValue.PASS
    assert allowed_result(["Mining"], ["Textiles"]) is CriterionResultValue.FAIL
    assert allowed_result([None, ""], ["Textiles"]) is None
