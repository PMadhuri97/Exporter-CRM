from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import yaml

from app.modules.compliance.domain.entities.compliance_rule import RequiredAction
from app.modules.compliance.domain.entities.registry import PurposeCategory
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import SEED_DATA_DIR
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    SEED_DATA_DIR as SECTOR_SEED_DATA_DIR,
)
from app.shared.value_objects import to_minor_units

DNFBP_RULE = "DNFBP_EDD_REQUIRED"
LARGE_VALUE_RULE = "LARGE_VALUE_REVIEW"

MATCH_FIELDS = (
    "corridor_match",
    "sector_risk_tier_match",
    "sector_classification_label_match",
    "purpose_code_category_match",
    "amount_threshold",
    "amount_threshold_currency",
)


@pytest.fixture(scope="module")
def rules() -> list[dict]:
    return yaml.safe_load((SEED_DATA_DIR / "compliance-rules.yaml").read_text()) or []


@pytest.fixture(scope="module")
def by_id(rules: list[dict]) -> dict[str, dict]:
    return {rule["rule_id"]: rule for rule in rules}


# ── the Walk-phase rule set ───────────────────────────────────────────────────


def test_both_walk_phase_rules_are_present(by_id: dict[str, dict]):
    assert DNFBP_RULE in by_id
    assert LARGE_VALUE_RULE in by_id


def test_the_walk_phase_defines_exactly_these_two_rules(rules: list[dict]):
    """A third rule arriving unreviewed would impose an obligation nobody signed
    off. Widen this assertion deliberately when the rule set grows."""
    assert len(rules) == 2


def test_rule_ids_are_unique(rules: list[dict]):
    """uq_compliance_rule_rule_id would reject a duplicate at load time, but the
    failure surfaces as a boot crash rather than as a reviewable diff."""
    ids = [rule["rule_id"] for rule in rules]
    assert sorted(ids) == sorted(set(ids))


# ── every rule ────────────────────────────────────────────────────────────────


def test_every_rule_declares_the_required_fields(rules: list[dict]):
    for rule in rules:
        for field in ("rule_id", "description", "required_action", "action_reason"):
            assert rule.get(field), f"{rule.get('rule_id')} is missing {field}"


def test_every_required_action_is_a_known_action(rules: list[dict]):
    for rule in rules:
        assert RequiredAction(rule["required_action"])


def test_every_risk_tier_is_a_known_tier(rules: list[dict]):
    for rule in rules:
        tier = rule.get("sector_risk_tier_match")
        if tier is not None:
            assert RiskTier(tier)


def test_every_rule_constrains_something(rules: list[dict]):
    for rule in rules:
        assert any(rule.get(field) is not None for field in MATCH_FIELDS), (
            f"{rule['rule_id']} sets no match condition and would fire on every settlement"
        )


def test_every_threshold_is_paired_with_a_currency(rules: list[dict]):
    for rule in rules:
        has_amount = rule.get("amount_threshold") is not None
        has_currency = rule.get("amount_threshold_currency") is not None
        assert has_amount == has_currency, f"{rule['rule_id']} has a half-declared threshold"


def test_every_threshold_is_positive(rules: list[dict]):
    for rule in rules:
        amount = rule.get("amount_threshold")
        if amount is not None:
            assert isinstance(amount, int) and amount > 0


def test_every_rule_is_effective_dated(rules: list[dict]):
    for rule in rules:
        assert isinstance(rule.get("effective_from"), date)


def test_no_rule_closes_before_it_opens(rules: list[dict]):
    for rule in rules:
        effective_to = rule.get("effective_to")
        if effective_to is not None:
            assert effective_to > rule["effective_from"]


def test_every_action_reason_is_written_for_a_regulator(rules: list[dict]):
    for rule in rules:
        reason = rule["action_reason"]
        assert len(reason) > 30, f"{rule['rule_id']} has a stub action_reason"
        assert reason.strip() == reason


def test_every_purpose_category_is_a_known_category(rules: list[dict]):
    """The loader now rejects an unknown category at boot; this fails in review."""
    for rule in rules:
        category = rule.get("purpose_code_category_match")
        if category is not None:
            assert PurposeCategory(category)


def test_every_classification_label_is_one_the_sector_registry_publishes(rules: list[dict]):
    classifications = (
        yaml.safe_load((SECTOR_SEED_DATA_DIR / "risk-classifications.yaml").read_text()) or []
    )
    published = {
        row["classification_label"]
        for row in classifications
        if row.get("classification_label") is not None
    }
    for rule in rules:
        label = rule.get("sector_classification_label_match")
        if label is not None:
            assert label in published, (
                f"{rule['rule_id']} matches on classification_label {label!r}, which no "
                f"sector in risk-classifications.yaml carries — the rule can never fire. "
                f"Published labels: {sorted(published)}"
            )


def test_no_rule_matches_on_a_corridor_yet(rules: list[dict]):
    for rule in rules:
        assert rule.get("corridor_match") is None, (
            f"{rule['rule_id']} sets corridor_match, which no registry validates"
        )


# ── DNFBP_EDD_REQUIRED ────────────────────────────────────────────────────────


def test_the_dnfbp_rule_requires_edd(by_id: dict[str, dict]):
    assert by_id[DNFBP_RULE]["required_action"] == RequiredAction.EDD_REQUIRED.value


def test_the_dnfbp_rule_matches_on_the_registry_label(by_id: dict[str, dict]):
    rule = by_id[DNFBP_RULE]
    assert rule["sector_classification_label_match"] == "DNFBP"
    assert rule.get("corridor_match") is None, "the DNFBP designation is not corridor-specific"


def test_the_dnfbp_rule_requires_both_a_high_tier_and_the_label(by_id: dict[str, dict]):
    """The ticket specifies both conditions, so a sector carrying the label at a
    lower tier does not fire this rule. Widening it is a change to the YAML, not
    to the evaluator."""
    rule = by_id[DNFBP_RULE]
    assert rule["sector_risk_tier_match"] == "high"
    assert rule["sector_classification_label_match"] == "DNFBP"


def test_the_dnfbp_rule_sets_no_amount_threshold(by_id: dict[str, dict]):
    assert by_id[DNFBP_RULE].get("amount_threshold") is None


def test_the_walk_rules_carry_the_action_reasons_the_ticket_specifies(by_id: dict[str, dict]):
    """The reason is what a regulator is shown. It is specified verbatim in the
    ticket, so it is asserted verbatim here rather than checked for plausibility."""
    assert by_id[DNFBP_RULE]["action_reason"] == (
        "FATF DNFBP classification requires enhanced due diligence before settlement proceeds."
    )
    assert by_id[LARGE_VALUE_RULE]["action_reason"] == (
        "Transaction value above large-value review threshold when converted to USD."
    )


# ── LARGE_VALUE_REVIEW ────────────────────────────────────────────────────────


def test_the_large_value_rule_requires_manual_review(by_id: dict[str, dict]):
    assert by_id[LARGE_VALUE_RULE]["required_action"] == RequiredAction.MANUAL_REVIEW.value


def test_the_large_value_threshold_is_fifty_thousand_usd(by_id: dict[str, dict]):
    rule = by_id[LARGE_VALUE_RULE]
    assert rule["amount_threshold_currency"] == "USD"
    assert rule["amount_threshold"] == to_minor_units(Decimal("50000"), "USD")


def test_the_large_value_rule_applies_to_every_sector(by_id: dict[str, dict]):
    rule = by_id[LARGE_VALUE_RULE]
    assert rule.get("sector_risk_tier_match") is None
    assert rule.get("sector_classification_label_match") is None
