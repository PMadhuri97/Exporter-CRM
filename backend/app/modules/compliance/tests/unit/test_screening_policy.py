from __future__ import annotations

import pytest

from app.modules.compliance.domain.entities.compliance import ScreeningStatus
from app.modules.compliance.domain.policies import screening
from app.modules.compliance.domain.policies.screening import score_aml_risk
from app.modules.customers import RiskRating

LARGE_AMOUNT = 6_000_000
SMALL_AMOUNT = 100_00


# ── the surviving decision: customer risk rating ──────────────────────────────


@pytest.mark.parametrize("rating", [RiskRating.HIGH, RiskRating.ENHANCED])
def test_an_elevated_customer_rating_requires_review(rating):
    status, payload = score_aml_risk(rating, SMALL_AMOUNT, "USD")

    assert status is ScreeningStatus.MANUAL_REVIEW
    assert payload["manual_review"] is True
    assert f"Customer risk rating is {rating.value}" in payload["reasons"]


@pytest.mark.parametrize("rating", [RiskRating.LOW, RiskRating.MEDIUM])
def test_an_ordinary_customer_rating_passes(rating):
    status, payload = score_aml_risk(rating, SMALL_AMOUNT, "USD")

    assert status is ScreeningStatus.PASS
    assert payload["manual_review"] is False
    assert payload["reasons"] == []


# ── the removed decision: amount is no longer judged here ─────────────────────


def test_a_large_amount_alone_no_longer_triggers_review():
    status, payload = score_aml_risk(RiskRating.LOW, LARGE_AMOUNT, "USD")

    assert status is ScreeningStatus.PASS
    assert payload["reasons"] == []


def test_the_registry_verdict_is_what_triggers_a_value_review():
    """The same large amount, this time with the registry having decided."""
    status, payload = score_aml_risk(
        RiskRating.LOW,
        LARGE_AMOUNT,
        "USD",
        registry_reasons=("Transaction value above large-value review threshold.",),
        registry_rule_ids=("LARGE_VALUE_REVIEW",),
    )

    assert status is ScreeningStatus.MANUAL_REVIEW
    assert payload["reasons"] == ["Transaction value above large-value review threshold."]
    assert payload["rule_ids"] == ["LARGE_VALUE_REVIEW"]


def test_both_grounds_are_reported_separately():
    """A rating and a rule are independent reasons and neither hides the other."""
    _, payload = score_aml_risk(
        RiskRating.HIGH,
        LARGE_AMOUNT,
        "USD",
        registry_reasons=("Above threshold.",),
        registry_rule_ids=("LARGE_VALUE_REVIEW",),
    )

    assert payload["reasons"] == ["Customer risk rating is HIGH", "Above threshold."]


def test_the_amount_is_still_reported_even_though_it_is_not_judged():
    """A reviewer needs to see what was screened."""
    _, payload = score_aml_risk(RiskRating.LOW, LARGE_AMOUNT, "USD")

    assert payload["amount"] == "60000.00"


def test_the_amount_is_scaled_by_its_own_currency():
    _, payload = score_aml_risk(RiskRating.LOW, SMALL_AMOUNT, "INR")

    assert payload["amount"] == "100.00"


# ── regression guards ─────────────────────────────────────────────────────────


def test_the_module_declares_no_threshold():
    import inspect
    import re

    source = inspect.getsource(screening)
    # Strip the docstrings, which legitimately *describe* the removed threshold.
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)
    literals = re.findall(r"\b\d{4,}\b", code)

    assert literals == [], f"screening policy contains threshold-sized literals: {literals}"


def test_the_module_no_longer_decides_designations():
    assert not hasattr(screening, "DNFBP_LABEL")
    assert not hasattr(screening, "requires_enhanced_due_diligence")


def test_the_policy_names_no_sector():
    offenders = [
        name
        for name in dir(screening)
        if name.isupper() and isinstance(getattr(screening, name), frozenset | set | list | tuple)
    ]

    assert offenders == [], (
        f"screening policy declares sector collections {offenders}; sector "
        f"designations belong in the registry, not in code"
    )
