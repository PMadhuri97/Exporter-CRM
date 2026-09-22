"""Compliance rule repository against a real database.

The repository is a reader and nothing more: it returns ``compliance_rule`` rows
exactly as stored, with no date filtering and no interpretation. What only a
database can prove is here — that the enum columns round trip as their domain
enums, that unset match conditions come back as ``None`` rather than as some
driver sentinel, and that a rule outside its effective window is still returned.

## Why this suite writes its own rows

There is no seed loader for this table yet (S0T3 Phase 3), so the fixture below
inserts its rules directly. There is no per-test transaction rollback in this
codebase (see backend/conftest.py) — tests commit against a shared Postgres — so
the fixture deletes exactly the rules it inserted on teardown, matched on the
``rule_id`` values it minted. Teardown runs even when a test fails, so a broken
assertion cannot strand fixture rules in the shared database either.

Every assertion is by membership, never by table contents: the database is shared
across a whole run and no test may assume ``compliance_rule`` holds only its own
rows.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.modules.compliance.domain.entities.compliance_rule import (
    ComplianceRule,
    RequiredAction,
)
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.infrastructure.compliance_rule_repository import (
    SQLAlchemyComplianceRuleRepository,
)
from app.modules.compliance.tests.integration._helpers import unique_code

# Imported as a module, not `from ... import AsyncSessionLocal`: the session-scoped
# autouse fixture in backend/conftest.py rebinds that attribute to a NullPool
# sessionmaker, and a name bound at import time would keep the pooled original -
# whose connections belong to whichever event loop first opened them.
from app.platform.database import services as database

AS_OF = date(2026, 8, 4)


@pytest.fixture(scope="module")
def rule_ids() -> dict[str, str]:
    """Rule ids no other test or seed file will collide with."""
    return {
        "unconstrained": unique_code("RULE_UNCONSTRAINED"),
        "tiered": unique_code("RULE_TIERED"),
        "threshold": unique_code("RULE_THRESHOLD"),
        "expired": unique_code("RULE_EXPIRED"),
        "future": unique_code("RULE_FUTURE"),
    }


def _rules(rule_ids: dict[str, str]) -> list[ComplianceRule]:
    return [
        # Every match condition left unset: the row that proves NULL survives the
        # round trip as None.
        ComplianceRule(
            rule_id=rule_ids["unconstrained"],
            description="Applies to every settlement",
            required_action=RequiredAction.ENHANCED_MONITORING,
            action_reason="Baseline monitoring",
            effective_from=date(2024, 1, 1),
        ),
        ComplianceRule(
            rule_id=rule_ids["tiered"],
            description="High-risk sector under FATF",
            corridor_match="US_IN",
            sector_risk_tier_match=RiskTier.HIGH,
            sector_classification_label_match="DNFBP",
            purpose_code_category_match="trade",
            required_action=RequiredAction.EDD_REQUIRED,
            action_reason="Designated non-financial business under FATF Recommendation 22",
            effective_from=date(2024, 1, 1),
        ),
        ComplianceRule(
            rule_id=rule_ids["threshold"],
            description="Large-value settlement",
            amount_threshold=5_000_000,
            amount_threshold_currency="USD",
            required_action=RequiredAction.MANUAL_REVIEW,
            action_reason="Settlement meets or exceeds the large-value threshold",
            effective_from=date(2024, 1, 1),
        ),
        # Outside its window in both directions, on purpose: the repository must
        # return each of these anyway.
        ComplianceRule(
            rule_id=rule_ids["expired"],
            description="Retired rule",
            required_action=RequiredAction.MANUAL_REVIEW,
            action_reason="Superseded",
            effective_from=date(2020, 1, 1),
            effective_to=date(2024, 1, 1),
        ),
        ComplianceRule(
            rule_id=rule_ids["future"],
            description="Not yet in force",
            required_action=RequiredAction.EDD_REQUIRED,
            action_reason="Takes effect next year",
            effective_from=date(2030, 1, 1),
        ),
    ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_rules(rule_ids: dict[str, str]):
    """Insert this module's rules, then remove exactly those rules again.

    Module-scoped because the tests only read. Each session is opened and closed
    inside this fixture rather than held across the ``yield``: fixtures and tests
    run on different event loops here, and an asyncpg connection cannot be used
    from a loop other than the one that created it.
    """
    async with database.AsyncSessionLocal() as session:
        for rule in _rules(rule_ids):
            session.add(rule)
        await session.commit()

    try:
        yield rule_ids
    finally:
        # Put the shared database back the way this suite found it. Deleting by
        # the minted ids leaves any other rules — real or another suite's —
        # untouched.
        async with database.AsyncSessionLocal() as session:
            await session.execute(
                delete(ComplianceRule).where(ComplianceRule.rule_id.in_(rule_ids.values()))
            )
            await session.commit()

            leaked = await session.execute(
                select(ComplianceRule.rule_id).where(
                    ComplianceRule.rule_id.in_(rule_ids.values())
                )
            )
            assert leaked.scalars().all() == [], (
                "fixture rules survived the cleanup; the shared test database is "
                "still holding this suite's rows"
            )


@pytest_asyncio.fixture(loop_scope="function")
async def repository(seeded_rules):
    """A repository on a session belonging to the running test's own event loop."""
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemyComplianceRuleRepository(session)


async def _by_id(repository, rule_id: str) -> ComplianceRule:
    rules = await repository.list_rules()
    match = [rule for rule in rules if rule.rule_id == rule_id]
    assert len(match) == 1, f"expected exactly one {rule_id}, got {len(match)}"
    return match[0]


# ── list_rules ────────────────────────────────────────────────────────────────


async def test_list_rules_returns_the_seeded_rules(repository, seeded_rules):
    returned = {rule.rule_id for rule in await repository.list_rules()}
    assert set(seeded_rules.values()) <= returned


async def test_list_rules_returns_orm_rows(repository):
    rules = await repository.list_rules()
    assert rules, "expected at least this suite's rules"
    assert all(isinstance(rule, ComplianceRule) for rule in rules)


async def test_list_rules_returns_a_list(repository):
    """The port promises a list, not a lazily-consumed result cursor."""
    assert isinstance(await repository.list_rules(), list)


# ── no filtering, no effectivity ──────────────────────────────────────────────


async def test_an_expired_rule_is_returned(repository, seeded_rules):
    """Effectivity is the caller's decision. A repository that hid a lapsed rule
    would also hide it from a settlement backdated to while it was in force."""
    rule = await _by_id(repository, seeded_rules["expired"])
    assert rule.effective_to is not None and rule.effective_to < AS_OF


async def test_a_rule_not_yet_in_force_is_returned(repository, seeded_rules):
    rule = await _by_id(repository, seeded_rules["future"])
    assert rule.effective_from > AS_OF


# ── column round trips ────────────────────────────────────────────────────────


async def test_unset_match_conditions_round_trip_as_none(repository, seeded_rules):
    rule = await _by_id(repository, seeded_rules["unconstrained"])
    assert rule.corridor_match is None
    assert rule.sector_risk_tier_match is None
    assert rule.sector_classification_label_match is None
    assert rule.purpose_code_category_match is None
    assert rule.amount_threshold is None
    assert rule.amount_threshold_currency is None
    assert rule.effective_to is None


async def test_match_conditions_round_trip(repository, seeded_rules):
    rule = await _by_id(repository, seeded_rules["tiered"])
    assert rule.corridor_match == "US_IN"
    assert rule.sector_classification_label_match == "DNFBP"
    assert rule.purpose_code_category_match == "trade"


async def test_sector_risk_tier_round_trips_as_the_domain_enum(repository, seeded_rules):
    """The tier column reuses sector_risk_tier_enum, so the value Postgres returns
    must be the sector registry's own RiskTier and not a bare string."""
    rule = await _by_id(repository, seeded_rules["tiered"])
    assert rule.sector_risk_tier_match is RiskTier.HIGH
    assert rule.sector_risk_tier_match == "high"


async def test_required_action_round_trips_as_the_domain_enum(repository, seeded_rules):
    rule = await _by_id(repository, seeded_rules["tiered"])
    assert rule.required_action is RequiredAction.EDD_REQUIRED
    assert rule.required_action == "edd_required"


async def test_a_threshold_round_trips_with_its_currency(repository, seeded_rules):
    """The pair is what makes a threshold comparable — an amount alone is a number
    in no asset, which ck_compliance_rule_threshold_paired exists to forbid."""
    rule = await _by_id(repository, seeded_rules["threshold"])
    assert rule.amount_threshold == 5_000_000
    assert rule.amount_threshold_currency == "USD"


async def test_effectivity_survives_postgres_date_columns(repository, seeded_rules):
    rule = await _by_id(repository, seeded_rules["expired"])
    assert rule.effective_from == date(2020, 1, 1)
    assert rule.effective_to == date(2024, 1, 1)


# ── read-only ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["create", "add", "update", "delete", "save"])
def test_repository_exposes_no_write_methods(method):
    assert not hasattr(SQLAlchemyComplianceRuleRepository, method), (
        f"SQLAlchemyComplianceRuleRepository must not expose {method}() — the rule "
        "registry is written only by its GitOps seed loader"
    )
