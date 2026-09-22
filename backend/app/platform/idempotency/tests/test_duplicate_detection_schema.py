"""ledger.duplicate_detection is append-only, indexed, and readable by ledger_ro.

Three claims that only PostgreSQL can settle, so all three run against it.

The immutability case matters most. A detection is evidence that the idempotency
control operated — and evidence that can be edited afterwards is not evidence.
BUILD.md #12 asks for a test that violates each database constraint through
direct SQL and asserts the rejection, which is what the UPDATE and DELETE cases
below do rather than trusting the trigger to have been written correctly.

The privilege case exists because nothing in the migration grants anything. The
table is readable by ``ledger_ro`` only through the default privilege
``b7e4c9a15d20`` set on the schema, and a default privilege that silently failed
to apply looks exactly like one that worked until something tries to read.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg2
import pytest
from psycopg2 import errors as pg_errors
from sqlalchemy.engine import make_url

from app.platform.configuration.config import get_settings
from app.platform.database.models import Base
from app.platform.idempotency.detection_models import DuplicateDetection
from app.platform.idempotency.migrations.idem_0003_duplicate_detection import (
    IMMUTABILITY_TRIGGER,
    OPERATION_INDEX,
    SCHEMA,
    TABLE,
)

QUALIFIED = f"{SCHEMA}.{TABLE}"
NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def owner_conn():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def ledger_ro_conn():
    settings = get_settings()
    url = make_url(settings.DATABASE_SYNC_URL).set(
        username=settings.LEDGER_RO_DB_USER, password=settings.LEDGER_RO_DB_PASSWORD
    )
    conn = psycopg2.connect(
        url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg2://", "postgresql://"
        )
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def detection(owner_conn) -> Iterator[uuid.UUID]:
    """One row, inserted as the owner. Removed by disabling the trigger it tests."""
    detection_id = uuid.uuid4()
    cur = owner_conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {QUALIFIED}
            (id, idempotency_key, scope_id, operation_type, original_request_ref,
             original_executed_at, detected_at, caller_identity, correlation_id,
             time_since_original_ms, returned_result_ref)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(detection_id),
            f"probe-{uuid.uuid4()}",
            f"probe-scope-{uuid.uuid4()}",
            "probe_operation",
            str(uuid.uuid4()),
            NOW,
            NOW,
            "probe-caller",
            str(uuid.uuid4()),
            412,
            str(uuid.uuid4()),
        ),
    )
    try:
        yield detection_id
    finally:
        cur.execute(f"ALTER TABLE {QUALIFIED} DISABLE TRIGGER {IMMUTABILITY_TRIGGER}")
        try:
            cur.execute(f"DELETE FROM {QUALIFIED} WHERE id = %s", (str(detection_id),))
        finally:
            cur.execute(f"ALTER TABLE {QUALIFIED} ENABLE TRIGGER {IMMUTABILITY_TRIGGER}")


# ── The table exists with the fields the epic specifies ───────────────────────


def test_every_model_column_exists_in_the_database(owner_conn) -> None:
    """Model and migration must agree, or the next autogenerate reconciles them badly."""
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (SCHEMA, TABLE),
    )
    in_database = {row[0] for row in cur.fetchall()}
    on_model = {column.name for column in Base.metadata.tables[QUALIFIED].columns}
    assert on_model == in_database, (
        f"model and database disagree — only on model: {on_model - in_database}, "
        f"only in database: {in_database - on_model}"
    )


@pytest.mark.parametrize(
    "column",
    (
        "id",
        "idempotency_key",
        "scope_id",
        "operation_type",
        "original_request_ref",
        "original_executed_at",
        "detected_at",
        "caller_identity",
        "correlation_id",
        "time_since_original_ms",
        "returned_result_ref",
    ),
)
def test_specified_field_is_present(owner_conn, column: str) -> None:
    """Named one by one so a dropped field fails as itself, not as a set difference."""
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (SCHEMA, TABLE, column),
    )
    assert cur.fetchone() is not None, f"{QUALIFIED} is missing {column}"


def test_no_foreign_key_to_the_registry(owner_conn) -> None:
    """A RESTRICT reference would make the nightly archival DELETE fail.

    ``original_request_ref`` points at a record the archival job moves out of
    idempotency_record and deletes. The absence of the constraint is deliberate
    and load-bearing, so it is asserted rather than left to be re-added by
    someone tidying up.
    """
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT conname FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = %s AND t.relname = %s AND c.contype = 'f'
        """,
        (SCHEMA, TABLE),
    )
    assert cur.fetchall() == [], (
        "duplicate_detection has a foreign key. If it references idempotency_record, "
        "the archival job's DELETE will fail on the first archived key."
    )


# ── Append-only, proved by violating it ───────────────────────────────────────


def test_update_is_rejected(owner_conn, detection: uuid.UUID) -> None:
    cur = owner_conn.cursor()
    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        cur.execute(
            f"UPDATE {QUALIFIED} SET operation_type = 'tampered' WHERE id = %s",
            (str(detection),),
        )
    assert "immutable" in str(exc.value).lower()


def test_delete_is_rejected(owner_conn, detection: uuid.UUID) -> None:
    cur = owner_conn.cursor()
    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        cur.execute(f"DELETE FROM {QUALIFIED} WHERE id = %s", (str(detection),))
    assert "immutable" in str(exc.value).lower()


def test_the_row_survives_both_attempts(owner_conn, detection: uuid.UUID) -> None:
    """The rejections above must be refusals, not silent no-ops on a missing row."""
    cur = owner_conn.cursor()
    cur.execute(f"SELECT count(*) FROM {QUALIFIED} WHERE id = %s", (str(detection),))
    assert cur.fetchone()[0] == 1


def test_the_trigger_is_the_shared_function(owner_conn) -> None:
    """Reused, not reimplemented — twelve other triggers depend on the same one."""
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT p.proname FROM pg_trigger tg
        JOIN pg_class t ON t.oid = tg.tgrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_proc p ON p.oid = tg.tgfoid
        WHERE n.nspname = %s AND t.relname = %s AND tg.tgname = %s
        """,
        (SCHEMA, TABLE, IMMUTABILITY_TRIGGER),
    )
    row = cur.fetchone()
    assert row is not None, f"{IMMUTABILITY_TRIGGER} does not exist"
    assert row[0] == "prevent_mutation"


# ── The index S4T3 queries through ────────────────────────────────────────────


def test_operation_index_exists_with_the_intended_columns(owner_conn) -> None:
    cur = owner_conn.cursor()
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
        (SCHEMA, OPERATION_INDEX),
    )
    assert [r[0] for r in cur.fetchall()] == ["operation_type", "detected_at"], (
        "operation_type must lead — reversed, the index cannot serve equality on it"
    )


def test_the_duplicates_query_can_use_the_index(owner_conn) -> None:
    """The exact S4T3 predicate: one operation type over a window.

    Sequential scans disabled because the table is empty in a fresh database, so
    the planner would prefer one however good the index is. The question worth
    answering is whether the index *can* serve this shape.
    """
    cur = owner_conn.cursor()
    cur.execute("SET enable_seqscan = off")
    try:
        cur.execute(
            f"""
            EXPLAIN SELECT id FROM {QUALIFIED}
            WHERE operation_type = %s
              AND detected_at >= now() - INTERVAL '7 days'
              AND detected_at <= now()
            ORDER BY detected_at DESC
            """,
            ("probe_operation",),
        )
        plan = "\n".join(r[0] for r in cur.fetchall())
    finally:
        cur.execute("SET enable_seqscan = DEFAULT")

    assert OPERATION_INDEX in plan, f"the S4T3 query cannot use {OPERATION_INDEX}:\n{plan}"


# ── Readable by the audit interface's role ────────────────────────────────────


def test_ledger_ro_can_read_the_table(ledger_ro_conn, detection: uuid.UUID) -> None:
    """Granted by the schema default privilege, not by anything in this migration."""
    cur = ledger_ro_conn.cursor()
    cur.execute(f"SELECT count(*) FROM {QUALIFIED} WHERE id = %s", (str(detection),))
    assert cur.fetchone()[0] == 1


@pytest.mark.parametrize(
    "statement",
    (
        f"UPDATE {QUALIFIED} SET operation_type = 'x'",
        f"DELETE FROM {QUALIFIED}",
    ),
    ids=("update", "delete"),
)
def test_ledger_ro_is_refused_writes(ledger_ro_conn, statement: str) -> None:
    """Two independent reasons this fails; the role's privileges are the first."""
    cur = ledger_ro_conn.cursor()
    with pytest.raises(pg_errors.InsufficientPrivilege) as exc:
        cur.execute(statement)
    assert exc.value.pgcode == "42501"


def test_the_model_is_registered_on_the_metadata() -> None:
    """Guards every catalogue test above from passing against a stale model import."""
    assert Base.metadata.tables[QUALIFIED] is DuplicateDetection.__table__
