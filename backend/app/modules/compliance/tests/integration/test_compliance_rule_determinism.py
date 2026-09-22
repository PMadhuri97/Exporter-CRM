"""The same settlement decides the same way, every time, against a real database.

Determinism is asserted branch by branch elsewhere. What this suite adds is
repetition against Postgres: a hundred evaluations of one settlement, so that
anything order-dependent, cached, clock-dependent or accumulated across calls has
a hundred chances to show itself rather than one.

A compliance decision that is not reproducible cannot be defended. Re-running an
evaluation months later — during an audit, during a dispute — must produce what
it produced when the money moved.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.compliance import (
    ComplianceFacts,
    SQLAlchemyComplianceRuleRepository,
    evaluate_settlement_compliance,
)
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.required_action import RequiredAction
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR,
    load_compliance_rules,
)
from app.modules.compliance.tests.fixtures.rate_providers import (
    StubIndicativeRateProvider,
    UnavailableRateProvider,
)
from app.platform.database import services as database

#: Enough repetition that an ordering or accumulation bug is not a coin flip.
REPETITIONS = 100

AS_OF = date(2026, 8, 4)
THRESHOLD = 5_000_000
DNFBP_RULE = "DNFBP_EDD_REQUIRED"
LARGE_VALUE_RULE = "LARGE_VALUE_REVIEW"

INR_TO_USD = Decimal("0.012048192771")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def real_registry():
    """The rules that actually ship. Idempotent, so this needs no teardown."""
    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, SEED_DATA_DIR)


@pytest_asyncio.fixture(loop_scope="function")
async def repository(real_registry):
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemyComplianceRuleRepository(session)


def _facts(**overrides) -> ComplianceFacts:
    fields: dict = {
        "send_amount_minor": THRESHOLD,
        "send_asset_code": "USD",
        "as_of_date": AS_OF,
        # The seeded DNFBP rule requires the tier and the label together, so a
        # settlement that is to fire it must carry both.
        "sector_risk_tier": "high",
        "classification_label": "DNFBP",
    }
    fields.update(overrides)
    return ComplianceFacts(**fields)


async def _evaluate_many(repository, facts, provider=None, times=REPETITIONS):
    return [
        await evaluate_settlement_compliance(facts, repository, provider) for _ in range(times)
    ]


# ── one hundred evaluations ───────────────────────────────────────────────────


async def test_one_hundred_evaluations_agree(repository):
    results = await _evaluate_many(repository, _facts())

    assert len(results) == REPETITIONS
    assert len(set(results)) == 1


async def test_one_hundred_evaluations_return_the_expected_decision(repository):
    """Stable *and* correct. A hundred identically wrong answers would satisfy
    the assertion above on its own."""
    results = await _evaluate_many(repository, _facts())

    assert results[0].edd_required is True
    assert results[0].edd_trigger_rule == DNFBP_RULE
    assert results[0].requires(RequiredAction.MANUAL_REVIEW)
    assert set(results[0].rule_ids) == {DNFBP_RULE, LARGE_VALUE_RULE}


async def test_rule_ids_come_back_in_the_same_order_every_time(repository):
    """Not merely the same set. The order is what a reviewer reads, and the
    reasons are aligned to it positionally."""
    results = await _evaluate_many(repository, _facts())

    assert len({result.rule_ids for result in results}) == 1
    assert len({result.reasons for result in results}) == 1


async def test_one_hundred_evaluations_of_an_unremarkable_settlement_agree(repository):
    results = await _evaluate_many(
        repository, _facts(send_amount_minor=1, classification_label=None)
    )

    assert len(set(results)) == 1
    assert results[0].rule_ids == ()


@pytest.mark.parametrize(
    "amount", [0, 1, THRESHOLD - 1, THRESHOLD, THRESHOLD + 1, 10**12]
)
async def test_each_amount_decides_the_same_way_across_repeats(repository, amount):
    """The threshold boundary repeated, since that is where a rounding or
    comparison instability would surface."""
    results = await _evaluate_many(
        repository, _facts(send_amount_minor=amount, classification_label=None), times=25
    )

    assert len(set(results)) == 1


# ── one hundred evaluations write nothing ─────────────────────────────────────


async def test_one_hundred_evaluations_write_nothing(repository):
    """Reading a registry a hundred times must leave it exactly as it was."""
    session = repository.session
    before = (
        await session.execute(select(func.count()).select_from(ComplianceRule))
    ).scalar_one()

    await _evaluate_many(repository, _facts())

    assert not session.new
    assert not session.dirty
    assert not session.deleted

    after = (
        await session.execute(select(func.count()).select_from(ComplianceRule))
    ).scalar_one()
    assert after == before


async def test_the_registry_is_unchanged_after_repeated_evaluation(repository):
    """Checked from a second connection, so a change held uncommitted in the
    evaluating session would still be caught."""
    await _evaluate_many(repository, _facts())

    async with database.AsyncSessionLocal() as observer:
        rows = await observer.execute(
            select(ComplianceRule.rule_id, ComplianceRule.action_reason).order_by(
                ComplianceRule.rule_id
            )
        )
        stored = rows.all()

    assert {rule_id for rule_id, _ in stored} >= {DNFBP_RULE, LARGE_VALUE_RULE}
    assert all(reason for _, reason in stored)


# ── determinism across an FX conversion ───────────────────────────────────────


async def test_one_hundred_cross_currency_evaluations_agree(repository):
    """A conversion sits between the registry and the comparison here, so this
    also pins the arithmetic: a hundred conversions of the same amount at the
    same rate must round to the same minor unit every time."""
    provider = StubIndicativeRateProvider({("INR", "USD"): INR_TO_USD})
    facts = _facts(send_amount_minor=4_150_000_000, send_asset_code="INR")

    results = await _evaluate_many(repository, facts, provider)

    assert len(set(results)) == 1
    assert results[0].requires(RequiredAction.MANUAL_REVIEW)


async def test_a_repeated_evaluation_asks_for_the_rate_each_time(repository):
    """No caching between calls. A rate held over from an earlier evaluation is
    how a decision starts depending on what was evaluated before it."""
    provider = StubIndicativeRateProvider({("INR", "USD"): INR_TO_USD})
    facts = _facts(send_amount_minor=1, send_asset_code="INR", classification_label=None)

    await _evaluate_many(repository, facts, provider, times=10)

    assert provider.calls == [("INR", "USD")] * 10


async def test_one_hundred_evaluations_agree_when_the_rate_is_unavailable(repository):
    """The fail-safe is a decision like any other and must be as reproducible."""
    facts = _facts(send_amount_minor=1, send_asset_code="INR", classification_label=None)

    results = await _evaluate_many(repository, facts, UnavailableRateProvider())

    assert len(set(results)) == 1
    assert results[0].requires(RequiredAction.MANUAL_REVIEW)
    assert results[0].rule_ids == (LARGE_VALUE_RULE,)


async def test_a_failing_rate_feed_does_not_degrade_across_repeats(repository):
    """A hundred consecutive failures must not accumulate into a different
    answer, or into no answer at all."""
    facts = _facts(send_amount_minor=1, send_asset_code="INR", classification_label=None)
    provider = UnavailableRateProvider()

    results = await _evaluate_many(repository, facts, provider)

    assert len(set(results)) == 1
    assert len(provider.calls) == REPETITIONS


# ── determinism across effectivity ────────────────────────────────────────────


@pytest.mark.parametrize(
    "as_of", [date(2023, 12, 31), date(2024, 1, 1), date(2026, 8, 4), date(2099, 1, 1)]
)
async def test_each_evaluation_date_is_stable_across_repeats(repository, as_of):
    """Effectivity is judged on the settlement's date, not today's, so repeating
    an evaluation cannot drift as the clock moves."""
    results = await _evaluate_many(repository, _facts(as_of_date=as_of), times=25)

    assert len(set(results)) == 1
