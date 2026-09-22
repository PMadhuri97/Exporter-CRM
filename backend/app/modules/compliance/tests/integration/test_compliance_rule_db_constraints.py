"""Database-level constraint violation suite for the compliance rule registry.

Raw SQL on purpose (BUILD.md #12): inserting through the ORM would prove only
that SQLAlchemy declares a constraint, not that Postgres enforces one. Every
constraint the migration creates is violated here and asserted rejected, and the
boundary of each is exercised alongside it — a constraint that rejects everything
is as broken as one that rejects nothing.

The test database is shared across a whole run and is never reset, so every test
mints its own rule ids and none may assume an empty table. Nothing here commits:
each test runs inside a transaction the fixture rolls back.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from app.modules.compliance.domain.entities.compliance_rule import RequiredAction
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.tests.integration._helpers import pg_connect, unique_code

UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
NOT_NULL_VIOLATION = "23502"
INVALID_TEXT_REPRESENTATION = "22P02"
STRING_DATA_RIGHT_TRUNCATION = "22001"

INSERT_RULE_SQL = """
    INSERT INTO compliance.compliance_rule
        (id, rule_id, description, corridor_match, sector_risk_tier_match,
         sector_classification_label_match, purpose_code_category_match,
         amount_threshold, amount_threshold_currency, required_action,
         action_reason, effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def rule_params(
    rule_id: str,
    *,
    description: str | None = "constraint-test fixture row",
    corridor_match: str | None = None,
    sector_risk_tier_match: str | None = None,
    sector_classification_label_match: str | None = None,
    purpose_code_category_match: str | None = None,
    amount_threshold: int | None = None,
    amount_threshold_currency: str | None = None,
    required_action: str | None = "manual_review",
    action_reason: str | None = "constraint-test reason",
    effective_from: str | None = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        rule_id,
        description,
        corridor_match,
        sector_risk_tier_match,
        sector_classification_label_match,
        purpose_code_category_match,
        amount_threshold,
        amount_threshold_currency,
        required_action,
        action_reason,
        effective_from,
        effective_to,
    )


@pytest.fixture
def cursor():
    """A cursor on an explicit transaction that is always rolled back.

    Yielded rather than returned so the rollback still happens when a test fails
    mid-transaction — a constraint violation leaves the connection in an aborted
    state, and an un-rolled-back connection would hold locks for the rest of the
    session.
    """
    conn = pg_connect()
    try:
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


# ── uq_compliance_rule_rule_id ────────────────────────────────────────────────


def test_rule_id_must_be_unique(cursor):
    rule_id = unique_code("DUP")
    cursor.execute(INSERT_RULE_SQL, rule_params(rule_id))

    with pytest.raises(psycopg2.errors.lookup(UNIQUE_VIOLATION)):
        cursor.execute(INSERT_RULE_SQL, rule_params(rule_id))


def test_rule_id_uniqueness_is_not_relaxed_by_a_different_effectivity_window(cursor):
    """Unlike the sector registry's classifications, a rule id is unique on its
    own: it is the value written to settlement.edd_trigger_rule, and two rows
    answering to one name would make that record ambiguous."""
    rule_id = unique_code("DUP_WINDOW")
    cursor.execute(INSERT_RULE_SQL, rule_params(rule_id, effective_from="2024-01-01"))

    with pytest.raises(psycopg2.errors.lookup(UNIQUE_VIOLATION)):
        cursor.execute(INSERT_RULE_SQL, rule_params(rule_id, effective_from="2025-01-01"))


def test_different_rule_ids_coexist(cursor):
    cursor.execute(INSERT_RULE_SQL, rule_params(unique_code("A")))
    cursor.execute(INSERT_RULE_SQL, rule_params(unique_code("B")))


# ── ck_compliance_rule_threshold_paired ───────────────────────────────────────


def test_an_amount_without_a_currency_is_rejected(cursor):
    """A quantity in no asset is not comparable to a settlement. The rule would
    load cleanly and then never fire, imposing nothing and saying nothing."""
    with pytest.raises(psycopg2.errors.lookup(CHECK_VIOLATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(
                unique_code("AMOUNT_ONLY"),
                amount_threshold=5_000_000,
                amount_threshold_currency=None,
            ),
        )


def test_a_currency_without_an_amount_is_rejected(cursor):
    """The mirror case: a currency alone constrains nothing while looking as
    though it does."""
    with pytest.raises(psycopg2.errors.lookup(CHECK_VIOLATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(
                unique_code("CURRENCY_ONLY"),
                amount_threshold=None,
                amount_threshold_currency="USD",
            ),
        )


def test_both_set_together_is_accepted(cursor):
    cursor.execute(
        INSERT_RULE_SQL,
        rule_params(
            unique_code("PAIRED"),
            amount_threshold=5_000_000,
            amount_threshold_currency="USD",
        ),
    )


def test_neither_set_is_accepted(cursor):
    """A rule that constrains no amount is legitimate — the DNFBP rule that ships
    is exactly that."""
    cursor.execute(
        INSERT_RULE_SQL,
        rule_params(unique_code("NO_THRESHOLD"), amount_threshold=None,
                    amount_threshold_currency=None),
    )


def test_a_zero_threshold_is_accepted_by_the_pairing_constraint(cursor):
    """The pairing constraint is about the pair, not the value. Zero is a
    degenerate threshold rather than an absent one, and it is not this
    constraint's business to reject it."""
    cursor.execute(
        INSERT_RULE_SQL,
        rule_params(unique_code("ZERO"), amount_threshold=0, amount_threshold_currency="USD"),
    )


# ── ck_compliance_rule_period ─────────────────────────────────────────────────


def test_a_period_must_not_end_before_it_starts(cursor):
    with pytest.raises(psycopg2.errors.lookup(CHECK_VIOLATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(
                unique_code("BACKWARDS"),
                effective_from="2024-06-01",
                effective_to="2024-01-01",
            ),
        )


def test_a_period_must_not_start_and_end_on_the_same_day(cursor):
    """The range is half-open, so a window that closes on the day it opens
    governs nothing at all."""
    with pytest.raises(psycopg2.errors.lookup(CHECK_VIOLATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(
                unique_code("SAME_DAY"),
                effective_from="2024-01-01",
                effective_to="2024-01-01",
            ),
        )


def test_a_period_of_one_day_is_accepted(cursor):
    """The smallest window that governs anything."""
    cursor.execute(
        INSERT_RULE_SQL,
        rule_params(
            unique_code("ONE_DAY"), effective_from="2024-01-01", effective_to="2024-01-02"
        ),
    )


def test_a_period_may_be_open_ended(cursor):
    cursor.execute(
        INSERT_RULE_SQL, rule_params(unique_code("OPEN"), effective_to=None)
    )


# ── required columns ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "column",
    ["rule_id", "description", "required_action", "action_reason", "effective_from"],
)
def test_required_columns_reject_null(cursor, column):
    # rule_id is the one positional parameter, so it cannot be nulled through
    # the same keyword splat as the rest.
    rule_id = None if column == "rule_id" else unique_code("NULLS")
    overrides = {} if column == "rule_id" else {column: None}

    with pytest.raises(psycopg2.errors.lookup(NOT_NULL_VIOLATION)):
        cursor.execute(INSERT_RULE_SQL, rule_params(rule_id, **overrides))


@pytest.mark.parametrize(
    "column",
    [
        "corridor_match",
        "sector_risk_tier_match",
        "sector_classification_label_match",
        "purpose_code_category_match",
        "effective_to",
    ],
)
def test_optional_columns_accept_null(cursor, column):
    """Every match condition is optional, and a NULL means the rule does not
    constrain that dimension. A NOT NULL here would force every rule to name a
    tier and a corridor it never cared about."""
    cursor.execute(INSERT_RULE_SQL, rule_params(unique_code("OPTIONAL"), **{column: None}))


def test_id_is_the_primary_key(cursor):
    shared_id = str(uuid.uuid4())
    params = list(rule_params(unique_code("PK_A")))
    params[0] = shared_id
    cursor.execute(INSERT_RULE_SQL, tuple(params))

    duplicate = list(rule_params(unique_code("PK_B")))
    duplicate[0] = shared_id
    with pytest.raises(psycopg2.errors.lookup(UNIQUE_VIOLATION)):
        cursor.execute(INSERT_RULE_SQL, tuple(duplicate))


# ── enum columns ──────────────────────────────────────────────────────────────


def test_required_action_must_be_a_known_action(cursor):
    with pytest.raises(psycopg2.errors.lookup(INVALID_TEXT_REPRESENTATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(unique_code("BAD_ACTION"), required_action="freeze_the_account"),
        )


def test_required_action_is_case_sensitive(cursor):
    """The enum's vocabulary is lower case. An upper-case value is a different
    string and Postgres rejects it rather than folding it."""
    with pytest.raises(psycopg2.errors.lookup(INVALID_TEXT_REPRESENTATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(unique_code("UPPER_ACTION"), required_action="MANUAL_REVIEW"),
        )


@pytest.mark.parametrize("action", [member.value for member in RequiredAction])
def test_every_declared_action_is_accepted(cursor, action):
    """Guards against the migration and the Python enum drifting apart: a member
    added to one and not the other fails here."""
    cursor.execute(
        INSERT_RULE_SQL, rule_params(unique_code("ACTION"), required_action=action)
    )


def test_the_risk_tier_column_rejects_an_unknown_tier(cursor):
    with pytest.raises(psycopg2.errors.lookup(INVALID_TEXT_REPRESENTATION)):
        cursor.execute(
            INSERT_RULE_SQL,
            rule_params(unique_code("BAD_TIER"), sector_risk_tier_match="catastrophic"),
        )


@pytest.mark.parametrize("tier", [member.value for member in RiskTier])
def test_every_sector_registry_tier_is_accepted(cursor, tier):
    """The column reuses sector_risk_tier_enum, so every tier the sector registry
    can assign must be expressible as a rule condition. A tier the registry could
    produce but a rule could not match on would be unreachable policy."""
    cursor.execute(
        INSERT_RULE_SQL, rule_params(unique_code("TIER"), sector_risk_tier_match=tier)
    )


def test_the_risk_tier_enum_is_the_one_the_sector_registry_uses(cursor):
    """Named rather than inferred: both columns must resolve to the same pg type,
    or the two vocabularies could drift while every other test still passed."""
    cursor.execute(
        """
        SELECT table_name, udt_schema, udt_name FROM information_schema.columns
        WHERE table_schema = 'compliance'
          AND ((table_name = 'compliance_rule' AND column_name = 'sector_risk_tier_match')
            OR (table_name = 'sector_risk_classification' AND column_name = 'risk_tier'))
        """
    )
    # Qualified by schema, not just name. Two same-named enums in different
    # schemas are two different types, and comparing bare names would report
    # them identical — which is the drift this test exists to catch.
    types = {table: (schema, name) for table, schema, name in cursor.fetchall()}

    assert types["compliance_rule"] == ("compliance", "sector_risk_tier_enum")
    assert types["sector_risk_classification"] == ("compliance", "sector_risk_tier_enum")


# ── column widths and types ───────────────────────────────────────────────────


def test_rule_id_is_bounded(cursor):
    with pytest.raises(psycopg2.errors.lookup(STRING_DATA_RIGHT_TRUNCATION)):
        cursor.execute(INSERT_RULE_SQL, rule_params("X" * 101))


def test_a_rule_id_fits_settlements_edd_trigger_rule_column(cursor):
    """compliance_rule.rule_id is written into settlement.edd_trigger_rule. If
    the source column were the wider of the two, a legal rule id could be
    unrecordable against the settlement it governed."""
    cursor.execute(
        """
        SELECT table_name, character_maximum_length FROM information_schema.columns
        WHERE (table_schema = 'compliance'
               AND table_name = 'compliance_rule' AND column_name = 'rule_id')
           OR (table_schema = 'settlement'
               AND table_name = 'settlement' AND column_name = 'edd_trigger_rule')
        """
    )
    widths = dict(cursor.fetchall())

    assert widths["compliance_rule"] <= widths["settlement"]


def test_the_threshold_holds_an_amount_larger_than_an_integer(cursor):
    """Minor units of a low-precision asset run large. BIGINT, not INTEGER."""
    cursor.execute(
        INSERT_RULE_SQL,
        rule_params(
            unique_code("BIG"),
            amount_threshold=9_000_000_000_000,
            amount_threshold_currency="USD",
        ),
    )


def test_the_orm_and_the_migration_agree_on_every_column(cursor):
    """The ORM mirrors the migration's columns by hand, so the two can disagree
    silently until something reads a column that is not there."""
    from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule

    cursor.execute(
        """
        SELECT column_name, is_nullable FROM information_schema.columns
        WHERE table_schema = 'compliance' AND table_name = 'compliance_rule'
        """
    )
    in_database = {name: nullable == "YES" for name, nullable in cursor.fetchall()}
    in_orm = {
        column.name: column.nullable for column in ComplianceRule.__table__.columns
    }

    assert in_orm == in_database
