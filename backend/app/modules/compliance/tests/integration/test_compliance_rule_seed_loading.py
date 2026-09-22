from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.compliance.domain.entities.compliance_rule import (
    ComplianceRule,
    RequiredAction,
)
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.infrastructure.compliance_rule_repository import (
    SQLAlchemyComplianceRuleRepository,
)
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR,
    load_compliance_rules,
)
from app.platform.database import services as database

REAL_RULE = "DNFBP_EDD_REQUIRED"

FIXTURE_RULES = [
    "TIERED_RULE",
    "LOWER_CASE_RULE",
    "PADDED_RULE",
    "EXPIRED_RULE",
    "UNCONSTRAINED_RULE",
    "LIMITS_RULE",
]

RULES_YAML = """
- rule_id: TIERED_RULE
  description: "Matches on the sector registry's own tier vocabulary"
  sector_risk_tier_match: high
  sector_classification_label_match: DNFBP
  required_action: edd_required
  action_reason: "High-risk sector under FATF Recommendation 22"
  effective_from: 2024-01-01

# Identifiers written in lower case on purpose: the loader upper-cases the ones
# that are later matched exactly.
- rule_id: lower_case_rule
  description: "Corridor and currency written in lower case on purpose"
  corridor_match: us_in
  amount_threshold: 5000000
  amount_threshold_currency: usd
  required_action: manual_review
  action_reason: "Large-value settlement on the US-India corridor"
  effective_from: 2024-01-01

# Padded on purpose. The label keeps its casing and loses only the padding: it is
# compared against sector_risk_classification.classification_label, which its own
# loader also stores as written.
- rule_id: "  PADDED_RULE  "
  description: "  Padded on purpose  "
  sector_classification_label_match: "  MixedCase  "
  required_action: enhanced_monitoring
  action_reason: "  Ongoing monitoring for a locally designated sector  "
  effective_from: 2024-01-01

- rule_id: EXPIRED_RULE
  description: "Superseded rule"
  corridor_match: US_IN
  required_action: manual_review
  action_reason: "Superseded by a later rule but still governs settlements raised while in force"
  effective_from: 2020-01-01
  effective_to: 2024-01-01

- rule_id: UNCONSTRAINED_RULE
  description: "Sets no match condition"
  required_action: enhanced_monitoring
  action_reason: "Baseline monitoring applied to every settlement"
  effective_from: 2024-01-01

# The fourth action. Present to prove a rule requiring it needs nothing but a
# seed row — no enum edit, no evaluator change.
- rule_id: LIMITS_RULE
  description: "Re-check limits for an elevated sector"
  sector_risk_tier_match: elevated
  required_action: enhanced_limits_check
  action_reason: "Sector risk warrants a limits re-check before release"
  effective_from: 2024-01-01
"""

#: A single rule, for proving that a reload replaces rather than accumulates.
REPLACEMENT_YAML = """
- rule_id: ONLY_SURVIVOR
  description: "The one rule left after the registry is rewritten"
  required_action: manual_review
  action_reason: "The only rule in force after the reference data was rewritten"
  effective_from: 2024-01-01
"""

#: required_action names an action that does not exist.
INVALID_YAML = """
- rule_id: BROKEN_RULE
  description: "Names an action that does not exist"
  required_action: freeze_the_account
  action_reason: "Whatever this rule intended, the platform cannot express it"
  effective_from: 2024-01-01
"""


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory):
    """The fixture registry on disk, in the layout the loader expects."""
    path = tmp_path_factory.mktemp("rules")
    (path / "compliance-rules.yaml").write_text(RULES_YAML)
    return path


@pytest.fixture(scope="module")
def replacement_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("rules_replacement")
    (path / "compliance-rules.yaml").write_text(REPLACEMENT_YAML)
    return path


@pytest.fixture(scope="module")
def invalid_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("rules_invalid")
    (path / "compliance-rules.yaml").write_text(INVALID_YAML)
    return path


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_rules(seed_dir):
    """Install the fixture registry for this module, then restore the real one.

    Module-scoped because the load is a full table rewrite and most tests only
    read. Each session is opened and closed inside this fixture rather than held
    across the ``yield``: fixtures and tests run on different event loops here,
    and an asyncpg connection cannot be used from a loop other than the one that
    created it.
    """
    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, seed_dir)

    try:
        yield seed_dir
    finally:
        async with database.AsyncSessionLocal() as session:
            await load_compliance_rules(session, SEED_DATA_DIR)

            restored = await session.execute(
                select(ComplianceRule.rule_id).where(ComplianceRule.rule_id == REAL_RULE)
            )
            assert restored.scalar_one_or_none() == REAL_RULE, (
                "GitOps seed data was not restored; the shared test database is "
                "still holding this suite's fixture rules"
            )

            leaked = await session.execute(
                select(ComplianceRule.rule_id).where(ComplianceRule.rule_id.in_(FIXTURE_RULES))
            )
            assert leaked.scalars().all() == [], "fixture rules survived the restore"


@pytest_asyncio.fixture(loop_scope="function")
async def repository(seeded_rules):
    """A repository on a session belonging to the running test's own event loop."""
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemyComplianceRuleRepository(session)


@pytest_asyncio.fixture(loop_scope="function")
async def restore_fixture_rules(seeded_rules):
    try:
        yield
    finally:
        async with database.AsyncSessionLocal() as session:
            await load_compliance_rules(session, seeded_rules)


async def _by_id(repository, rule_id: str) -> ComplianceRule:
    rules = await repository.list_rules()
    match = [rule for rule in rules if rule.rule_id == rule_id]
    assert len(match) == 1, f"expected exactly one {rule_id}, got {len(match)}"
    return match[0]


# ── seed loading ──────────────────────────────────────────────────────────────


async def test_seed_data_loads_into_the_table(repository):
    rules = await repository.list_rules()
    assert sorted(rule.rule_id for rule in rules) == sorted(FIXTURE_RULES)


async def test_dates_survive_postgres_date_columns(repository):
    rule = await _by_id(repository, "EXPIRED_RULE")
    assert rule.effective_from == date(2020, 1, 1)
    assert rule.effective_to == date(2024, 1, 1)


async def test_an_open_ended_rule_loads_with_no_end_date(repository):
    assert (await _by_id(repository, "UNCONSTRAINED_RULE")).effective_to is None


async def test_a_rule_with_no_conditions_loads(repository):
    rule = await _by_id(repository, "UNCONSTRAINED_RULE")
    assert rule.corridor_match is None
    assert rule.sector_risk_tier_match is None
    assert rule.sector_classification_label_match is None
    assert rule.purpose_code_category_match is None
    assert rule.amount_threshold is None
    assert rule.amount_threshold_currency is None


# ── enum coercion ─────────────────────────────────────────────────────────────


async def test_the_risk_tier_loads_as_the_sector_registry_enum(repository):
    """The column reuses sector_risk_tier_enum, so a seeded 'high' must come back
    as the registry's own RiskTier rather than as a bare string."""
    assert (await _by_id(repository, "TIERED_RULE")).sector_risk_tier_match is RiskTier.HIGH


async def test_the_required_action_loads_as_its_domain_enum(repository):
    assert (await _by_id(repository, "TIERED_RULE")).required_action is RequiredAction.EDD_REQUIRED


async def test_every_seeded_action_round_trips(repository):
    actions = {rule.rule_id: rule.required_action for rule in await repository.list_rules()}
    assert actions["TIERED_RULE"] is RequiredAction.EDD_REQUIRED
    assert actions["LOWER_CASE_RULE"] is RequiredAction.MANUAL_REVIEW
    assert actions["PADDED_RULE"] is RequiredAction.ENHANCED_MONITORING


async def test_an_unknown_action_fails_the_load(invalid_dir, restore_fixture_rules):
    """Coerced in the loader rather than left to the column, so a mistyped action
    names itself at boot instead of surfacing as a driver error mid-request."""
    with pytest.raises(ValueError, match="freeze_the_account"):
        async with database.AsyncSessionLocal() as session:
            await load_compliance_rules(session, invalid_dir)


# ── normalisation ─────────────────────────────────────────────────────────────


async def test_identifiers_matched_exactly_are_upper_cased(repository):
    """A rule seeded as 'us_in' would load cleanly, satisfy every constraint, and
    then never fire — imposing no obligation and saying nothing about it."""
    rule = await _by_id(repository, "LOWER_CASE_RULE")
    assert rule.corridor_match == "US_IN"
    assert rule.amount_threshold_currency == "USD"


async def test_the_rule_id_is_upper_cased(repository):
    assert (await _by_id(repository, "LOWER_CASE_RULE")).rule_id == "LOWER_CASE_RULE"


async def test_a_rule_requiring_enhanced_limits_check_loads_from_yaml(repository):
    """The action the updated ticket added, arriving the way a real rule would:
    a seed row and nothing else. The loader coerces it through RequiredAction, so
    this fails if the enum, the database type or the column disagree."""
    rule = await _by_id(repository, "LIMITS_RULE")

    assert rule.required_action is RequiredAction.ENHANCED_LIMITS_CHECK
    assert rule.sector_risk_tier_match is RiskTier.ELEVATED


async def test_padding_is_trimmed(repository):
    rule = await _by_id(repository, "PADDED_RULE")
    assert rule.description == "Padded on purpose"
    assert rule.action_reason.startswith("Ongoing monitoring")
    assert rule.action_reason.strip() == rule.action_reason


async def test_the_classification_label_keeps_its_casing(repository):
    assert (await _by_id(repository, "PADDED_RULE")).sector_classification_label_match == "MixedCase"


async def test_a_threshold_loads_as_integer_minor_units(repository):
    rule = await _by_id(repository, "LOWER_CASE_RULE")
    assert rule.amount_threshold == 5_000_000
    assert isinstance(rule.amount_threshold, int)


# ── idempotency and atomicity ─────────────────────────────────────────────────


async def test_reloading_the_same_data_changes_nothing(repository, seeded_rules):
    """Every replica runs this on boot, so the second load must be a no-op rather
    than a duplicate-key failure on uq_compliance_rule_rule_id."""
    before = sorted(rule.rule_id for rule in await repository.list_rules())

    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, seeded_rules)

    async with database.AsyncSessionLocal() as session:
        after = await SQLAlchemyComplianceRuleRepository(session).list_rules()

    assert sorted(rule.rule_id for rule in after) == before


async def test_a_reload_replaces_rather_than_accumulates(replacement_dir, restore_fixture_rules):
    """A rule withdrawn from the YAML must stop governing settlements. Appending
    would leave a retired rule firing forever."""
    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, replacement_dir)

    async with database.AsyncSessionLocal() as session:
        rules = await SQLAlchemyComplianceRuleRepository(session).list_rules()

    assert [rule.rule_id for rule in rules] == ["ONLY_SURVIVOR"]


async def test_a_failed_load_leaves_the_previous_registry_intact(
    invalid_dir, restore_fixture_rules
):
    with pytest.raises(ValueError):
        async with database.AsyncSessionLocal() as session:
            await load_compliance_rules(session, invalid_dir)

    async with database.AsyncSessionLocal() as session:
        surviving = await SQLAlchemyComplianceRuleRepository(session).list_rules()

    assert sorted(rule.rule_id for rule in surviving) == sorted(FIXTURE_RULES)


async def test_the_table_holds_exactly_the_seeded_rules(repository):
    total = await repository.session.execute(select(func.count()).select_from(ComplianceRule))
    assert total.scalar_one() == len(FIXTURE_RULES)
