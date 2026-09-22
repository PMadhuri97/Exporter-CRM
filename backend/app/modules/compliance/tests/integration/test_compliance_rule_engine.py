from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.compliance import (
    ComplianceActionSet,
    ComplianceFacts,
    RequiredAction,
    SQLAlchemyComplianceRuleRepository,
    evaluate_settlement_compliance,
)
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR,
    load_compliance_rules,
)
from app.modules.compliance.tests.fixtures.rate_providers import StubIndicativeRateProvider
from app.platform.database import services as database

DNFBP_RULE = "DNFBP_EDD_REQUIRED"
LARGE_VALUE_RULE = "LARGE_VALUE_REVIEW"

#: After both rules take effect (2024-01-01) and after today, so the suite does
#: not start failing on a calendar boundary.
AS_OF = date(2026, 8, 4)

#: The seeded threshold: USD 50,000.00 in integer minor units.
THRESHOLD = 5_000_000

#: What the sector registry resolves for a DNFBP sector. The seeded rule
#: requires the tier and the label together, so tests state both.
DNFBP_DESIGNATION = {"sector_risk_tier": "high", "classification_label": "DNFBP"}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def real_registry():
    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, SEED_DATA_DIR)


@pytest_asyncio.fixture(loop_scope="function")
async def repository(real_registry):
    """A repository on a session belonging to the running test's own event loop."""
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemyComplianceRuleRepository(session)


def _facts(**overrides) -> ComplianceFacts:
    fields: dict = {
        "send_amount_minor": 100_000,
        "send_asset_code": "USD",
        "as_of_date": AS_OF,
    }
    fields.update(overrides)
    return ComplianceFacts(**fields)


# ── the chain ─────────────────────────────────────────────────────────────────


async def test_evaluation_returns_an_action_set(repository):
    result = await evaluate_settlement_compliance(_facts(), repository)
    assert isinstance(result, ComplianceActionSet)


async def test_an_ordinary_settlement_incurs_no_obligations(repository):
    """Small, unremarkable, in no designated sector — the registry has nothing to
    say about it, and saying nothing is an answer rather than a failure."""
    result = await evaluate_settlement_compliance(_facts(), repository)

    assert result.edd_required is False
    assert result.requires(RequiredAction.MANUAL_REVIEW) is False
    assert result.requires(RequiredAction.ENHANCED_MONITORING) is False
    assert result.rule_ids == ()
    assert result.reasons == ()


# ── DNFBP_EDD_REQUIRED ────────────────────────────────────────────────────────


async def test_a_dnfbp_counterparty_requires_edd(repository):
    result = await evaluate_settlement_compliance(
        _facts(**DNFBP_DESIGNATION), repository
    )

    assert result.edd_required is True
    assert result.edd_trigger_rule == DNFBP_RULE
    assert result.rule_ids == (DNFBP_RULE,)


async def test_the_edd_decision_carries_the_seeded_reason(repository):
    """The reason is what a regulator is shown, so it must survive the round trip
    from YAML rather than being regenerated from the columns."""
    result = await evaluate_settlement_compliance(
        _facts(**DNFBP_DESIGNATION), repository
    )

    assert len(result.reasons) == 1
    assert "FATF" in result.reasons[0]


async def test_edd_applies_at_any_amount(repository):
    """The designation obliges EDD regardless of value — the rule sets no
    threshold, and an unset condition constrains nothing."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=1, **DNFBP_DESIGNATION), repository
    )

    assert result.edd_required is True


async def test_an_undesignated_sector_does_not_require_edd(repository):
    result = await evaluate_settlement_compliance(
        _facts(classification_label="NOT_DESIGNATED"), repository
    )

    assert result.edd_required is False
    assert result.edd_trigger_rule is None


# ── LARGE_VALUE_REVIEW ────────────────────────────────────────────────────────


async def test_a_settlement_at_the_threshold_requires_manual_review(repository):
    """The threshold is an inclusive lower bound."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD), repository
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.rule_ids == (LARGE_VALUE_RULE,)


async def test_a_settlement_one_minor_unit_below_the_threshold_does_not(repository):
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD - 1), repository
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is False
    assert result.rule_ids == ()


async def test_a_settlement_in_another_asset_is_valued_against_the_usd_threshold(repository):
    """Five million minor units is fifty thousand dollars and fifty thousand
    rupees — the same integer and nothing like the same amount — so the
    settlement is valued in the rule's currency before the two are compared.

    INR 1,000,000.00 at 1/83 is USD 12,048.19, short of the USD 50,000
    threshold."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD * 20, send_asset_code="INR"),
        repository,
        StubIndicativeRateProvider({("INR", "USD"): Decimal("0.012048192771")}),
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is False
    assert result.rule_ids == ()


async def test_a_settlement_in_another_asset_crosses_the_threshold_once_converted(repository):
    """INR 41,500,000.00 at 1/83 is USD 500,000.00, well past the threshold."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=4_150_000_000, send_asset_code="INR"),
        repository,
        StubIndicativeRateProvider({("INR", "USD"): Decimal("0.012048192771")}),
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.rule_ids == (LARGE_VALUE_RULE,)


async def test_a_settlement_in_another_asset_escalates_when_no_rate_is_available(repository):
    """The fail-safe, against the rules that actually ship: without a rate the
    platform cannot tell whether an INR settlement breaches a USD threshold, and
    escalating is the answer a human can clear."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=1, send_asset_code="INR"), repository
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.rule_ids == (LARGE_VALUE_RULE,)


async def test_a_usd_settlement_never_needs_a_rate(repository):
    """The Walk-phase path against the real seed data: the only threshold rule
    that ships is denominated in USD, so a USD settlement reaches no rate feed."""
    provider = StubIndicativeRateProvider({})

    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD), repository, provider
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert provider.calls == []


# ── several rules at once ─────────────────────────────────────────────────────


async def test_obligations_from_different_rules_accumulate(repository):
    """One rule imposes one action; a settlement subject to both carries both,
    each with the rule that imposed it."""
    result = await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD, **DNFBP_DESIGNATION), repository
    )

    assert result.edd_required is True
    assert result.requires(RequiredAction.MANUAL_REVIEW) is True
    assert result.edd_trigger_rule == DNFBP_RULE
    assert set(result.rule_ids) == {DNFBP_RULE, LARGE_VALUE_RULE}
    assert len(result.reasons) == 2


async def test_edd_is_always_paired_with_the_rule_that_triggered_it(repository):
    """Mirrors ck_settlement_edd_rule_consistent, which will reject a settlement
    row whose edd_required and edd_trigger_rule disagree."""
    for facts in (
        _facts(),
        _facts(**DNFBP_DESIGNATION),
        _facts(send_amount_minor=THRESHOLD),
        _facts(send_amount_minor=THRESHOLD, **DNFBP_DESIGNATION),
    ):
        result = await evaluate_settlement_compliance(facts, repository)
        assert result.edd_required == (result.edd_trigger_rule is not None)


# ── effectivity ───────────────────────────────────────────────────────────────


async def test_a_settlement_predating_the_rules_is_governed_by_neither(repository):
    """Effectivity is judged on the settlement's own date, never today. Both
    seeded rules take effect on 2024-01-01."""
    result = await evaluate_settlement_compliance(
        _facts(
            send_amount_minor=THRESHOLD,
            **DNFBP_DESIGNATION,
            as_of_date=date(2023, 12, 31),
        ),
        repository,
    )

    assert result.rule_ids == ()


async def test_a_settlement_on_the_effective_date_is_governed(repository):
    result = await evaluate_settlement_compliance(
        _facts(**DNFBP_DESIGNATION, as_of_date=date(2024, 1, 1)), repository
    )

    assert result.edd_required is True


# ── determinism and read-only ─────────────────────────────────────────────────


async def test_evaluating_twice_returns_the_same_decision(repository):
    """Nothing is carried between evaluations, so re-running one must not change
    what a payment was obliged to do."""
    facts = _facts(send_amount_minor=THRESHOLD, **DNFBP_DESIGNATION)

    first = await evaluate_settlement_compliance(facts, repository)
    second = await evaluate_settlement_compliance(facts, repository)

    assert first == second
    assert first.rule_ids == second.rule_ids
    assert first.reasons == second.reasons


async def test_evaluation_writes_nothing(repository):
    """A compliance decision is not a side effect. Recording one against a
    settlement is the caller's transaction, and this must not have started it."""
    session = repository.session
    before = (
        await session.execute(select(func.count()).select_from(ComplianceRule))
    ).scalar_one()

    await evaluate_settlement_compliance(
        _facts(send_amount_minor=THRESHOLD, **DNFBP_DESIGNATION), repository
    )

    assert not session.new
    assert not session.dirty
    assert not session.deleted

    after = (
        await session.execute(select(func.count()).select_from(ComplianceRule))
    ).scalar_one()
    assert after == before


async def test_evaluation_does_not_commit_the_callers_session(repository):
    session = repository.session
    session.add(
        ComplianceRule(
            rule_id="ENGINE_TEST_UNCOMMITTED",
            description="Added by the test, never committed",
            required_action=RequiredAction.MANUAL_REVIEW,
            action_reason="Present only to prove the entry point does not commit its session",
            effective_from=date(2024, 1, 1),
        )
    )

    try:
        await evaluate_settlement_compliance(_facts(), repository)

        async with database.AsyncSessionLocal() as observer:
            visible = await observer.execute(
                select(ComplianceRule.rule_id).where(
                    ComplianceRule.rule_id == "ENGINE_TEST_UNCOMMITTED"
                )
            )
            assert visible.scalar_one_or_none() is None, (
                "the entry point committed the caller's session"
            )
    finally:
        await session.rollback()


# ── the public surface ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "ComplianceActionSet",
        "ComplianceFacts",
        "ComplianceRuleRepository",
        "IndicativeRateProvider",
        "SQLAlchemyComplianceRuleRepository",
        "evaluate_compliance_rules",
        "evaluate_settlement_compliance",
    ],
)
def test_the_facade_exports_what_a_caller_needs(name):
    """S1T2 may import only app.modules.compliance. Anything missing here is
    unreachable to it, however public it looks from inside the module."""
    import app.modules.compliance as compliance

    assert name in compliance.__all__
    assert hasattr(compliance, name)


def test_the_entry_point_takes_the_parameters_the_contract_names():
    import inspect

    import app.modules.compliance as compliance

    parameters = inspect.signature(compliance.evaluate_compliance_rules).parameters

    for name in (
        "sector_code",
        "purpose_code",
        "corridor_id",
        "send_amount",
        "send_currency",
        "as_of_date",
    ):
        assert name in parameters, f"the contract names {name}"

    assert "send_amount_usd" not in parameters
