"""Direct-SQL tests for ``onboarding_0013_shared_history``.

The table stopped being "the lifecycle history" and became the shared CRM
history log: one row for every change to a company's journey, any of its three
gauges, its marker or any of its deals. These tests assert that against Postgres
rather than through the ORM, following the convention the rest of this module
uses (BUILD.md #12: every DB constraint gets a test that violates it via direct
SQL).

What is deliberately **not** here: the `upgrade -> downgrade -> upgrade` round
trip. Running Alembic inside the suite would drop `dimension`, `deal_id` and
`reason` out from under every other test that writes history, making the whole
run order-dependent for a property that belongs to migration time. It is
verified by the command sequence in `docs/contracts/migration-register.md` §4
and was run against live Postgres for this migration. The single-head assertion
is already owned by `tests/contract/test_migration_discovery.py`.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest

from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.platform.configuration.config import get_settings

SCHEMA = "onboarding"
TABLE = "exporter_lifecycle_history"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _fetchall(query: str, params: tuple = ()):
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _insert_row(*, dimension: str, deal_id: str | None = None, reason: str | None = None) -> str:
    """Write one history row straight into the table and return its id."""
    row_id = str(uuid.uuid4())
    conn = _connect()
    cur = conn.cursor()
    try:
        # Since 0014 a history row must name a company that exists.
        company_id = insert_company(cur)
        cur.execute(
            f"INSERT INTO {SCHEMA}.{TABLE} "
            "(id, customer_id, dimension, deal_id, event_type, from_status, "
            " to_status, actor_id, reason) "
            "VALUES (%s, %s, %s, %s, 'test_transition', 'A', 'B', 'tester', %s)",
            (row_id, str(company_id), dimension, deal_id, reason),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return row_id


# ── 1. Columns ───────────────────────────────────────────────────────────────


def test_the_three_new_columns_exist_with_the_contracted_types():
    columns = {
        name: (data_type, is_nullable)
        for name, data_type, is_nullable in _fetchall(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (SCHEMA, TABLE),
        )
    }

    assert columns["dimension"] == ("character varying", "NO")
    assert columns["deal_id"] == ("uuid", "YES")
    assert columns["reason"] == ("text", "YES")


def test_dimension_is_32_characters_wide():
    (width,) = _fetchall(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = 'dimension'",
        (SCHEMA, TABLE),
    )[0]
    assert width == 32


def test_dimension_has_no_database_default():
    """The default existed only for the length of the backfill.

    Leaving `DEFAULT 'journey'` in place would mean a writer that forgot its
    dimension silently recorded a journey move — the exact failure the column
    exists to prevent. Without it, the insert fails loudly.
    """
    (default,) = _fetchall(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = 'dimension'",
        (SCHEMA, TABLE),
    )[0]
    assert default is None


def test_an_insert_without_a_dimension_is_refused():
    conn = _connect()
    cur = conn.cursor()
    try:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(id, customer_id, event_type, to_status) "
                "VALUES (%s, %s, 'x', 'B')",
                (str(uuid.uuid4()), str(uuid.uuid4())),
            )
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def test_the_original_columns_are_untouched():
    """0013 adds; it does not rename or retype.

    `from_status`/`to_status` now carry values that are not journey statuses,
    and `from_value`/`to_value` would read better — but renaming them would
    touch every writer and reader, so the contract keeps the names.
    """
    columns = {
        name: data_type
        for name, data_type in _fetchall(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (SCHEMA, TABLE),
        )
    }
    assert columns["from_status"] == "character varying"
    assert columns["to_status"] == "character varying"
    assert columns["customer_id"] == "uuid"
    assert columns["actor_id"] == "character varying"
    assert columns["event_metadata"] == "jsonb"
    assert columns["created_at"] == "timestamp with time zone"


def test_values_are_strings_not_enums():
    """A gauge value added tomorrow must be recordable today.

    If `dimension`, `from_status` or `to_status` were Postgres enums, every new
    gauge value would need a migration against the history table before it
    could be written, and removing a value would destroy the history of it.
    Asserting the column is not `USER-DEFINED` is how that stays true.
    """
    types = {
        name: data_type
        for name, data_type in _fetchall(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "AND column_name IN ('dimension', 'from_status', 'to_status')",
            (SCHEMA, TABLE),
        )
    }
    assert set(types.values()) == {"character varying"}


@pytest.mark.parametrize(
    "dimension",
    ["journey", "qualification", "conversation", "background_check", "deal", "marker"],
)
def test_every_contracted_dimension_can_be_recorded(dimension: str):
    """No migration needed to start writing a new dimension — the point of
    keeping the column a varchar."""
    row_id = _insert_row(dimension=dimension)
    stored = _fetchall(f"SELECT dimension FROM {SCHEMA}.{TABLE} WHERE id = %s", (row_id,))
    assert stored == [(dimension,)]


def test_a_deal_row_carries_its_deal_and_reason():
    deal_id = str(uuid.uuid4())
    row_id = _insert_row(dimension="deal", deal_id=deal_id, reason="buyer withdrew")

    stored = _fetchall(
        f"SELECT deal_id::text, reason FROM {SCHEMA}.{TABLE} WHERE id = %s", (row_id,)
    )
    assert stored == [(deal_id, "buyer withdrew")]


# ── 2. Indexes ───────────────────────────────────────────────────────────────


def _index_names() -> set[str]:
    return {
        name
        for (name,) in _fetchall(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = %s",
            (SCHEMA, TABLE),
        )
    }


def test_the_two_new_indexes_exist():
    names = _index_names()
    assert "ix_exporter_lifecycle_history_dimension_recent" in names
    assert "ix_exporter_lifecycle_history_deal_recent" in names


def test_the_three_original_indexes_survive():
    """0011's indexes are not collateral damage.

    `ix_..._to_status` in particular serves the ANER-4.2-S1T2 completion hook,
    which polls for `COMPLIANCE_REVIEW -> ONBOARDED` and would sequential-scan
    the whole history on every poll without it.
    """
    names = _index_names()
    assert "ix_exporter_lifecycle_history_customer_id" in names
    assert "ix_exporter_lifecycle_history_recent" in names
    assert "ix_exporter_lifecycle_history_to_status" in names


def test_the_dimension_index_matches_the_query_it_serves():
    """Column order and direction, so Postgres satisfies the ordering from the
    index instead of sorting: `(customer_id, dimension, created_at DESC, id DESC)`."""
    (definition,) = _fetchall(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = %s",
        (SCHEMA, "ix_exporter_lifecycle_history_dimension_recent"),
    )[0]
    assert "customer_id, dimension, created_at DESC, id DESC" in definition


def test_the_deal_index_is_partial():
    """`deal_id` is NULL on every company-level row, and always will be on most
    of them. Indexing those NULLs would double the index for entries no query
    can use."""
    (definition,) = _fetchall(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = %s",
        (SCHEMA, "ix_exporter_lifecycle_history_deal_recent"),
    )[0]
    assert "WHERE (deal_id IS NOT NULL)" in definition


# ── 3. The backfill ──────────────────────────────────────────────────────────


def test_no_history_row_has_a_null_dimension():
    """Every row that predated 0013 recorded a move of
    `exporter_profile.lifecycle_status`, so `journey` is the correct value for
    all of them rather than a placeholder."""
    (nulls,) = _fetchall(f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE dimension IS NULL")[0]
    assert nulls == 0


def test_history_written_before_this_migration_still_exists():
    """The backfill is `ADD COLUMN ... DEFAULT`, which fills rows in place.

    A migration that truncated and rebuilt the table would satisfy every other
    assertion in this file while destroying the record it exists to keep.
    """
    (total,) = _fetchall(f"SELECT count(*) FROM {SCHEMA}.{TABLE}")[0]
    assert total > 0

    (journeys,) = _fetchall(
        f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE dimension = 'journey'"
    )[0]
    assert journeys > 0


def test_the_lifecycle_writer_names_its_dimension():
    """`ExporterProfileService._record_lifecycle` must pass `journey` now that
    the column has no default — otherwise every profile creation would fail on
    a NOT NULL violation."""
    rows = _fetchall(
        f"SELECT count(*) FROM {SCHEMA}.{TABLE} "
        "WHERE event_type IN ('lifecycle_initial', 'lifecycle_transition') "
        "AND dimension <> 'journey'"
    )
    assert rows == [(0,)]


# ── 4 & 5. The table is still append-only ────────────────────────────────────


def test_the_database_refuses_to_update_a_history_row():
    """`trg_exporter_lifecycle_history_append_only` survives 0013.

    The migration deliberately never issues an UPDATE against this table — the
    backfill is DDL for exactly this reason — so the guard was never dropped
    and recreated, and there was no window in which history was editable.
    """
    row_id = _insert_row(dimension="journey")

    conn = _connect()
    cur = conn.cursor()
    try:
        with pytest.raises(psycopg2.errors.RaiseException) as exc:
            cur.execute(
                f"UPDATE {SCHEMA}.{TABLE} SET to_status = 'TAMPERED' WHERE id = %s",
                (row_id,),
            )
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    assert "immutable" in str(exc.value).lower()


def test_the_database_refuses_to_update_the_new_columns_too():
    """The guard is whole-table, so `dimension`, `deal_id` and `reason` are as
    unchangeable as everything else — a row cannot be quietly re-filed under a
    different gauge after the fact."""
    row_id = _insert_row(dimension="deal", reason="original reason")

    conn = _connect()
    cur = conn.cursor()
    try:
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(
                f"UPDATE {SCHEMA}.{TABLE} SET dimension = 'journey', reason = 'rewritten' "
                "WHERE id = %s",
                (row_id,),
            )
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    stored = _fetchall(f"SELECT dimension, reason FROM {SCHEMA}.{TABLE} WHERE id = %s", (row_id,))
    assert stored == [("deal", "original reason")]


def test_the_database_refuses_to_delete_a_history_row():
    row_id = _insert_row(dimension="journey")

    conn = _connect()
    cur = conn.cursor()
    try:
        with pytest.raises(psycopg2.errors.RaiseException) as exc:
            cur.execute(f"DELETE FROM {SCHEMA}.{TABLE} WHERE id = %s", (row_id,))
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    assert "immutable" in str(exc.value).lower()
    assert _fetchall(f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE id = %s", (row_id,)) == [(1,)]
