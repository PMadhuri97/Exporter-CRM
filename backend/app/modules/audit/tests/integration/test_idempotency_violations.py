"""Idempotency violations read back out of the audit log they were written to.

Every case seeds through the violation detector's own writer,
``dispatch_violation_alert``, rather than inserting audit rows by hand. The failure
worth guarding against is the writer and this reader drifting apart — a renamed
event type, a payload key that moves — and a hand-built fixture would encode the
reader's assumptions about the writer instead of testing them.

Reads go through ``get_audit_ro_db``, the dependency the endpoint uses, so every
case also runs under the ``audit_ro`` role rather than the owner's credentials.

The detector's alert-deduplication cache is process-global, so it is cleared per
test; otherwise whether a record carries ``already_alerted`` would depend on which
tests happened to run first.
"""

from __future__ import annotations

import inspect
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Any

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.modules.audit.infrastructure.idempotency_violations import AuditViolationSource
from app.modules.audit.migrations.audit_0003_event_type_index import (
    INDEX_COLUMNS,
    INDEX_NAME,
)
from app.platform.configuration.config import get_settings
from app.platform.database.services import get_audit_ro_db
from app.platform.idempotency import alerting
from app.platform.idempotency.alerting import clear_alert_cache, dispatch_violation_alert
from app.platform.idempotency.ports import ViolationSource
from app.shared.constants.idempotency import IDEMPOTENCY_VIOLATION_EVENT_TYPE

MARKER = "test-idempotency-violations"


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    session = sessionmaker(bind=sync_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@asynccontextmanager
async def _audit_ro_session():
    """The session the endpoint receives, driven the way FastAPI drives it."""
    generator = get_audit_ro_db()
    session = await generator.__anext__()
    try:
        yield session
    finally:
        with suppress(StopAsyncIteration):
            await generator.__anext__()


@pytest.fixture
def written(db_session):
    """Writes violations through the detector's own writer, and removes them after."""
    clear_alert_cache()
    keys: list[str] = []

    async def _write(*, key_value: str | None = None, **overrides):
        key = key_value or f"{MARKER}-{uuid.uuid4()}"
        keys.append(key)
        fields: dict[str, Any] = {
            "scope": str(uuid.uuid4()),
            "operation_type": "ledger_posting",
            "execution_count": 2,
            "involved_object_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            "correlation_id": f"corr-{uuid.uuid4()}",
        }
        fields.update(overrides)
        await dispatch_violation_alert(db_session, key_value=key, **fields)
        db_session.commit()
        return key, fields

    yield _write

    clear_alert_cache()
    db_session.rollback()
    db_session.execute(
        text("ALTER TABLE audit.audit_events DISABLE TRIGGER audit_events_immutable")
    )
    try:
        for key in keys:
            db_session.execute(
                text(
                    "DELETE FROM audit.audit_events "
                    "WHERE event_type = :t AND payload->>'key_value' = :k"
                ),
                {"t": IDEMPOTENCY_VIOLATION_EVENT_TYPE, "k": key},
            )
    finally:
        db_session.execute(
            text("ALTER TABLE audit.audit_events ENABLE TRIGGER audit_events_immutable")
        )
    db_session.commit()


async def _read_all(limit: int = 500):
    async with _audit_ro_session() as session:
        return await AuditViolationSource(session).list_violations(limit=limit, offset=0)


def _mine(page, key: str):
    return [v for v in page.violations if v.key_value == key]


def _insert_raw(db_session, *, event_type: str, key_value: str) -> None:
    """An audit row the detector's writer would never produce."""
    db_session.execute(
        text(
            "INSERT INTO audit.audit_events (id, event_type, actor_type, payload, created_at) "
            "VALUES (gen_random_uuid(), :t, 'SYSTEM', CAST(:p AS jsonb), NOW())"
        ),
        {"t": event_type, "p": f'{{"key_value": "{key_value}"}}'},
    )
    db_session.commit()


def _delete_raw(db_session, key_value: str) -> None:
    db_session.rollback()
    db_session.execute(
        text("ALTER TABLE audit.audit_events DISABLE TRIGGER audit_events_immutable")
    )
    try:
        db_session.execute(
            text("DELETE FROM audit.audit_events WHERE payload->>'key_value' = :k"),
            {"k": key_value},
        )
    finally:
        db_session.execute(
            text("ALTER TABLE audit.audit_events ENABLE TRIGGER audit_events_immutable")
        )
    db_session.commit()


# ── The contract with the writer ──────────────────────────────────────────────


def test_the_adapter_satisfies_the_port_structurally() -> None:
    assert issubclass(AuditViolationSource, ViolationSource)


def test_the_writer_uses_the_shared_event_type() -> None:
    """One string, one place. A literal left in the writer is the drift this prevents."""
    source = inspect.getsource(alerting)
    assert "IDEMPOTENCY_VIOLATION_EVENT_TYPE" in source
    assert f'"{IDEMPOTENCY_VIOLATION_EVENT_TYPE}"' not in source, (
        "alerting.py spells the event type out instead of importing the shared constant"
    )


async def test_a_violation_written_by_the_detector_reads_back_with_all_six_fields(
    written,
) -> None:
    """The acceptance criterion's six fields, as the detector wrote them."""
    key, fields = await written()

    [violation] = _mine(await _read_all(), key)

    assert violation.key_value == key
    assert violation.scope == fields["scope"]
    assert violation.operation_type == fields["operation_type"]
    assert violation.execution_count == fields["execution_count"]
    assert violation.involved_object_ids == fields["involved_object_ids"]
    assert violation.correlation_id == fields["correlation_id"]
    assert violation.violation_hash
    assert violation.detected_at is not None


async def test_the_traceable_correlation_id_is_returned(written) -> None:
    """Not the uuid5 the writer derives for the uuid-typed column.

    A non-UUID correlation ID is stored twice: as written in the payload, and as a
    derived UUID in the column that matches nothing in any log line. Returning the
    column would hand an operator an ID they cannot search for.
    """
    key, _fields = await written(correlation_id="corr-not-a-uuid-trace-me")

    [violation] = _mine(await _read_all(), key)

    assert violation.correlation_id == "corr-not-a-uuid-trace-me"


# ── Ordering, paging, and what is excluded ────────────────────────────────────


async def test_violations_are_newest_first(written) -> None:
    first, _ = await written()
    second, _ = await written()

    page = await _read_all()

    detected = [v.detected_at for v in page.violations]
    assert detected == sorted(detected, reverse=True), "the whole page must be newest first"
    keys = [v.key_value for v in page.violations if v.key_value in (first, second)]
    assert keys == [second, first]


async def test_total_counts_every_violation_independent_of_the_page(written) -> None:
    await written()
    await written()

    async with _audit_ro_session() as session:
        page = await AuditViolationSource(session).list_violations(limit=1, offset=0)

    assert len(page.violations) == 1
    assert page.total >= 2


async def test_other_audit_events_are_not_violations(written, db_session) -> None:
    """The audit log is shared by every module; only one event type is a violation.

    The decoy carries the same key value in its payload as a real violation, so the
    only thing separating them is the event type — which is the filter under test.
    """
    key, _fields = await written()
    _insert_raw(db_session, event_type="ledger.transaction.posted", key_value=key)
    try:
        records = _mine(await _read_all(), key)
        assert len(records) == 1, "a non-violation audit event was returned as a violation"
    finally:
        _delete_raw(db_session, key)


# ── Recurrence: one incident, many records ────────────────────────────────────


async def test_a_redetected_violation_is_a_second_record_with_the_same_hash(
    written,
) -> None:
    """The scheduled check re-records an unresolved violation on every run.

    Both records are returned, because an audit read reports what was recorded. The
    shared hash is what lets a caller treat them as one incident, and
    already_alerted marks the one that did not page.
    """
    key, fields = await written()
    await written(key_value=key, **fields)

    records = _mine(await _read_all(), key)

    assert len(records) == 2
    assert records[0].violation_hash == records[1].violation_hash
    assert sorted(r.already_alerted for r in records) == [False, True]


# ── A bad row does not fail the page ──────────────────────────────────────────


async def test_an_incomplete_payload_is_returned_with_gaps(db_session) -> None:
    """One malformed row must not take the investigation tool down with it.

    Written by hand because it is precisely the row the real writer cannot produce.
    """
    key = f"{MARKER}-malformed-{uuid.uuid4()}"
    _insert_raw(db_session, event_type=IDEMPOTENCY_VIOLATION_EVENT_TYPE, key_value=key)
    try:
        [violation] = _mine(await _read_all(), key)
        assert violation.key_value == key
        assert violation.scope is None
        assert violation.execution_count is None
        assert violation.involved_object_ids == []
    finally:
        _delete_raw(db_session, key)


# ── The index the feed pages through ──────────────────────────────────────────


@pytest.fixture(scope="module")
def owner_conn():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    yield conn
    conn.close()


def test_the_event_type_index_exists_is_valid_and_ordered(owner_conn) -> None:
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT a.attname, ix.indisvalid
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
        WHERE i.relname = %s
        ORDER BY k.ord
        """,
        (INDEX_NAME,),
    )
    rows = cur.fetchall()
    assert rows, f"{INDEX_NAME} does not exist — audit_0003 has not been applied"
    assert [r[0] for r in rows] == INDEX_COLUMNS
    assert all(r[1] for r in rows), f"{INDEX_NAME} is INVALID — a concurrent build failed"


def test_the_violation_feed_can_use_the_index(owner_conn) -> None:
    """The feed's exact shape: one event type, newest first.

    Sequential scans disabled because a development database may be small enough
    that a scan wins regardless. The question is whether the index can serve this
    query, and on the production log it is the only plan that scales.
    """
    cur = owner_conn.cursor()
    cur.execute("SET enable_seqscan = off")
    try:
        cur.execute(
            "EXPLAIN SELECT id FROM audit.audit_events WHERE event_type = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 100",
            (IDEMPOTENCY_VIOLATION_EVENT_TYPE,),
        )
        plan = "\n".join(r[0] for r in cur.fetchall())
    finally:
        cur.execute("SET enable_seqscan = DEFAULT")
    assert INDEX_NAME in plan, f"the violation feed cannot use {INDEX_NAME}:\n{plan}"
