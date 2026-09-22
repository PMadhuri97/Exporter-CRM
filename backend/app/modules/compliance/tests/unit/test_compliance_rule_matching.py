"""The two predicates a rule's conditions are decided by — pure, no database.

Every obligation the platform imposes rests on these, so they are asserted with
plain values rather than inferred from an evaluation result: read only through
the engine, a condition that quietly matched everything would look identical to
one that matched correctly, right up until a rule was written that relied on the
difference. How the two compose into a decision about a whole rule is covered in
``test_compliance_rule_evaluation.py``.
"""
from dataclasses import dataclass
from datetime import date

from app.modules.compliance.domain.policies.rule_matching import (
    ComplianceFacts,
    amount_against_threshold,
    matches_condition,
    matches_threshold,
)


@dataclass(frozen=True)
class _Rule:
    """Only the members ``amount_against_threshold`` reads."""

    amount_threshold_minor: int | None
    threshold_asset_code: str | None


def _rule(*, amount_threshold_minor: int | None, threshold_asset_code: str | None) -> _Rule:
    return _Rule(
        amount_threshold_minor=amount_threshold_minor,
        threshold_asset_code=threshold_asset_code,
    )


def _facts(send_asset_code: str, send_amount_minor: int) -> ComplianceFacts:
    return ComplianceFacts(
        send_amount_minor=send_amount_minor,
        send_asset_code=send_asset_code,
        as_of_date=date(2026, 8, 4),
    )

# ── matches_condition ─────────────────────────────────────────────────────────

def test_an_unset_condition_matches_a_known_fact():
    assert matches_condition(None, "US_IN")


def test_an_unset_condition_matches_an_unknown_fact():
    """A rule that does not mention the corridor is indifferent to whether one
    was established, so an unset condition cannot be the thing that stops it."""
    assert matches_condition(None, None)


def test_a_condition_matches_an_equal_fact():
    assert matches_condition("US_IN", "US_IN")


def test_a_condition_does_not_match_a_different_fact():
    assert not matches_condition("US_IN", "EUR_IN")


def test_a_condition_does_not_match_an_unknown_fact():
    """The safe direction: a rule written for one corridor must not attach its
    obligation to a settlement whose corridor was never established."""
    assert not matches_condition("US_IN", None)


def test_a_condition_does_not_match_on_case_alone():
    assert not matches_condition("US_IN", "us_in")


def test_a_condition_does_not_match_a_padded_fact():
    assert not matches_condition("US_IN", " US_IN ")


# ── matches_threshold ─────────────────────────────────────────────────────────

def test_no_threshold_matches_any_amount():
    assert matches_threshold(None, 0)
    assert matches_threshold(None, 10**12)


def test_an_amount_at_the_threshold_matches():
    """The bound is inclusive, so the figure a regulator publishes is the figure
    that triggers the obligation rather than the one above it."""
    assert matches_threshold(5_000_000, 5_000_000)


def test_an_amount_above_the_threshold_matches():
    assert matches_threshold(5_000_000, 5_000_001)


def test_an_amount_below_the_threshold_does_not_match():
    assert not matches_threshold(5_000_000, 4_999_999)


def test_an_amount_that_could_not_be_established_matches():
    """The fail-safe. A rate lookup that failed leaves the settlement's value in
    the rule's currency unknown, and an unknown value satisfies the threshold
    rather than failing it: the alternative silently excuses a payment from the
    review it exists to receive, and records nothing about having done so."""
    assert matches_threshold(5_000_000, None)


def test_the_fail_safe_does_not_reach_rules_without_a_threshold():
    """A rule with no threshold is unconstrained by amount either way, so the
    unknown amount changes nothing about it."""
    assert matches_threshold(None, None)


# ── amount_against_threshold ──────────────────────────────────────────────────

def test_a_threshold_in_the_settlements_own_currency_needs_no_conversion():
    rule = _rule(amount_threshold_minor=5_000_000, threshold_asset_code="USD")

    assert amount_against_threshold(rule, _facts("USD", 7_500_000), {}) == 7_500_000


def test_a_threshold_in_another_currency_uses_the_supplied_conversion():
    rule = _rule(amount_threshold_minor=5_000_000, threshold_asset_code="INR")

    assert amount_against_threshold(rule, _facts("USD", 100), {"INR": 8_300}) == 8_300


def test_a_threshold_in_another_currency_with_no_conversion_is_unknown():
    rule = _rule(amount_threshold_minor=5_000_000, threshold_asset_code="INR")

    assert amount_against_threshold(rule, _facts("USD", 100), {}) is None
    assert amount_against_threshold(rule, _facts("USD", 100), None) is None


def test_a_rule_without_a_threshold_never_consults_a_conversion():
    rule = _rule(amount_threshold_minor=None, threshold_asset_code=None)

    assert amount_against_threshold(rule, _facts("USD", 100), None) == 100


def test_a_threshold_missing_its_asset_is_unknown():
    """ck_compliance_rule_threshold_paired makes this unrepresentable in the
    database, so it is reached only by a rule built in memory. It resolves to
    unknown, which the fail-safe then treats as met."""
    rule = _rule(amount_threshold_minor=5_000_000, threshold_asset_code=None)

    assert amount_against_threshold(rule, _facts("USD", 100), {"USD": 100}) is None
