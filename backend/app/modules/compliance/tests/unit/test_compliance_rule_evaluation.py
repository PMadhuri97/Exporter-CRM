from __future__ import annotations

import ast
import dataclasses
import enum
import pathlib
from dataclasses import dataclass
from datetime import date, datetime

import pytest

from app.modules.compliance.application.rule_engine import (
    NO_ACTIONS,
    FiredAction,
    evaluate_compliance_rules,
)
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.required_action import RequiredAction

EPOCH = date(2024, 1, 1)
AS_OF = date(2026, 8, 3)

DNFBP_LABEL = "DNFBP"
HIGH_TIER = "high"

#: Fifty thousand dollars, in the integer minor units the send amount is carried in.
LARGE_VALUE_THRESHOLD_MINOR = 5_000_000


@dataclass(frozen=True)
class Rule:
    """A compliance rule with every condition unset unless a test sets it.

    Frozen, because the engine only ever reads a rule and several of these are
    shared between tests.
    """

    rule_id: str
    priority: int = 10
    sector_risk_tier: str | None = None
    classification_label: str | None = None
    purpose_code: str | None = None
    corridor_id: str | None = None
    amount_threshold_minor: int | None = None
    threshold_asset_code: str | None = None
    # One action per rule, as the registry stores it. A test rule that imposed
    # several would be a shape the compliance_rule table cannot produce.
    required_action: RequiredAction = RequiredAction.MANUAL_REVIEW
    reason: str = "the rule fired"
    effective_from: date = EPOCH
    effective_to: date | None = None


def facts(**overrides) -> ComplianceFacts:
    """A settlement that satisfies nothing in particular."""
    return ComplianceFacts(
        **{
            "send_amount_minor": 100_000,
            "send_asset_code": "USD",
            "as_of_date": AS_OF,
            **overrides,
        }
    )


DNFBP_EDD_REQUIRED = Rule(
    rule_id="DNFBP_EDD_REQUIRED",
    priority=10,
    sector_risk_tier=HIGH_TIER,
    classification_label=DNFBP_LABEL,
    required_action=RequiredAction.EDD_REQUIRED,
    reason="the sector is designated a non-financial business or profession",
)

LARGE_VALUE_REVIEW = Rule(
    rule_id="LARGE_VALUE_REVIEW",
    priority=20,
    amount_threshold_minor=LARGE_VALUE_THRESHOLD_MINOR,
    threshold_asset_code="USD",
    required_action=RequiredAction.MANUAL_REVIEW,
    reason="the amount reaches the review threshold",
)


# ── Nothing fires ─────────────────────────────────────────────────────────────

def test_an_empty_registry_imposes_no_obligations():
    assert evaluate_compliance_rules(facts(), []) == NO_ACTIONS


def test_a_rule_whose_condition_fails_imposes_no_obligations():
    result = evaluate_compliance_rules(facts(sector_risk_tier="standard"), [DNFBP_EDD_REQUIRED])

    assert result == NO_ACTIONS
    assert result.rule_ids == ()


# ── One condition at a time ───────────────────────────────────────────────────

def test_a_rule_matching_on_risk_tier_fires():
    rule = Rule(rule_id="TIER", sector_risk_tier=HIGH_TIER, required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(sector_risk_tier=HIGH_TIER), [rule])

    assert result.rule_ids == ("TIER",)


def test_a_rule_matching_on_classification_label_fires():
    rule = Rule(rule_id="LABEL", classification_label=DNFBP_LABEL, required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(classification_label=DNFBP_LABEL), [rule])

    assert result.rule_ids == ("LABEL",)


def test_a_rule_matching_on_purpose_code_fires():
    rule = Rule(rule_id="PURPOSE", purpose_code="TRADE_GOODS_IMPORT", required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(purpose_code="TRADE_GOODS_IMPORT"), [rule])

    assert result.rule_ids == ("PURPOSE",)


def test_a_rule_matching_on_corridor_fires():
    rule = Rule(rule_id="CORRIDOR", corridor_id="US_IN", required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(corridor_id="US_IN"), [rule])

    assert result.rule_ids == ("CORRIDOR",)


def test_conditions_are_compared_exactly():
    """The registry settles casing where the rules are held. Re-casing here
    would have to know which identifiers are upper case and which are not."""
    rule = Rule(rule_id="CORRIDOR", corridor_id="US_IN", required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(corridor_id="us_in"), [rule]) == NO_ACTIONS


def test_a_condition_matches_a_string_enum_fact_by_value():
    class Tier(str, enum.Enum):
        HIGH = "high"

    rule = Rule(rule_id="TIER", sector_risk_tier=HIGH_TIER, required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(sector_risk_tier=Tier.HIGH), [rule]).requires(RequiredAction.MANUAL_REVIEW)


# ── Unset conditions and unknown facts ────────────────────────────────────────

def test_a_rule_with_no_conditions_fires_on_every_settlement():
    rule = Rule(rule_id="ALWAYS", required_action=RequiredAction.ENHANCED_MONITORING)

    assert evaluate_compliance_rules(facts(), [rule]).requires(RequiredAction.ENHANCED_MONITORING)


def test_an_unset_condition_ignores_the_fact_it_would_have_matched():
    """A rule that says nothing about the corridor fires whatever the corridor
    is, including one it would never have been written for."""
    rule = Rule(rule_id="ANY_CORRIDOR", sector_risk_tier=HIGH_TIER, required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, corridor_id="XX_YY"), [rule]
    )

    assert result.rule_ids == ("ANY_CORRIDOR",)


def test_a_set_condition_does_not_match_an_unknown_fact():
    """The safe direction. A rule written for one corridor must not fire on a
    settlement whose corridor has not been established — the alternative is a
    regulatory obligation attached to a payment that never earned it."""
    rule = Rule(rule_id="CORRIDOR", corridor_id="US_IN", required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(corridor_id=None), [rule]) == NO_ACTIONS


def test_every_condition_must_hold_for_a_rule_to_fire():
    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, classification_label="OTHER"), [DNFBP_EDD_REQUIRED]
    )

    assert result == NO_ACTIONS


# ── Thresholds ────────────────────────────────────────────────────────────────

def test_an_amount_at_the_threshold_fires():
    """The bound is inclusive, so the figure a regulator publishes is the figure
    that triggers the obligation rather than the one just below it."""
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR), [LARGE_VALUE_REVIEW]
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)


def test_an_amount_one_minor_unit_below_the_threshold_does_not_fire():
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR - 1), [LARGE_VALUE_REVIEW]
    )

    assert result == NO_ACTIONS


def test_an_amount_well_above_the_threshold_fires():
    """The threshold is a floor, not a band. Everything above it is caught."""
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR * 100), [LARGE_VALUE_REVIEW]
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)


def test_a_threshold_is_one_condition_among_the_others():
    rule = Rule(
        rule_id="LARGE_ON_ONE_CORRIDOR",
        corridor_id="US_IN",
        amount_threshold_minor=LARGE_VALUE_THRESHOLD_MINOR,
        threshold_asset_code="USD",
        required_action=RequiredAction.MANUAL_REVIEW,
    )
    large = {"send_amount_minor": LARGE_VALUE_THRESHOLD_MINOR}

    assert evaluate_compliance_rules(facts(corridor_id="US_IN", **large), [rule]).requires(RequiredAction.MANUAL_REVIEW)
    assert evaluate_compliance_rules(facts(corridor_id="EUR_IN", **large), [rule]) == NO_ACTIONS
    assert evaluate_compliance_rules(facts(corridor_id="US_IN"), [rule]) == NO_ACTIONS


def test_a_zero_amount_fires_no_threshold_rule():
    rule = Rule(
        rule_id="ANY_VALUE",
        amount_threshold_minor=1,
        threshold_asset_code="USD",
        required_action=RequiredAction.MANUAL_REVIEW,
    )

    assert evaluate_compliance_rules(facts(send_amount_minor=0), [rule]) == NO_ACTIONS


def test_a_threshold_in_another_asset_is_compared_against_the_converted_amount():
    """5,000,000 minor units is fifty thousand dollars under one asset and fifty
    thousand rupees under another, so the settlement is valued in the rule's
    currency before the integers are compared. Obtaining the rate is the
    caller's job; here it is supplied."""
    below = evaluate_compliance_rules(
        facts(send_amount_minor=10**12, send_asset_code="INR"),
        [LARGE_VALUE_REVIEW],
        {"USD": LARGE_VALUE_THRESHOLD_MINOR - 1},
    )
    at = evaluate_compliance_rules(
        facts(send_amount_minor=10**12, send_asset_code="INR"),
        [LARGE_VALUE_REVIEW],
        {"USD": LARGE_VALUE_THRESHOLD_MINOR},
    )

    assert below == NO_ACTIONS
    assert at.requires(RequiredAction.MANUAL_REVIEW)


def test_a_threshold_in_another_asset_fires_when_the_amount_cannot_be_converted():
    """The fail-safe: with no conversion supplied the settlement's value in the
    rule's currency is unknown, and an unknown value escalates rather than
    quietly excusing the payment from review."""
    result = evaluate_compliance_rules(
        facts(send_amount_minor=1, send_asset_code="INR"),
        [LARGE_VALUE_REVIEW],
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)


def test_a_conversion_is_ignored_for_a_settlement_already_in_the_rules_currency():
    """A supplied conversion must not override the settlement's own amount, or a
    stale rate would decide a comparison that needed no rate at all."""
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR - 1, send_asset_code="USD"),
        [LARGE_VALUE_REVIEW],
        {"USD": 10**12},
    )

    assert result == NO_ACTIONS


def test_a_rule_without_a_threshold_fires_at_any_amount():
    rule = Rule(rule_id="ANY_AMOUNT", required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(send_amount_minor=1), [rule]).requires(RequiredAction.MANUAL_REVIEW)


def test_a_threshold_missing_its_asset_fires_under_the_fail_safe():
    """A quantity with no asset names no currency to value the settlement in, so
    it resolves to unknown and the fail-safe escalates.

    ck_compliance_rule_threshold_paired makes this unrepresentable in the
    database; the case survives here because the evaluator is handed rules by a
    caller, not only by the registry."""
    rule = Rule(
        rule_id="NO_ASSET",
        amount_threshold_minor=1,
        threshold_asset_code=None,
        required_action=RequiredAction.MANUAL_REVIEW,
    )

    assert evaluate_compliance_rules(facts(), [rule]).requires(RequiredAction.MANUAL_REVIEW)


# ── Effectivity ───────────────────────────────────────────────────────────────

def test_a_rule_fires_on_its_effective_from():
    rule = Rule(rule_id="STARTS", effective_from=AS_OF, required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(), [rule]).requires(RequiredAction.MANUAL_REVIEW)


def test_a_rule_does_not_fire_before_its_effective_from():
    rule = Rule(rule_id="NOT_YET", effective_from=date(2026, 8, 4), required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(), [rule]) == NO_ACTIONS


def test_a_rule_does_not_fire_on_its_effective_to():
    """The window is half-open, so a rule and its successor can abut on the
    changeover date without both being in force that day."""
    rule = Rule(rule_id="RETIRED", effective_to=AS_OF, required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(), [rule]) == NO_ACTIONS


def test_a_rule_without_an_end_date_fires_indefinitely():
    rule = Rule(rule_id="OPEN_ENDED", required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(as_of_date=date(2099, 1, 1)), [rule]).requires(RequiredAction.MANUAL_REVIEW)


def test_a_rule_that_expired_long_ago_does_not_fire():
    """Distinct from the boundary above: a rule withdrawn years earlier must not
    keep governing settlements raised since."""
    rule = Rule(
        rule_id="WITHDRAWN",
        effective_from=date(2020, 1, 1),
        effective_to=date(2021, 1, 1),
        required_action=RequiredAction.MANUAL_REVIEW,
    )

    assert evaluate_compliance_rules(facts(), [rule]) == NO_ACTIONS


def test_a_rule_starting_far_in_the_future_does_not_fire():
    rule = Rule(rule_id="ANNOUNCED", effective_from=date(2099, 1, 1), required_action=RequiredAction.MANUAL_REVIEW)

    assert evaluate_compliance_rules(facts(), [rule]) == NO_ACTIONS


def test_effectivity_gates_a_rule_whose_conditions_all_hold():
    """A rule out of force is out of force however well it otherwise fits, so
    effectivity cannot be treated as one condition among the others."""
    rule = Rule(rule_id="LAPSED", corridor_id="US_IN", effective_to=date(2025, 1, 1))

    assert evaluate_compliance_rules(facts(corridor_id="US_IN"), [rule]) == NO_ACTIONS


def test_a_rule_whose_window_closes_before_it_opens_never_fires():
    """An inverted window describes no dates at all, so it fires on none of
    them. Nothing in the engine has to recognise the row as malformed for the
    settlement in front of it to be handled correctly."""
    rule = Rule(
        rule_id="INVERTED",
        effective_from=date(2026, 1, 1),
        effective_to=date(2024, 1, 1),
        required_action=RequiredAction.MANUAL_REVIEW,
    )

    for on in (date(2023, 1, 1), date(2025, 1, 1), date(2027, 1, 1)):
        assert evaluate_compliance_rules(facts(as_of_date=on), [rule]) == NO_ACTIONS


def test_a_retired_rule_still_governs_a_settlement_raised_while_it_was_in_force():
    """Effectivity is judged on the settlement's own date. Re-running an
    evaluation years later must reach the answer the payment was given at the
    time, not the answer today's registry would give."""
    rule = Rule(
        rule_id="SUPERSEDED",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 1, 1),
        required_action=RequiredAction.MANUAL_REVIEW,
    )

    assert evaluate_compliance_rules(facts(as_of_date=date(2024, 6, 1)), [rule]).requires(RequiredAction.MANUAL_REVIEW)


# ── Several rules at once ─────────────────────────────────────────────────────

def test_actions_are_the_union_of_every_firing_rule():
    result = evaluate_compliance_rules(
        facts(
            sector_risk_tier=HIGH_TIER,
            classification_label=DNFBP_LABEL,
            send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR,
        ),
        [DNFBP_EDD_REQUIRED, LARGE_VALUE_REVIEW],
    )

    assert result.edd_required
    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert result.rule_ids == ("DNFBP_EDD_REQUIRED", "LARGE_VALUE_REVIEW")


def test_a_later_rule_cannot_withdraw_an_obligation():
    """Actions are asserted, never cleared. A rule that imposes nothing must not
    undo one that imposed something."""
    silent = Rule(rule_id="ZZ_SILENT", priority=99, required_action=RequiredAction.ENHANCED_MONITORING)

    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, classification_label=DNFBP_LABEL),
        [DNFBP_EDD_REQUIRED, silent],
    )

    assert result.edd_required
    assert result.requires(RequiredAction.ENHANCED_MONITORING)


def test_two_rules_requiring_the_same_action_impose_it_once():
    first = Rule(rule_id="A_MONITOR", required_action=RequiredAction.ENHANCED_MONITORING)
    second = Rule(rule_id="B_MONITOR", required_action=RequiredAction.ENHANCED_MONITORING)

    result = evaluate_compliance_rules(facts(), [first, second])

    assert result.requires(RequiredAction.ENHANCED_MONITORING)
    assert result.rule_ids == ("A_MONITOR", "B_MONITOR")


def test_every_declared_action_can_fire():
    """All four of the ticket's actions are representable end to end.

    One rule imposes one action, so imposing four takes four rules — which is
    the shape the registry actually stores. A member of RequiredAction that the
    action set could not carry would fail here rather than at the point some
    rule is written to use it.
    """
    rules = [
        Rule(rule_id=f"R_{action.name}", required_action=action) for action in RequiredAction
    ]

    result = evaluate_compliance_rules(facts(), rules)

    assert set(result.required_actions) == set(RequiredAction)
    for action in RequiredAction:
        assert result.requires(action)
        assert result.rules_for(action) == (f"R_{action.name}",)


def test_an_action_carries_the_rule_and_the_reason_that_produced_it():
    """The association the ticket asks for: a consumer looking at one obligation
    can name the rule behind it and quote the reason for it, without indexing
    into a parallel list."""
    result = evaluate_compliance_rules(
        facts(),
        [
            Rule(
                rule_id="LIMITS",
                priority=1,
                required_action=RequiredAction.ENHANCED_LIMITS_CHECK,
                reason="limits must be re-checked",
            ),
            Rule(
                rule_id="REVIEW",
                priority=2,
                required_action=RequiredAction.MANUAL_REVIEW,
                reason="a human must look at this",
            ),
        ],
    )

    assert result.fired == (
        FiredAction(RequiredAction.ENHANCED_LIMITS_CHECK, "LIMITS", "limits must be re-checked"),
        FiredAction(RequiredAction.MANUAL_REVIEW, "REVIEW", "a human must look at this"),
    )
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == ("REVIEW",)
    assert result.reasons_for(RequiredAction.MANUAL_REVIEW) == ("a human must look at this",)
    assert result.rules_for(RequiredAction.ENHANCED_LIMITS_CHECK) == ("LIMITS",)
    assert result.reasons_for(RequiredAction.ENHANCED_LIMITS_CHECK) == (
        "limits must be re-checked",
    )


def test_an_action_required_by_two_rules_names_both():
    """A distinct action, but not a lost rule: both rules that imposed it are
    recoverable, which a set of booleans could never express."""
    result = evaluate_compliance_rules(
        facts(),
        [
            Rule(rule_id="A_REVIEW", priority=1, reason="first"),
            Rule(rule_id="B_REVIEW", priority=2, reason="second"),
        ],
    )

    assert result.required_actions == (RequiredAction.MANUAL_REVIEW,)
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == ("A_REVIEW", "B_REVIEW")
    assert result.reasons_for(RequiredAction.MANUAL_REVIEW) == ("first", "second")


def test_separate_rules_contributing_one_action_each_combine():
    """The obligations a settlement carries are assembled from the whole
    registry, not read off whichever rule happened to be considered first."""
    result = evaluate_compliance_rules(
        facts(),
        [
            Rule(rule_id="C_MONITOR", priority=30, required_action=RequiredAction.ENHANCED_MONITORING),
            Rule(rule_id="A_EDD", priority=10, required_action=RequiredAction.EDD_REQUIRED),
            Rule(rule_id="B_REVIEW", priority=20, required_action=RequiredAction.MANUAL_REVIEW),
        ],
    )

    assert result.edd_required
    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert result.requires(RequiredAction.ENHANCED_MONITORING)
    assert result.rule_ids == ("A_EDD", "B_REVIEW", "C_MONITOR")


def test_a_reason_is_collected_from_every_firing_rule():
    result = evaluate_compliance_rules(
        facts(),
        [
            Rule(rule_id="A_RULE", priority=1, required_action=RequiredAction.MANUAL_REVIEW, reason="the first reason"),
            Rule(rule_id="B_RULE", priority=2, required_action=RequiredAction.MANUAL_REVIEW, reason="the second reason"),
            Rule(rule_id="C_RULE", priority=3, required_action=RequiredAction.MANUAL_REVIEW, reason="the third reason"),
        ],
    )

    assert result.reasons == ("the first reason", "the second reason", "the third reason")


def test_a_reason_is_collected_only_from_rules_that_fired():
    result = evaluate_compliance_rules(
        facts(corridor_id="US_IN"),
        [
            Rule(rule_id="FIRES", priority=1, required_action=RequiredAction.MANUAL_REVIEW, reason="this one applied"),
            Rule(
                rule_id="SILENT",
                priority=2,
                corridor_id="XX_YY",
                required_action=RequiredAction.MANUAL_REVIEW,
                reason="this one did not",
            ),
        ],
    )

    assert result.reasons == ("this one applied",)


# ── Determinism ───────────────────────────────────────────────────────────────

def test_firing_rules_are_reported_in_priority_order():
    low = Rule(rule_id="LAST", priority=90, required_action=RequiredAction.MANUAL_REVIEW)
    high = Rule(rule_id="FIRST", priority=1, required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(), [low, high])

    assert result.rule_ids == ("FIRST", "LAST")


def test_rules_sharing_a_priority_are_ordered_by_rule_id():
    """Priority alone leaves ties, and a tie broken by row order would make the
    trigger rule depend on how the registry happened to be read."""
    second = Rule(rule_id="B_RULE", priority=10, required_action=RequiredAction.MANUAL_REVIEW)
    first = Rule(rule_id="A_RULE", priority=10, required_action=RequiredAction.MANUAL_REVIEW)

    result = evaluate_compliance_rules(facts(), [second, first])

    assert result.rule_ids == ("A_RULE", "B_RULE")


def test_reasons_are_positional_against_rule_ids():
    first = Rule(rule_id="A_RULE", priority=1, required_action=RequiredAction.MANUAL_REVIEW, reason="the first reason")
    second = Rule(rule_id="B_RULE", priority=2, required_action=RequiredAction.MANUAL_REVIEW, reason="the second reason")

    result = evaluate_compliance_rules(facts(), [second, first])

    assert result.rule_ids == ("A_RULE", "B_RULE")
    assert result.reasons == ("the first reason", "the second reason")


def test_the_order_rules_are_supplied_in_does_not_change_the_result():
    given = facts(
        sector_risk_tier=HIGH_TIER,
        classification_label=DNFBP_LABEL,
        send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR,
    )
    registry = [DNFBP_EDD_REQUIRED, LARGE_VALUE_REVIEW]

    assert evaluate_compliance_rules(given, registry) == evaluate_compliance_rules(
        given, list(reversed(registry))
    )


def test_evaluating_the_same_settlement_twice_gives_the_same_answer():
    given = facts(sector_risk_tier=HIGH_TIER, classification_label=DNFBP_LABEL)

    first = evaluate_compliance_rules(given, [DNFBP_EDD_REQUIRED])
    second = evaluate_compliance_rules(given, [DNFBP_EDD_REQUIRED])

    assert first == second


def test_rules_supplied_as_a_generator_are_evaluated():
    """The registry is read once and consumed once, so a one-shot iterable is a
    legitimate way to supply it."""
    result = evaluate_compliance_rules(facts(), (rule for rule in [Rule("ANY", required_action=RequiredAction.MANUAL_REVIEW)]))

    assert result.rule_ids == ("ANY",)


def test_evaluation_leaves_the_rules_it_read_unchanged():
    rule = Rule(rule_id="UNTOUCHED", required_action=RequiredAction.MANUAL_REVIEW)
    before = dataclasses.asdict(rule)

    evaluate_compliance_rules(facts(), [rule])

    assert dataclasses.asdict(rule) == before


# ── The rule accountable for enhanced due diligence ───────────────────────────

def test_the_trigger_rule_is_the_first_firing_rule_that_requires_it():
    later = Rule(rule_id="ALSO_EDD", priority=50, required_action=RequiredAction.EDD_REQUIRED)

    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, classification_label=DNFBP_LABEL),
        [later, DNFBP_EDD_REQUIRED],
    )

    assert result.edd_trigger_rule == "DNFBP_EDD_REQUIRED"
    assert result.rule_ids == ("DNFBP_EDD_REQUIRED", "ALSO_EDD")


def test_two_rules_requiring_due_diligence_at_one_priority_resolve_by_rule_id():
    """Priority alone leaves the credit ambiguous when two rules share one. The
    settlement records a single trigger, so which rule is named must not depend
    on the order the registry was read in."""
    first = Rule(rule_id="A_EDD", priority=10, required_action=RequiredAction.EDD_REQUIRED)
    second = Rule(rule_id="B_EDD", priority=10, required_action=RequiredAction.EDD_REQUIRED)

    result = evaluate_compliance_rules(facts(), [second, first])

    assert result.edd_trigger_rule == "A_EDD"
    assert result.rule_ids == ("A_EDD", "B_EDD")


def test_the_trigger_rule_outranks_a_higher_priority_rule_that_does_not_require_it():
    """The first firing rule is not necessarily the one accountable for due
    diligence — only the first that actually requires it is."""
    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, classification_label=DNFBP_LABEL),
        [Rule(rule_id="EARLY_REVIEW", priority=1, required_action=RequiredAction.MANUAL_REVIEW), DNFBP_EDD_REQUIRED],
    )

    assert result.rule_ids == ("EARLY_REVIEW", "DNFBP_EDD_REQUIRED")
    assert result.edd_trigger_rule == "DNFBP_EDD_REQUIRED"


def test_a_rule_that_only_requires_manual_review_is_not_credited_as_the_trigger():
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR), [LARGE_VALUE_REVIEW]
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert not result.edd_required
    assert result.edd_trigger_rule is None


def test_no_obligation_leaves_no_trigger_rule():
    assert NO_ACTIONS.edd_required is False
    assert NO_ACTIONS.edd_trigger_rule is None


def test_edd_required_and_the_trigger_rule_cannot_disagree():
    """``settlement`` admits the two only together (ck_settlement_edd_rule_consistent).

    Previously an invariant checked at construction, which could raise inside an
    evaluation. Now they are both read off ``fired``, so disagreeing is not a
    state the type can hold — no guard, and nothing to raise.
    """
    for rules in (
        [],
        [Rule(rule_id="REVIEW")],
        [Rule(rule_id="EDD", required_action=RequiredAction.EDD_REQUIRED)],
        [
            Rule(rule_id="EDD", required_action=RequiredAction.EDD_REQUIRED),
            Rule(rule_id="REVIEW"),
        ],
    ):
        result = evaluate_compliance_rules(facts(), rules)
        assert result.edd_required == (result.edd_trigger_rule is not None)
        assert result.edd_required == bool(result.edd_trigger_rules)


def test_every_edd_rule_is_named_not_only_the_first():
    """The ticket says the settlement's trigger comes from "the rule_id(s)" that
    required EDD. Both are kept; ``edd_trigger_rule`` narrows to one only
    because settlement.edd_trigger_rule is a single column today."""
    result = evaluate_compliance_rules(
        facts(),
        [
            Rule(rule_id="B_EDD", priority=2, required_action=RequiredAction.EDD_REQUIRED),
            Rule(rule_id="A_EDD", priority=1, required_action=RequiredAction.EDD_REQUIRED),
        ],
    )

    assert result.edd_trigger_rules == ("A_EDD", "B_EDD")
    assert result.edd_trigger_rule == "A_EDD"


def test_an_action_set_is_immutable():
    result = evaluate_compliance_rules(facts(), [])

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.fired = ()  # type: ignore[misc]


# ── The facts an evaluation is answerable for ─────────────────────────────────

def test_facts_reject_a_missing_as_of_date():
    """Without the guard this reaches the date comparison and raises TypeError,
    which is reported as a platform failure rather than the malformed input it
    is."""
    with pytest.raises(ValueError):
        ComplianceFacts(
            send_amount_minor=1,
            send_asset_code="USD",
            as_of_date=None,  # type: ignore[arg-type]
        )


def test_facts_reject_a_timestamp_where_a_date_was_meant():
    """A datetime is a date by inheritance and would pass a plain isinstance
    check, then raise comparing itself to a rule's window — reported as a
    platform failure rather than the malformed input it is. Dropping a
    ``.date()`` is the ordinary way to arrive here."""
    with pytest.raises(ValueError):
        ComplianceFacts(
            send_amount_minor=1,
            send_asset_code="USD",
            as_of_date=datetime(2026, 8, 3, 12, 0),
        )


def test_facts_reject_an_empty_asset_code():
    """An amount with no asset cannot be compared to any threshold, and would
    quietly match none of them."""
    with pytest.raises(ValueError):
        ComplianceFacts(send_amount_minor=1, send_asset_code="", as_of_date=AS_OF)


def test_facts_reject_a_negative_amount():
    with pytest.raises(ValueError):
        ComplianceFacts(send_amount_minor=-1, send_asset_code="USD", as_of_date=AS_OF)


def test_facts_reject_an_amount_that_is_not_integer_minor_units():
    """A decimal amount would compare against the threshold and give an answer
    that is wrong by whatever the asset's precision is."""
    with pytest.raises(ValueError):
        ComplianceFacts(
            send_amount_minor=50_000.00,  # type: ignore[arg-type]
            send_asset_code="USD",
            as_of_date=AS_OF,
        )


def test_facts_are_immutable():
    given = facts()

    with pytest.raises(dataclasses.FrozenInstanceError):
        given.send_amount_minor = 1  # type: ignore[misc]


# ── The obligations the registry is written to impose ─────────────────────────

def test_a_designated_sector_requires_enhanced_due_diligence():
    """The designation comes from the sector registry and the obligation from
    the rule, so neither the sector nor the label is named in code."""
    result = evaluate_compliance_rules(
        facts(sector_risk_tier=HIGH_TIER, classification_label=DNFBP_LABEL),
        [DNFBP_EDD_REQUIRED, LARGE_VALUE_REVIEW],
    )

    assert result.edd_required
    assert result.edd_trigger_rule == "DNFBP_EDD_REQUIRED"
    assert not result.requires(RequiredAction.MANUAL_REVIEW)


def test_a_large_value_settlement_requires_manual_review():
    result = evaluate_compliance_rules(
        facts(send_amount_minor=LARGE_VALUE_THRESHOLD_MINOR),
        [DNFBP_EDD_REQUIRED, LARGE_VALUE_REVIEW],
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert result.edd_trigger_rule is None
    assert result.reasons == ("the amount reaches the review threshold",)


# ── The evaluation answers from its inputs alone ──────────────────────────────

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[5]

EVALUATOR = "app.modules.compliance.application.rule_engine"

#: Reaching any of these would mean an evaluation could consult something other
#: than the facts and rules it was handed, and two runs over the same settlement
#: could then disagree.
INFRASTRUCTURE = (
    "sqlalchemy",
    "fastapi",
    "starlette",
    "asyncpg",
    "psycopg2",
    "pydantic",
    "structlog",
    "yaml",
)

#: The evaluation's whole first-party reach. Adding to this is a deliberate act:
#: a module belongs here only if it is as free of the outside world as these are.
PURE_MODULES = {
    EVALUATOR,
    "app.modules.compliance.domain.policies.rule_matching",
    "app.modules.compliance.domain.policies.effectivity",
    # The action vocabulary. Added deliberately: it is a bare enum module with
    # no imports beyond the standard library, which is why the evaluator may
    # reach it and why it does not live beside the ORM model that also uses it.
    "app.modules.compliance.domain.required_action",
    # The jurisdiction pair the result carries. Also a bare dataclass/enum
    # module with no imports beyond the standard library.
    "app.modules.compliance.domain.jurisdiction",
}


def _import_closure(module: str) -> dict[str, set[str]]:
    """Every first-party module reachable from ``module``, and what each imports.

    Read from the source rather than from ``sys.modules``: importing any part of
    a module executes its package ``__init__``, which pulls in the facade and
    everything behind it. That says nothing about what the evaluation itself
    depends on, which is what these tests are about.
    """
    reached: dict[str, set[str]] = {}
    pending = [module]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        source = BACKEND_ROOT.joinpath(*current.split(".")).with_suffix(".py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        reached[current] = imported
        pending += [name for name in imported if name.startswith("app.")]
    return reached


def test_the_evaluation_imports_no_infrastructure():
    offenders = {
        module: sorted(
            name
            for name in imported
            if any(name == package or name.startswith(f"{package}.") for package in INFRASTRUCTURE)
        )
        for module, imported in _import_closure(EVALUATOR).items()
    }

    assert not {module: names for module, names in offenders.items() if names}, (
        "the evaluation reaches infrastructure. A rule decision is reproducible "
        "only while it is reached from the facts and rules it was given, and a "
        "session or a client is the one way that stops being true"
    )


def test_the_infrastructure_guard_detects_a_module_that_uses_infrastructure():
    """A guard that cannot fail proves nothing about what it guards.

    Pointed at a seed loader — which legitimately holds a session and a YAML
    parser — the same closure and the same package list must report them, so a
    silent pass above means the evaluation is clean rather than the check being
    blind.
    """
    closure = _import_closure("app.modules.compliance.infrastructure.purpose_code_seed_loader")
    reached = {name for imported in closure.values() for name in imported}

    detected = sorted(
        name
        for name in reached
        if any(name == package or name.startswith(f"{package}.") for package in INFRASTRUCTURE)
    )

    assert detected, "the guard reported nothing against a module that plainly uses infrastructure"


def test_the_evaluation_reaches_only_pure_modules():
    reached = set(_import_closure(EVALUATOR))

    assert reached == PURE_MODULES, (
        f"the evaluation's reach has changed: {sorted(reached.symmetric_difference(PURE_MODULES))}. "
        f"A repository or a service pulled in here would let an evaluation consult "
        f"the database mid-decision; if the new module is as pure as the rest, add it "
        f"to PURE_MODULES deliberately"
    )
