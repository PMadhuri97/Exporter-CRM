from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.compliance import RequiredAction, evaluate_compliance_rules
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR as REAL_RULE_SEED_DIR,
)
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    load_compliance_rules,
)
from app.modules.compliance.infrastructure.purpose_code_seed_loader import (
    SEED_DATA_DIR as PURPOSE_SEED_DIR,
)
from app.modules.compliance.infrastructure.purpose_code_seed_loader import load_purpose_codes
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    SEED_DATA_DIR as SECTOR_SEED_DIR,
)
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    load_sector_registry,
)
from app.modules.compliance.tests.fixtures.rate_providers import (
    StubIndicativeRateProvider,
    UnavailableRateProvider,
)
from app.platform.database import services as database

CORRIDOR = "US_IN"
AS_OF = date(2026, 8, 12)

#: No sector conditions are used by any rule below, so the classification is
#: deliberately irrelevant here — this suite is about thresholds and currency.
NEUTRAL_SECTOR = "SECTOR_WITH_NO_CLASSIFICATION"

EUR_RULE = "EUR_LARGE_VALUE_REVIEW"
INR_RULE = "INR_LARGE_VALUE_REVIEW"
#: EUR 46,000.00 and INR 415,000.00, both as integer minor units at precision 2.
EUR_THRESHOLD = 4_600_000
INR_THRESHOLD = 41_500_000

#: A rule the real GitOps registry contains, used to prove the restore worked.
REAL_RULE = "DNFBP_EDD_REQUIRED"

#: The entire registry for this module. Neither rule exists in the shipped seed
#: data, neither names a sector or a corridor, and neither is mentioned by any
#: application module — adding them is a file, and nothing else.
RULES_YAML = f"""
- rule_id: {EUR_RULE}
  description: "Review settlements at or above the euro large-value threshold"
  amount_threshold: {EUR_THRESHOLD}
  amount_threshold_currency: EUR
  required_action: manual_review
  action_reason: "Transaction value above the euro large-value review threshold."
  effective_from: 2024-01-01

- rule_id: {INR_RULE}
  description: "Monitor settlements at or above the rupee large-value threshold"
  amount_threshold: {INR_THRESHOLD}
  amount_threshold_currency: INR
  required_action: enhanced_monitoring
  action_reason: "Transaction value above the rupee enhanced-monitoring threshold."
  effective_from: 2024-01-01
"""


@pytest.fixture(scope="module")
def rule_seed_dir(tmp_path_factory):
    """The YAML on disk, in the layout the real loader expects."""
    path = tmp_path_factory.mktemp("config_only_rules")
    (path / "compliance-rules.yaml").write_text(RULES_YAML)
    return path


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded(rule_seed_dir):
    """Load this module's registry, then put the real GitOps one back.

    The loader replaces the whole table, so the restore is not optional — a
    leaked fixture rule would change the answer for every other suite.
    """
    async with database.AsyncSessionLocal() as session:
        await load_purpose_codes(session, PURPOSE_SEED_DIR)
        await load_sector_registry(session, SECTOR_SEED_DIR)
        await load_compliance_rules(session, rule_seed_dir)

    try:
        yield
    finally:
        async with database.AsyncSessionLocal() as session:
            await load_compliance_rules(session, REAL_RULE_SEED_DIR)

            restored = await session.execute(
                select(ComplianceRule.rule_id).where(ComplianceRule.rule_id == REAL_RULE)
            )
            assert restored.scalar_one_or_none() == REAL_RULE, (
                "GitOps seed data was not restored; the shared test database is "
                "still holding this suite's fixture rules"
            )
            leaked = await session.execute(
                select(ComplianceRule.rule_id).where(
                    ComplianceRule.rule_id.in_([EUR_RULE, INR_RULE])
                )
            )
            assert leaked.scalars().all() == [], "fixture rules survived the restore"


@pytest_asyncio.fixture(loop_scope="function")
async def session(seeded):
    async with database.AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _purpose_code(session) -> str:
    from app.modules.compliance.domain.entities.registry import PurposeCodeCorridorMapping

    return (
        await session.execute(
            select(PurposeCodeCorridorMapping.canonical_code)
            .where(PurposeCodeCorridorMapping.corridor_id == CORRIDOR)
            .limit(1)
        )
    ).scalar_one()


async def _evaluate(session, *, amount: int, currency: str, provider=None):
    return await evaluate_compliance_rules(
        session,
        sector_code=NEUTRAL_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=amount,
        send_currency=currency,
        as_of_date=AS_OF,
        rate_provider=provider,
    )


# ── the rules really did come from YAML ───────────────────────────────────────


async def test_the_yaml_rules_are_in_the_table(session):
    """The premise of everything below: these rows exist because a file said so."""
    rows = (await session.execute(select(ComplianceRule.rule_id))).scalars().all()

    assert sorted(rows) == sorted([EUR_RULE, INR_RULE])


async def test_the_threshold_and_currency_survived_the_loader(session):
    rule = (
        await session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_id == EUR_RULE)
        )
    ).scalar_one()

    assert rule.amount_threshold == EUR_THRESHOLD
    assert rule.amount_threshold_currency == "EUR"
    assert rule.required_action is RequiredAction.MANUAL_REVIEW


async def test_no_application_module_mentions_these_rules():
    """AC6's actual claim: configuration only, no application-code change.

    The rule ids are searched for across the application package. Finding one
    would mean the behaviour under test is not really configuration-driven.
    """
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[4]
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if "tests" not in path.parts
        and any(rule in path.read_text(encoding="utf-8") for rule in (EUR_RULE, INR_RULE))
    ]

    assert offenders == [], f"these application modules name the fixture rules: {offenders}"


# ── Cases 1-3 — a EUR settlement against a EUR threshold ──────────────────────
#
# Same currency on both sides, so no rate is needed and none is fetched. This is
# the case that shows a brand-new currency working from configuration alone.


async def test_a_eur_settlement_below_the_eur_threshold_is_not_reviewed(session):
    """Case 1. One minor unit below."""
    provider = StubIndicativeRateProvider({})

    result = await _evaluate(
        session, amount=EUR_THRESHOLD - 1, currency="EUR", provider=provider
    )

    assert RequiredAction.MANUAL_REVIEW not in result.required_actions
    # The EUR rule needed no rate. (The INR rule does, and asks for EUR->INR —
    # which is why this asserts on the pair rather than on calls being empty.)
    assert ("EUR", "EUR") not in provider.calls


async def test_a_eur_settlement_at_the_eur_threshold_is_reviewed(session):
    """Case 2. The boundary is inclusive."""
    provider = StubIndicativeRateProvider({})

    result = await _evaluate(session, amount=EUR_THRESHOLD, currency="EUR", provider=provider)

    assert RequiredAction.MANUAL_REVIEW in result.required_actions
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == (EUR_RULE,)
    assert ("EUR", "EUR") not in provider.calls


async def test_a_eur_settlement_above_the_eur_threshold_is_reviewed(session):
    """Case 3."""
    result = await _evaluate(
        session, amount=EUR_THRESHOLD * 2, currency="EUR", provider=StubIndicativeRateProvider({})
    )

    assert RequiredAction.MANUAL_REVIEW in result.required_actions


async def test_the_eur_reason_is_the_one_the_yaml_states(session):
    """The text a compliance officer reads comes from the file, unmodified."""
    result = await _evaluate(session, amount=EUR_THRESHOLD, currency="EUR")

    assert result.reasons_for(RequiredAction.MANUAL_REVIEW) == (
        "Transaction value above the euro large-value review threshold.",
    )


# ── Case 4 — a settlement converted into the rule's currency ──────────────────


async def test_a_usd_settlement_is_valued_against_the_inr_threshold(session):
    """Case 4, with a currency the platform registry knows.

    USD 5,000.00 at 83.50 is INR 417,500.00, which clears the INR 415,000.00
    threshold. The rate is supplied through the IndicativeRateProvider port and
    the arithmetic is the shared conversion helper — neither is EUR- or
    INR-specific.
    """
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83.50")})

    result = await _evaluate(session, amount=500_000, currency="USD", provider=provider)

    assert RequiredAction.ENHANCED_MONITORING in result.required_actions
    assert result.rules_for(RequiredAction.ENHANCED_MONITORING) == (INR_RULE,)
    assert ("USD", "INR") in provider.calls


async def test_a_usd_settlement_below_the_converted_inr_threshold_is_not_monitored(session):
    """The converted amount, not the raw one, decides."""
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83.50")})

    result = await _evaluate(session, amount=100_000, currency="USD", provider=provider)

    assert RequiredAction.ENHANCED_MONITORING not in result.required_actions


async def test_the_rate_is_requested_for_the_pair_being_compared(session):
    """Send currency to threshold currency, in that direction."""
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83.50")})

    await _evaluate(session, amount=500_000, currency="USD", provider=provider)

    assert ("USD", "INR") in provider.calls


# ── Case 5 — the fail-safe ────────────────────────────────────────────────────


async def test_an_unavailable_rate_fires_the_rule_conservatively(session):
    """Case 5. A rate that cannot be obtained escalates rather than excuses.

    The amount is far below every threshold, so the only reason either rule can
    fire is the fail-safe treating the unchecked condition as met.
    """
    result = await _evaluate(
        session, amount=1_00, currency="USD", provider=UnavailableRateProvider()
    )

    assert RequiredAction.ENHANCED_MONITORING in result.required_actions
    assert RequiredAction.MANUAL_REVIEW in result.required_actions


async def test_no_provider_at_all_is_treated_the_same_way(session):
    result = await _evaluate(session, amount=1_00, currency="USD", provider=None)

    assert RequiredAction.MANUAL_REVIEW in result.required_actions


async def test_a_eur_threshold_on_a_usd_settlement_falls_back_to_the_fail_safe(session):
    """**The limit of "configuration only", asserted rather than assumed.**

    EUR is not in the platform currency registry, so ``convert_minor_units``
    cannot scale into it and raises ``CurrencyNotRegisteredError``. The fail-safe
    catches that like any other rate failure and fires the rule.

    The outcome is safe — the settlement is escalated, not excused — but it is
    *not* a threshold comparison: the amount here is one hundredth of the
    threshold and the rule fires anyway. Onboarding EUR to the currency registry
    is an application-code change, and until it happens a EUR rule can only be
    compared against a settlement already denominated in EUR.
    """
    provider = StubIndicativeRateProvider({("USD", "EUR"): Decimal("0.92")})

    result = await _evaluate(session, amount=46_000, currency="USD", provider=provider)

    assert RequiredAction.MANUAL_REVIEW in result.required_actions
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == (EUR_RULE,)


async def test_a_failing_rate_does_not_disturb_the_same_currency_rule(session):
    """A EUR settlement is comparable against the EUR rule without any rate, so
    a broken feed must not change that rule's answer — only the INR rule, whose
    threshold genuinely needs converting, falls to the fail-safe."""
    result = await _evaluate(
        session, amount=EUR_THRESHOLD - 1, currency="EUR", provider=UnavailableRateProvider()
    )

    assert RequiredAction.MANUAL_REVIEW not in result.required_actions
    assert RequiredAction.ENHANCED_MONITORING in result.required_actions


# ── determinism across the configured path ────────────────────────────────────


async def test_the_configured_rules_decide_the_same_way_every_time(session):
    provider = StubIndicativeRateProvider({("USD", "INR"): Decimal("83.50")})

    answers = {
        (await _evaluate(session, amount=500_000, currency="USD", provider=provider)).rule_ids
        for _ in range(20)
    }

    assert len(answers) == 1
