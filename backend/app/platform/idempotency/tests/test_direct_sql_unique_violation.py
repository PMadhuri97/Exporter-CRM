"""Direct-SQL constraint tests for uq_idempotency_record_key_scope (BUILD.md #12).

S3T1 replaced the unconditional ``UNIQUE (key_value, scope_id)`` constraint with a PARTIAL
unique index over the live rows only:

    UNIQUE (key_value, scope_id) WHERE status <> 'expired'

That predicate has two halves, and a test of only the first would pass just as happily
against the constraint it replaced:

  * it must still REJECT a second live row for a pair — the idempotency guarantee;
  * it must PERMIT expired rows alongside one another and alongside a live row, which is
    what makes a key registrable again once its window closes, and is the half that is new.

Both are asserted through raw SQL rather than the registration service, because
``register_key`` issues ``ON CONFLICT DO NOTHING`` and would swallow the very violation
this file exists to observe.
"""

import uuid

import psycopg2
import pytest

from app.platform.configuration.config import get_settings

SCHEMA = "ledger"
INDEX_NAME = "uq_idempotency_record_key_scope"
OPERATION = "s3t1_direct_sql_constraint_test"

#: Statuses the partial index covers. Registration only ever writes `active`, but the index
#: predicate is written in terms of "not expired", so the guarantee has to hold for every
#: non-expired status the enum allows.
LIVE_STATUSES = ("active", "completed", "failed")


def _connect():
    """A psycopg2 connection built from application settings.

    Deliberately local rather than reusing app.modules.ledger.tests…pg_connect: platform
    code, tests included, may not import from a module (ARCHITECTURE.md §2, enforced by
    importlinter.ini), and importing that helper breaks the build.
    """
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


@pytest.fixture
def conn():
    """Connection whose rows are removed afterwards, keyed on this suite's operation_type.

    These tests commit deliberately — a UniqueViolation only surfaces on a real write — so
    cleanup cannot rely on rolling back. Deleting by operation_type also clears rows left by
    a test that failed part-way through, which is how stale rows accumulate in shared
    development databases.
    """
    connection = _connect()
    try:
        yield connection
    finally:
        try:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {SCHEMA}.idempotency_record WHERE operation_type = %s",
                    (OPERATION,),
                )
            connection.commit()
        finally:
            connection.close()


def _insert(cur, *, key_value, scope_id, status, key_type="customer_key"):
    """Insert one record directly, bypassing the service layer entirely."""
    record_id = str(uuid.uuid4())
    cur.execute(
        f"""
        INSERT INTO {SCHEMA}.idempotency_record
            (id, key_value, scope_id, key_type, operation_type, status,
             first_seen_at, expires_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, now(), now() + interval '1 hour')
        """,
        (record_id, key_value, scope_id, key_type, OPERATION, status),
    )
    return record_id


# ── Rejecting half: at most one live row per (key_value, scope_id) ────────────────────


@pytest.mark.parametrize("second_status", LIVE_STATUSES)
def test_second_live_row_for_the_same_key_and_scope_is_rejected(conn, second_status):
    """Direct SQL violates the index and PostgreSQL rejects it (BUILD.md #12).

    Parameterised across every non-expired status so the guarantee is shown to rest on the
    index predicate rather than on `active` happening to be what registration writes.
    """
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        _insert(cur, key_value=key_value, scope_id=scope_id, status="active")
    conn.commit()

    with pytest.raises(psycopg2.errors.UniqueViolation) as excinfo:
        with conn.cursor() as cur:
            _insert(cur, key_value=key_value, scope_id=scope_id, status=second_status)
        conn.commit()

    assert INDEX_NAME in str(excinfo.value)
    conn.rollback()


def test_rejection_ignores_key_type(conn):
    """The index covers (key_value, scope_id) only — a different key_type is no escape."""
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        _insert(cur, key_value=key_value, scope_id=scope_id, status="active")
    conn.commit()

    with pytest.raises(psycopg2.errors.UniqueViolation) as excinfo:
        with conn.cursor() as cur:
            _insert(
                cur,
                key_value=key_value,
                scope_id=scope_id,
                status="completed",
                key_type="internal_derived_key",
            )
        conn.commit()

    assert INDEX_NAME in str(excinfo.value)
    conn.rollback()


def test_the_same_key_in_a_different_scope_is_permitted(conn):
    """scope_id is part of the index, so scopes stay independent."""
    key_value = f"key-{uuid.uuid4()}"

    with conn.cursor() as cur:
        first = _insert(cur, key_value=key_value, scope_id=str(uuid.uuid4()), status="active")
        second = _insert(cur, key_value=key_value, scope_id=str(uuid.uuid4()), status="active")
    conn.commit()

    assert first != second


# ── Permitting half: expired rows fall outside the index predicate ────────────────────


def test_two_expired_rows_coexist(conn):
    """Both rows are outside the predicate, so neither constrains the other.

    The pure form of the permitting half — nothing in the pair is covered by the index.
    """
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        first = _insert(cur, key_value=key_value, scope_id=scope_id, status="expired")
        second = _insert(cur, key_value=key_value, scope_id=scope_id, status="expired")
    conn.commit()

    assert first != second

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) FROM {SCHEMA}.idempotency_record
             WHERE key_value = %s AND scope_id = %s AND status = 'expired'
            """,
            (key_value, scope_id),
        )
        assert cur.fetchone()[0] == 2


@pytest.mark.parametrize("live_status", LIVE_STATUSES)
def test_an_expired_row_coexists_with_a_live_row(conn, live_status):
    """The reason the constraint had to become partial.

    Under the unconditional UNIQUE this replaced, the second insert would have raised —
    which is why an expired record used to hold its key for good.
    """
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        _insert(cur, key_value=key_value, scope_id=scope_id, status="expired")
        _insert(cur, key_value=key_value, scope_id=scope_id, status=live_status)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT status::text, count(*)
              FROM {SCHEMA}.idempotency_record
             WHERE key_value = %s AND scope_id = %s
             GROUP BY 1 ORDER BY 1
            """,
            (key_value, scope_id),
        )
        assert dict(cur.fetchall()) == {"expired": 1, live_status: 1}


def test_many_expired_generations_coexist_with_one_live_row(conn):
    """Repeated expiry and reuse accumulates history; the index constrains live rows only."""
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        for _ in range(5):
            _insert(cur, key_value=key_value, scope_id=scope_id, status="expired")
        _insert(cur, key_value=key_value, scope_id=scope_id, status="active")
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) FILTER (WHERE status = 'expired'),
                   count(*) FILTER (WHERE status <> 'expired')
              FROM {SCHEMA}.idempotency_record
             WHERE key_value = %s AND scope_id = %s
            """,
            (key_value, scope_id),
        )
        assert cur.fetchone() == (5, 1)


def test_a_live_row_is_still_rejected_once_expired_history_exists(conn):
    """Expired history must not weaken the guarantee for the live row beside it."""
    key_value = f"key-{uuid.uuid4()}"
    scope_id = str(uuid.uuid4())

    with conn.cursor() as cur:
        _insert(cur, key_value=key_value, scope_id=scope_id, status="expired")
        _insert(cur, key_value=key_value, scope_id=scope_id, status="active")
    conn.commit()

    with pytest.raises(psycopg2.errors.UniqueViolation) as excinfo:
        with conn.cursor() as cur:
            _insert(cur, key_value=key_value, scope_id=scope_id, status="completed")
        conn.commit()

    assert INDEX_NAME in str(excinfo.value)
    conn.rollback()


# ── The index is genuinely partial, not merely named so ───────────────────────────────


def test_the_index_is_unique_and_carries_the_expired_predicate(conn):
    """Reads the definition PostgreSQL holds, not the model's declaration of it."""
    with conn.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", (INDEX_NAME,))
        definition = cur.fetchone()[0]

    assert "CREATE UNIQUE INDEX" in definition
    assert "key_value" in definition and "scope_id" in definition
    assert "WHERE" in definition and "expired" in definition


def test_no_unconditional_unique_constraint_remains(conn):
    """A leftover table constraint would re-block reuse regardless of the partial index."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT conname FROM pg_constraint
             WHERE conrelid = '{SCHEMA}.idempotency_record'::regclass AND contype = 'u'
            """
        )
        assert cur.fetchall() == []
