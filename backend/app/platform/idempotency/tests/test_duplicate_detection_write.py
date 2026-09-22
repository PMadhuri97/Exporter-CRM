"""Registration persists a duplicate_detection record when it short-circuits a duplicate.

One case per acceptance criterion, plus the cases that make those criteria mean
something:

  one record per detection      — and N detections make N rows, not one row
                                  updated N times. The table is append-only, so
                                  a counter-style implementation would fail at
                                  the database rather than quietly work.
  all fields populated          — asserted field by field, because a NULL in
                                  time_since_original_ms is the difference
                                  between a usable history and a list of keys.
  the counter still increments  — the metric was not replaced by the table.
  no re-execution               — the registry still holds exactly one record
                                  for the key, and the original is what came back.

Detections are written into the caller's transaction, so every case commits the
way the middleware and the rails services do. A test that never committed would
pass against an implementation that never wrote anything.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency.detection_models import DuplicateDetection
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.platform.idempotency.services import register_key_sync

OPERATION = "test_duplicate_detection_write"


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(sync_engine):
    return sessionmaker(bind=sync_engine, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def cleanup(sync_engine):
    """Removes everything a test registered, trigger disabled for the detections."""
    keys: list[str] = []
    yield keys

    session = sessionmaker(bind=sync_engine)()
    try:
        session.execute(
            text(
                "ALTER TABLE ledger.duplicate_detection "
                "DISABLE TRIGGER duplicate_detection_immutable"
            )
        )
        try:
            for key in keys:
                session.execute(
                    text("DELETE FROM ledger.duplicate_detection WHERE idempotency_key = :k"),
                    {"k": key},
                )
                session.execute(
                    text("DELETE FROM ledger.idempotency_record WHERE key_value = :k"),
                    {"k": key},
                )
        finally:
            session.execute(
                text(
                    "ALTER TABLE ledger.duplicate_detection "
                    "ENABLE TRIGGER duplicate_detection_immutable"
                )
            )
        session.commit()
    finally:
        session.close()


def _register(session, key: str, scope: str, **kwargs):
    return register_key_sync(
        session,
        key_value=key,
        key_type=IdempotencyKeyType.CUSTOMER_KEY,
        scope_id=scope,
        operation_type=OPERATION,
        **kwargs,
    )


def _detections(session, key: str) -> list[DuplicateDetection]:
    return list(
        session.execute(
            select(DuplicateDetection)
            .where(DuplicateDetection.idempotency_key == key)
            .order_by(DuplicateDetection.detected_at)
        )
        .scalars()
        .all()
    )


@pytest.fixture
def registered(db_session, cleanup):
    """A key already registered and committed, ready to be re-presented."""

    def _make(*, status: IdempotencyStatus = IdempotencyStatus.COMPLETED):
        key, scope = str(uuid.uuid4()), str(uuid.uuid4())
        cleanup.append(key)
        result = _register(db_session, key, scope, created_by="original-caller")
        record = result.record
        if status is not IdempotencyStatus.ACTIVE:
            record.status = status
            record.completed_at = datetime.now(UTC) - timedelta(seconds=5)
        db_session.commit()
        return key, scope, record

    return _make


# ── One record per detection ──────────────────────────────────────────────────


def test_a_short_circuited_duplicate_creates_one_detection(
    db_session, registered
) -> None:
    key, scope, _record = registered()

    result = _register(db_session, key, scope, created_by="duplicate-caller")
    db_session.commit()

    assert result.registration_result == "duplicate"
    assert len(_detections(db_session, key)) == 1


def test_a_first_registration_creates_no_detection(db_session, cleanup) -> None:
    """Nothing was short-circuited, so there is nothing to record."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    cleanup.append(key)

    _register(db_session, key, scope)
    db_session.commit()

    assert _detections(db_session, key) == []


def test_three_duplicates_create_three_rows(db_session, registered) -> None:
    """Append-only means a history, not a counter.

    A counter-style implementation would have to UPDATE, which the immutability
    trigger rejects — so this would fail loudly rather than silently collapse
    three detections into one.
    """
    key, scope, _record = registered()

    for _ in range(3):
        _register(db_session, key, scope)
    db_session.commit()

    assert len(_detections(db_session, key)) == 3


# ── All fields populated ──────────────────────────────────────────────────────


def test_every_field_is_populated(db_session, registered) -> None:
    key, scope, record = registered()
    correlation = str(uuid.uuid4())

    _register(
        db_session, key, scope, created_by="duplicate-caller", correlation_id=correlation
    )
    db_session.commit()

    detection = _detections(db_session, key)[0]
    assert detection.idempotency_key == key
    assert detection.scope_id == scope
    assert detection.operation_type == OPERATION
    assert detection.original_request_ref == record.id
    assert detection.returned_result_ref == record.id
    assert detection.original_executed_at == record.completed_at
    assert detection.detected_at is not None
    assert detection.caller_identity == "duplicate-caller"
    assert detection.correlation_id == correlation
    assert detection.time_since_original_ms >= 0


def test_the_caller_recorded_is_the_duplicates_not_the_originals(
    db_session, registered
) -> None:
    """The original's caller is already on the record this points at.

    Recording it again here would make the one field that identifies who is
    retrying describe the wrong party.
    """
    key, scope, _record = registered()

    _register(db_session, key, scope, created_by="the-retrying-service")
    db_session.commit()

    assert _detections(db_session, key)[0].caller_identity == "the-retrying-service"


def test_elapsed_time_reflects_the_gap_since_the_original(
    db_session, registered
) -> None:
    """The field the pattern analysis turns on — a tight retry versus a stale replay."""
    key, scope, record = registered()
    record.completed_at = datetime.now(UTC) - timedelta(hours=6)
    db_session.commit()

    _register(db_session, key, scope)
    db_session.commit()

    elapsed = _detections(db_session, key)[0].time_since_original_ms
    assert 5.5 * 3600_000 < elapsed < 6.5 * 3600_000


def test_an_active_original_uses_its_registration_time(db_session, registered) -> None:
    """A duplicate can arrive before the original finishes, leaving no completed_at."""
    key, scope, record = registered(status=IdempotencyStatus.ACTIVE)

    _register(db_session, key, scope)
    db_session.commit()

    detection = _detections(db_session, key)[0]
    assert record.completed_at is None
    assert detection.original_executed_at == record.first_seen_at


# ── The counter is not replaced ───────────────────────────────────────────────


def test_the_metric_still_increments(db_session, registered) -> None:
    """The aggregate drives the dashboard; the table drives the query. Both run."""
    key, scope, _record = registered()
    labels = {
        "key_type": IdempotencyKeyType.CUSTOMER_KEY.value,
        "operation_type": OPERATION,
        "duplicate_status": IdempotencyStatus.COMPLETED.value,
    }
    before = REGISTRY.get_sample_value("aner_idempotency_duplicates_total", labels) or 0.0

    _register(db_session, key, scope)
    db_session.commit()

    after = REGISTRY.get_sample_value("aner_idempotency_duplicates_total", labels)
    assert after == before + 1


# ── The downstream operation does not run again ───────────────────────────────


def test_the_registry_still_holds_exactly_one_record(db_session, registered) -> None:
    """The whole point: detection recorded, operation not repeated."""
    key, scope, record = registered()

    result = _register(db_session, key, scope)
    db_session.commit()

    live = db_session.execute(
        select(func.count())
        .select_from(IdempotencyRecord)
        .where(IdempotencyRecord.key_value == key)
    ).scalar_one()
    assert live == 1
    assert result.record.id == record.id, "the original record must be what is returned"


# ── Concurrency ───────────────────────────────────────────────────────────────


def test_concurrent_duplicates_each_record_a_detection(
    session_factory, registered, db_session
) -> None:
    """Real connections against a real database — a lock cannot be mocked.

    Four callers re-present the same key at once. Each is short-circuited, so
    each must leave its own row: a lost detection here is a caller who retried
    and left no trace.
    """
    key, scope, _record = registered()
    workers = 4

    def _attempt() -> None:
        session = session_factory()
        try:
            _register(session, key, scope, created_by="concurrent")
            session.commit()
        finally:
            session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(_attempt) for _ in range(workers)]:
            future.result()

    db_session.rollback()
    assert len(_detections(db_session, key)) == workers
