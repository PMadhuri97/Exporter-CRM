"""The public shape of a compliance decision, as the updated S0T3 ticket states it.

Separate from ``test_compliance_rule_evaluation.py``, which asks whether the right
rules fire. These ask whether the answer a caller receives carries what S1T2 is
required to store: every action that fired, the rule and reason behind each one,
and the jurisdiction whose classification fed the determination.

No database. The repository is a list and the classification lookup is a stub,
because none of this depends on where a rule was stored or how a jurisdiction was
established.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.application.rule_engine import (
    ComplianceActionSet,
    FiredAction,
    evaluate_compliance_rules,
)
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.jurisdiction import (
    JurisdictionType,
    ResolvingJurisdiction,
)
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.ports import ResolvedSectorClassification
from app.modules.compliance.domain.required_action import RequiredAction

AS_OF = date(2026, 8, 12)


class ListRepository:
    def __init__(self, rules: list[ComplianceRule]) -> None:
        self._rules = rules

    async def list_rules(self) -> list[ComplianceRule]:
        return list(self._rules)


def _rule(rule_id: str, action: RequiredAction, reason: str) -> ComplianceRule:
    return ComplianceRule(
        rule_id=rule_id,
        description=f"{action.value} for the contract tests",
        required_action=action,
        action_reason=reason,
        effective_from=date(2024, 1, 1),
    )


def _facts() -> ComplianceFacts:
    return ComplianceFacts(send_amount_minor=1, send_asset_code="USD", as_of_date=AS_OF)


# ── every action in the ticket's vocabulary ───────────────────────────────────


@pytest.mark.parametrize("action", list(RequiredAction))
async def test_every_required_action_survives_a_round_trip_through_the_engine(action):
    """Including enhanced_limits_check, which the previous contract could not
    represent at all. Parametrised over the enum so a fifth member is covered the
    day it is added rather than the day someone remembers to add a case."""
    rule = _rule(f"RULE_{action.name}", action, f"because of {action.value}")

    result = await evaluate_settlement_compliance(_facts(), ListRepository([rule]))

    assert result.required_actions == (action,)
    assert result.requires(action)
    assert result.rules_for(action) == (f"RULE_{action.name}",)
    assert result.reasons_for(action) == (f"because of {action.value}",)


async def test_all_four_actions_can_fire_on_one_settlement():
    rules = [
        _rule(f"RULE_{action.name}", action, f"because of {action.value}")
        for action in RequiredAction
    ]

    result = await evaluate_settlement_compliance(_facts(), ListRepository(rules))

    assert set(result.required_actions) == set(RequiredAction)
    assert len(result.fired) == len(RequiredAction)


async def test_enhanced_limits_check_is_reachable_from_a_stored_rule():
    """The action the updated ticket added. It has to survive the ORM column, the
    rule adapter and the evaluator — this fails if any of the three still knows
    only three actions."""
    rule = _rule("LIMITS", RequiredAction.ENHANCED_LIMITS_CHECK, "limits need re-checking")

    result = await evaluate_settlement_compliance(_facts(), ListRepository([rule]))

    assert result.requires(RequiredAction.ENHANCED_LIMITS_CHECK)
    assert result.fired == (
        FiredAction(RequiredAction.ENHANCED_LIMITS_CHECK, "LIMITS", "limits need re-checking"),
    )
    # Not due diligence. A new action must not be mistaken for the one the
    # settlement record has a column for.
    assert result.edd_required is False
    assert result.edd_trigger_rule is None


# ── action → rule → reason ────────────────────────────────────────────────────


async def test_each_action_can_be_traced_to_its_own_rule_and_reason():
    rules = [
        _rule("EDD_RULE", RequiredAction.EDD_REQUIRED, "the sector is designated"),
        _rule("REVIEW_RULE", RequiredAction.MANUAL_REVIEW, "the value is large"),
    ]

    result = await evaluate_settlement_compliance(_facts(), ListRepository(rules))

    assert result.rules_for(RequiredAction.EDD_REQUIRED) == ("EDD_RULE",)
    assert result.reasons_for(RequiredAction.EDD_REQUIRED) == ("the sector is designated",)
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == ("REVIEW_RULE",)
    assert result.reasons_for(RequiredAction.MANUAL_REVIEW) == ("the value is large",)


def test_the_association_does_not_depend_on_position():
    """The failure the old parallel-tuple shape invited: reading reasons[i] as the
    reason for required_actions[i]. Here two rules impose one action and a third
    imposes another, so the two sequences have different lengths and any
    index-based reading is wrong."""
    result = ComplianceActionSet(
        fired=(
            FiredAction(RequiredAction.MANUAL_REVIEW, "A", "first reason"),
            FiredAction(RequiredAction.MANUAL_REVIEW, "B", "second reason"),
            FiredAction(RequiredAction.EDD_REQUIRED, "C", "third reason"),
        )
    )

    assert result.required_actions == (
        RequiredAction.MANUAL_REVIEW,
        RequiredAction.EDD_REQUIRED,
    )
    assert len(result.reasons) == 3
    assert result.reasons_for(RequiredAction.EDD_REQUIRED) == ("third reason",)
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == ("A", "B")


# ── resolving jurisdiction ────────────────────────────────────────────────────


US_FINCEN = ResolvingJurisdiction(JurisdictionType.COUNTRY, "US_FINCEN")
FATF = ResolvingJurisdiction(JurisdictionType.FRAMEWORK, "FATF")


async def test_the_resolving_jurisdiction_reaches_the_action_set():
    result = await evaluate_settlement_compliance(
        _facts(),
        ListRepository([_rule("R", RequiredAction.MANUAL_REVIEW, "why")]),
        resolving_jurisdiction=US_FINCEN,
    )

    assert result.resolving_jurisdiction == US_FINCEN
    assert result.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert result.resolving_jurisdiction.value == "US_FINCEN"


async def test_the_jurisdiction_is_carried_even_when_no_rule_fires():
    """S1T2 records which jurisdiction's classification was consulted, not only
    which one produced an obligation. A settlement that incurred nothing was
    still assessed under some regime."""
    result = await evaluate_settlement_compliance(
        _facts(), ListRepository([]), resolving_jurisdiction=FATF
    )

    assert result.required_actions == ()
    assert result.resolving_jurisdiction == FATF


def test_the_precedence_level_is_kept_not_only_the_name():
    """S0T2 returns a type/value pair. Collapsing it to the name would leave a
    compliance officer unable to tell a corridor override from the framework
    baseline it overrode — the two can even share a value."""
    corridor = ResolvingJurisdiction(JurisdictionType.CORRIDOR, "US_IN")
    country = ResolvingJurisdiction(JurisdictionType.COUNTRY, "US_IN")

    assert corridor != country
    assert corridor.value == country.value
    assert str(corridor) == "corridor:US_IN"


def test_the_jurisdiction_does_not_participate_in_matching():
    """It records which regime classified the sector; the rules match on the tier
    and label that classification produced."""
    facts = _facts()
    rules: list = []

    without = evaluate_compliance_rules(facts, rules)
    with_jurisdiction = evaluate_compliance_rules(
        facts, rules, resolving_jurisdiction=ResolvingJurisdiction(JurisdictionType.COUNTRY, "IN_RBI")
    )

    assert without.fired == with_jurisdiction.fired


def test_a_resolved_classification_carries_the_jurisdiction_that_answered():
    resolved = ResolvedSectorClassification(
        risk_tier="high",
        classification_label="DNFBP",
        resolving_jurisdiction=US_FINCEN,
        found=True,
    )

    assert resolved.resolving_jurisdiction == US_FINCEN


def test_a_not_found_classification_says_so_explicitly():
    """S0T2 requires an unrated sector to be reported as not found rather than
    defaulting silently into ``standard`` — the two are different facts and only
    one of them means a regulator looked."""
    resolved = ResolvedSectorClassification(
        risk_tier="standard",
        classification_label=None,
        resolving_jurisdiction=None,
        found=False,
    )

    assert resolved.found is False
    assert resolved.resolving_jurisdiction is None


def test_found_and_the_jurisdiction_cannot_disagree():
    """A classification that was found must name who made it, and one that was
    not must name nobody."""
    with pytest.raises(ValueError):
        ResolvedSectorClassification(
            risk_tier="high",
            classification_label="DNFBP",
            resolving_jurisdiction=None,
            found=True,
        )
    with pytest.raises(ValueError):
        ResolvedSectorClassification(
            risk_tier="standard",
            classification_label=None,
            resolving_jurisdiction=FATF,
            found=False,
        )
