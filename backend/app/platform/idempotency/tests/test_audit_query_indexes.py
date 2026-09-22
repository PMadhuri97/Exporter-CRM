"""The scope-and-date indexes exist, are valid, and the audit query can use them.

An index that exists proves very little. Three things can go wrong that a
catalogue lookup alone would miss, so each gets its own case: a concurrent build
can fail and leave an INVALID index the planner silently ignores; the column
order can be wrong, which still produces a usable-looking index that cannot
serve a range on the second column; and the model can drift from the migration,
so the database has an index that SQLAlchemy's metadata does not know about.

Plan assertions run with ``enable_seqscan`` off. On a table holding a handful of
test rows a sequential scan is genuinely the cheaper plan, so the planner would
choose it however good the index is. Disabling it asks the question actually
worth answering — *can* this index serve this query shape — rather than the one
that only reflects how much data happens to be present.
"""

from __future__ import annotations

import ast
import pathlib

import psycopg2
import pytest

from app.platform.configuration.config import get_settings
from app.platform.database.models import Base
from app.platform.idempotency.migrations.idem_0002_audit_query_indexes import (
    AUDIT_QUERY_INDEXES,
    SCHEMA,
)

MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "idem_0002_audit_query_indexes.py"
)


@pytest.fixture(scope="module")
def conn():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    connection = psycopg2.connect(url)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def migration_source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


# ── The indexes are present, valid, and shaped as intended ────────────────────


@pytest.mark.parametrize(("name", "table", "columns"), AUDIT_QUERY_INDEXES)
def test_index_exists_and_is_valid(conn, name: str, table: str, columns: list[str]) -> None:
    """A failed CREATE INDEX CONCURRENTLY leaves an INVALID index behind.

    It is present in the catalogue, is never used by the planner, and is not
    replaced by re-running the migration. Asserting only on existence would
    treat that state as success.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ix.indisvalid, ix.indisready
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = i.relnamespace
        WHERE n.nspname = %s AND i.relname = %s
        """,
        (SCHEMA, name),
    )
    row = cur.fetchone()
    assert row is not None, (
        f"{SCHEMA}.{name} does not exist — idem_0002 has not been applied to this database"
    )
    indisvalid, indisready = row
    assert indisvalid, (
        f"{name} exists but is INVALID, which means a concurrent build failed part-way. "
        f"The planner will never use it. Downgrade and upgrade to rebuild."
    )
    assert indisready, f"{name} exists but is not ready for inserts"


@pytest.mark.parametrize(("name", "table", "columns"), AUDIT_QUERY_INDEXES)
def test_index_columns_are_in_the_intended_order(
    conn, name: str, table: str, columns: list[str]
) -> None:
    """scope_id must lead. Reversed, the index cannot serve equality on scope."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = i.relnamespace
        JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
        WHERE n.nspname = %s AND i.relname = %s
        ORDER BY k.ord
        """,
        (SCHEMA, name),
    )
    assert [r[0] for r in cur.fetchall()] == columns


@pytest.mark.parametrize(("name", "table", "columns"), AUDIT_QUERY_INDEXES)
def test_model_metadata_declares_the_index(name: str, table: str, columns: list[str]) -> None:
    """The migration and the model must agree, or the next autogenerate drops it.

    A migration that creates an index the model does not declare leaves the
    database ahead of the metadata; Alembic's autogenerate then reads that as an
    index to remove, and a later revision quietly deletes it.
    """
    metadata_table = Base.metadata.tables[f"{SCHEMA}.{table}"]
    declared = {
        str(index.name): [c.name for c in index.columns]
        for index in metadata_table.indexes
    }
    assert name in declared, (
        f"{table} is missing {name} in its __table_args__; the migration creates an "
        f"index the model does not know about"
    )
    assert declared[name] == columns


# ── The planner can actually use them ─────────────────────────────────────────


PROBE_OPERATION = "probe_audit_query_index"
PROBE_ROWS = 4000
PROBE_SCOPES = 200


@pytest.fixture(scope="module")
def populated(conn):
    """Enough rows, spread over enough scopes and dates, for the planner to have an opinion.

    On an empty table every index costs about the same and the planner picks
    more or less arbitrarily — it chose the pre-existing (key_value, scope_id)
    index for a scope-only predicate, by scanning the whole index. That plan is
    correct and would be ruinous at archive scale, so asserting against it on
    empty tables would have proved nothing either way. Real statistics are what
    turn "an index exists" into "the planner prefers it".
    """
    cur = conn.cursor()
    for table, extra_columns, extra_values in (
        ("idempotency_record", "", ""),
        ("idempotency_archive", ", archived_at", ", now()"),
    ):
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.{table}
                (id, key_value, scope_id, key_type, operation_type, status,
                 first_seen_at{extra_columns})
            SELECT gen_random_uuid(), %s || g, %s || (g %% {PROBE_SCOPES}),
                   'customer_key', %s, 'completed',
                   now() - ((g %% 365) * INTERVAL '1 day'){extra_values}
            FROM generate_series(1, {PROBE_ROWS}) g
            """,
            (f"{PROBE_OPERATION}-key-", f"{PROBE_OPERATION}-scope-", PROBE_OPERATION),
        )
        cur.execute(f"ANALYZE {SCHEMA}.{table}")

    yield f"{PROBE_OPERATION}-scope-7"

    cur.execute(
        "ALTER TABLE ledger.idempotency_archive "
        "DISABLE TRIGGER trigger_idempotency_archive_no_delete"
    )
    for table in ("idempotency_record", "idempotency_archive"):
        cur.execute(
            f"DELETE FROM {SCHEMA}.{table} WHERE operation_type = %s", (PROBE_OPERATION,)
        )
        # Statistics claiming thousands of absent rows would follow this suite
        # into every other test's query plans.
        cur.execute(f"ANALYZE {SCHEMA}.{table}")
    cur.execute(
        "ALTER TABLE ledger.idempotency_archive "
        "ENABLE TRIGGER trigger_idempotency_archive_no_delete"
    )


@pytest.mark.parametrize(("name", "table", "columns"), AUDIT_QUERY_INDEXES)
def test_scope_and_date_query_prefers_the_index(
    conn, populated: str, name: str, table: str, columns: list[str]
) -> None:
    """The union's per-branch predicate, planned against each table separately.

    Nothing is disabled here. The assertion is that this index is the one the
    planner *chooses* on realistic data — an index it merely tolerates is an
    index that is costing write throughput for nothing.
    """
    cur = conn.cursor()
    cur.execute(
        f"""
        EXPLAIN SELECT id FROM {SCHEMA}.{table}
        WHERE scope_id = ANY(%s)
          AND first_seen_at >= now() - INTERVAL '30 days'
          AND first_seen_at <= now()
        ORDER BY first_seen_at, id
        """,
        ([populated],),
    )
    plan = "\n".join(r[0] for r in cur.fetchall())
    assert name in plan, (
        f"the scope-and-date query on {table} does not choose {name}, so the index is not "
        f"serving the access path it was added for:\n{plan}"
    )


# ── BUILD.md #14: concurrent build, retryable downgrade ───────────────────────


def test_indexes_are_built_concurrently(migration_source: str) -> None:
    """The plain form locks the table for the whole build, which on these tables is an outage."""
    assert "postgresql_concurrently=True" in migration_source
    assert "autocommit_block" in migration_source, (
        "CREATE INDEX CONCURRENTLY cannot run inside a transaction block, so it must be "
        "issued inside op.get_context().autocommit_block()"
    )


def test_downgrade_drops_if_exists(migration_source: str) -> None:
    """A failed concurrent build must be recoverable by downgrade-then-upgrade."""
    tree = ast.parse(migration_source)
    downgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    body = ast.unparse(downgrade)
    assert "if_exists=True" in body, (
        "downgrade() must drop by name IF EXISTS, or an INVALID index left by a failed "
        "concurrent build has to be cleaned up by hand before a retry can work"
    )
    assert "postgresql_concurrently=True" in body, (
        "DROP INDEX must also be concurrent, or the downgrade takes the exclusive lock "
        "the upgrade was written to avoid"
    )
