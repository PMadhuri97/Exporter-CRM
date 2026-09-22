"""Threshold evaluation across currencies, through the application entry point.

The conversion arithmetic is asserted in ``test_threshold_conversion.py`` and the
comparison in ``test_compliance_rule_matching.py``. What is asserted here is the
part only the service does: deciding which currencies need a rate at all, asking
for them through the injected port, and what happens to the decision when the
answer does not come back.

No database. The repository is a list, because none of this depends on where the
rules were stored.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.domain.entities.compliance_rule import (
    ComplianceRule,
    RequiredAction,
)
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.tests.fixtures.rate_providers import (
    FloatRateProvider,
    StubIndicativeRateProvider,
    UnavailableRateProvider,
)
from app.shared.value_objects import AssetType, CurrencyAsset, CurrencyRegistry

AS_OF = date(2026, 8, 4)

#: USD 50,000.00 and INR 4,150,000.00 in minor units.
USD_THRESHOLD = 5_000_000
INR_THRESHOLD = 415_000_000
EUR_THRESHOLD = 4_600_000

REGISTRY_WITH_EUR = CurrencyRegistry(
    version="test-eur",
    assets={
        "USD": CurrencyAsset(
            asset_code="USD", asset_type=AssetType.FIAT, precision=2, minor_unit_name="cent"
        ),
        "EUR": CurrencyAsset(
            asset_code="EUR", asset_type=AssetType.FIAT, precision=2, minor_unit_name="cent"
        ),
    },
)


class ListRepository:
    """The rule registry as a list. Satisfies ComplianceRuleRepository."""

    def __init__(self, rules: list[ComplianceRule]) -> None:
        self._rules = rules

    async def list_rules(self) -> list[ComplianceRule]:
        return list(self._rules)


def _rule(rule_id: str, threshold: int, currency: str) -> ComplianceRule:
    return ComplianceRule(
        rule_id=rule_id,
        description=f"Large value in {currency}",
        amount_threshold=threshold,
        amount_threshold_currency=currency,
        required_action=RequiredAction.MANUAL_REVIEW,
        action_reason=f"Settlement meets the {currency} large-value threshold",
        effective_from=date(2024, 1, 1),
    )


def _facts(amount_minor: int, asset_code: str = "USD") -> ComplianceFacts:
    return ComplianceFacts(
        send_amount_minor=amount_minor, send_asset_code=asset_code, as_of_date=AS_OF
    )


USD_RULE = _rule("USD_LARGE_VALUE", USD_THRESHOLD, "USD")
INR_RULE = _rule("INR_LARGE_VALUE", INR_THRESHOLD, "INR")
EUR_RULE = _rule("EUR_LARGE_VALUE", EUR_THRESHOLD, "EUR")

USD_TO_INR = StubIndicativeRateProvider({("USD", "INR"): Decimal("83")})


# ── same currency: no rate is fetched ─────────────────────────────────────────


async def test_a_usd_threshold_on_a_usd_settlement_fetches_no_rate():
    """The Walk-phase path. Every seeded rule and every settlement is USD, so an
    evaluation must not reach a rate feed at all — not even to be told the rate
    is 1."""
    provider = StubIndicativeRateProvider({})

    result = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD), ListRepository([USD_RULE]), provider
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert provider.calls == []


async def test_the_same_currency_path_needs_no_provider_at_all():
    result = await evaluate_settlement_compliance(_facts(USD_THRESHOLD), ListRepository([USD_RULE]))

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True


async def test_a_usd_settlement_below_a_usd_threshold_is_not_reviewed():
    result = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD - 1), ListRepository([USD_RULE]), USD_TO_INR
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is False


# ── cross currency ────────────────────────────────────────────────────────────


async def test_a_usd_settlement_is_valued_against_an_inr_threshold():
    """USD 50,000.00 at 83 is INR 4,150,000.00 — exactly the threshold, which is
    an inclusive bound."""
    result = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD), ListRepository([INR_RULE]), USD_TO_INR
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.rule_ids == ("INR_LARGE_VALUE",)


async def test_a_usd_settlement_below_the_converted_inr_threshold_is_not_reviewed():
    """One cent less is INR 4,149,999.17, which rounds to 4,149,999 — below."""
    result = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD - 1), ListRepository([INR_RULE]), USD_TO_INR
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is False


async def test_the_rate_is_requested_for_the_pair_being_compared():
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83")})

    await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD), ListRepository([INR_RULE]), provider
    )

    assert provider.calls == [("USD", "INR")]


async def test_a_eur_threshold_is_evaluated_against_a_supplied_registry():
    """EUR is not a platform asset, so its precision comes from the registry the
    caller supplies rather than from an assumption."""
    provider = StubIndicativeRateProvider({("USD", "EUR"): Decimal("0.92")})

    at = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD),
        ListRepository([EUR_RULE]),
        provider,
        registry=REGISTRY_WITH_EUR,
    )
    below = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD - 1),
        ListRepository([EUR_RULE]),
        provider,
        registry=REGISTRY_WITH_EUR,
    )

    assert at.requires(RequiredAction.MANUAL_REVIEW) is True
    assert below.requires(RequiredAction.MANUAL_REVIEW) is False


async def test_one_rate_is_fetched_per_currency_however_many_rules_share_it():
    """Two INR-denominated rules are one question about what the settlement is
    worth in INR, not two."""
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83")})
    second = _rule("INR_SECOND", INR_THRESHOLD * 2, "INR")

    await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD), ListRepository([INR_RULE, second]), provider
    )

    assert provider.calls == [("USD", "INR")]


# ── the fail-safe ─────────────────────────────────────────────────────────────


async def test_an_unreachable_rate_feed_escalates_rather_than_excusing():
    """The whole point of the fail-safe. A settlement of one paisa cannot really
    breach an INR 4.15m threshold, but with no rate the platform cannot know
    that, and the safe answer is the one a human can clear."""
    result = await evaluate_settlement_compliance(
        _facts(1), ListRepository([INR_RULE]), UnavailableRateProvider()
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.rule_ids == ("INR_LARGE_VALUE",)


async def test_no_provider_is_treated_as_an_unavailable_provider():
    result = await evaluate_settlement_compliance(_facts(1), ListRepository([INR_RULE]))

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True


async def test_an_unsupported_pair_escalates():
    """The provider is reachable and simply cannot quote this pair."""
    result = await evaluate_settlement_compliance(
        _facts(1), ListRepository([INR_RULE]), StubIndicativeRateProvider({})
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True


async def test_a_float_rate_escalates_rather_than_crashing_the_evaluation():
    """A float is refused by the conversion, and a refused conversion is an
    unavailable one. The evaluation still returns a decision."""
    result = await evaluate_settlement_compliance(
        _facts(1), ListRepository([INR_RULE]), FloatRateProvider(83.0)
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True


async def test_a_failed_rate_does_not_affect_a_rule_in_the_settlements_own_currency():
    """One currency failing must not decide anything about another. The USD rule
    is evaluated on the real amount and stays below its threshold."""
    result = await evaluate_settlement_compliance(
        _facts(USD_THRESHOLD - 1),
        ListRepository([USD_RULE, INR_RULE]),
        UnavailableRateProvider(),
    )

    assert result.rule_ids == ("INR_LARGE_VALUE",)


async def test_the_evaluation_still_returns_when_every_rate_fails():
    result = await evaluate_settlement_compliance(
        _facts(1), ListRepository([INR_RULE, EUR_RULE]), UnavailableRateProvider()
    )

    assert set(result.rule_ids) == {"INR_LARGE_VALUE", "EUR_LARGE_VALUE"}


# ── determinism ───────────────────────────────────────────────────────────────


async def test_the_same_settlement_and_rate_decide_the_same_way_every_time():
    facts = _facts(USD_THRESHOLD)
    repository = ListRepository([USD_RULE, INR_RULE])

    results = [
        await evaluate_settlement_compliance(facts, repository, USD_TO_INR) for _ in range(10)
    ]

    assert all(result == results[0] for result in results)
    assert all(result.rule_ids == results[0].rule_ids for result in results)


async def test_the_decision_does_not_depend_on_the_order_rules_come_back_in():
    facts = _facts(USD_THRESHOLD)
    forward = await evaluate_settlement_compliance(
        facts, ListRepository([USD_RULE, INR_RULE]), USD_TO_INR
    )
    reversed_ = await evaluate_settlement_compliance(
        facts, ListRepository([INR_RULE, USD_RULE]), USD_TO_INR
    )

    assert forward == reversed_


@pytest.mark.parametrize("amount", [0, 1, USD_THRESHOLD - 1, USD_THRESHOLD, USD_THRESHOLD * 3])
async def test_no_float_ever_reaches_the_comparison(amount):
    """Every amount that comes back is an integer number of minor units. A float
    surviving into the comparison is how a threshold decision becomes
    irreproducible across machines."""
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83.333333")})

    result = await evaluate_settlement_compliance(
        _facts(amount), ListRepository([INR_RULE]), provider
    )

    assert isinstance(result.requires(RequiredAction.MANUAL_REVIEW), bool)
    assert result == await evaluate_settlement_compliance(
        _facts(amount), ListRepository([INR_RULE]), provider
    )
