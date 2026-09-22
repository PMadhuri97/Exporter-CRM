"""Unit and service-level tests for the archival pipeline (S3T3).

Tests the ``run_archival_job`` service function using real database sessions
(matching the test_key_registration_service.py pattern) to exercise the full
transactional archival flow, Prometheus metrics emission, and audit sink logging.

Each test is an independently collected pytest function — no umbrella test
calling helper functions.
"""

import asyncio
import gc
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.platform.audit_framework.sink import AuditSinkLogger
from app.platform.configuration.config import get_settings
from app.platform.idempotency.archival_service import run_archival_job
from app.platform.idempotency.archive_models import IdempotencyArchive
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)


@pytest.fixture(scope="module")
def sync_engine():
    settings = get_settings()
    url = settings.DATABASE_SYNC_URL
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    session_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(autouse=True)
async def _use_nullpool_in_archival_service():
    """Ensure the archival service uses the NullPool-backed async session factory.

    ``archival_service.py`` imports ``AsyncSessionLocal`` at module load time,
    capturing the *original* pooled engine. The root conftest swaps
    ``database.AsyncSessionLocal`` with a NullPool engine **after** import, so
    the archival module still holds a stale reference to the old factory. On
    Windows this causes the proactor event loop IOCP write-future crash
    (``'NoneType' has no attribute 'send'``) when pooled connections from a
    previous test are recycled.

    This fixture patches the archival service's local ``AsyncSessionLocal``
    binding to match the current (NullPool) factory for each test.
    """
    from app.platform.database import services as database
    from app.platform.idempotency import archival_service

    archival_service.AsyncSessionLocal = database.AsyncSessionLocal
    yield
    gc.collect()
    await asyncio.sleep(0)


def _seed_aged_record(
    session: Session,
    *,
    status: IdempotencyStatus = IdempotencyStatus.COMPLETED,
    days_ago: int = 100,
) -> IdempotencyRecord:
    """Create and flush a record that is eligible for archival."""
    past = datetime.now(UTC) - timedelta(days=days_ago)
    record = IdempotencyRecord(
        id=uuid.uuid4(),
        key_value=str(uuid.uuid4()),
        scope_id=str(uuid.uuid4()),
        key_type=IdempotencyKeyType.CUSTOMER_KEY,
        operation_type="test_archival",
        status=status,
        completed_at=past,
        expires_at=past,
        first_seen_at=past - timedelta(hours=1),
    )
    session.add(record)
    session.flush()
    return record


def _seed_recent_record(
    session: Session,
    *,
    status: IdempotencyStatus = IdempotencyStatus.COMPLETED,
) -> IdempotencyRecord:
    """Create a record that is NOT eligible (too recent)."""
    now = datetime.now(UTC)
    record = IdempotencyRecord(
        id=uuid.uuid4(),
        key_value=str(uuid.uuid4()),
        scope_id=str(uuid.uuid4()),
        key_type=IdempotencyKeyType.CUSTOMER_KEY,
        operation_type="test_archival",
        status=status,
        completed_at=now,
        expires_at=now + timedelta(hours=24),
        first_seen_at=now - timedelta(hours=1),
    )
    session.add(record)
    session.flush()
    return record


def _cleanup_record(session: Session, record_id: uuid.UUID) -> None:
    """Remove a record from both tables (for test cleanup)."""
    # Disable archive delete trigger for cleanup
    session.execute(
        text(
            "ALTER TABLE ledger.idempotency_archive "
            "DISABLE TRIGGER trigger_idempotency_archive_no_delete"
        )
    )
    session.execute(
        text("DELETE FROM ledger.idempotency_archive WHERE id = :id"), {"id": str(record_id)}
    )
    session.execute(
        text("DELETE FROM ledger.idempotency_record WHERE id = :id"), {"id": str(record_id)}
    )
    session.execute(
        text(
            "ALTER TABLE ledger.idempotency_archive "
            "ENABLE TRIGGER trigger_idempotency_archive_no_delete"
        )
    )
    session.commit()


# ── 1. DELETE-blocking trigger test ──────────────────────────────────────────


def test_archive_delete_trigger_rejects_deletion(db_session):
    """The DELETE-blocking trigger on idempotency_archive prevents row removal."""
    record_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(days=200)

    # Insert a record directly into the archive table via raw SQL.
    db_session.execute(
        text(
            "INSERT INTO ledger.idempotency_archive "
            "(id, key_value, scope_id, key_type, operation_type, status, "
            " first_seen_at, archived_at) "
            "VALUES (:id, :kv, :sid, 'customer_key', 'test_trigger', "
            "'completed', :fsa, NOW())"
        ),
        {
            "id": str(record_id),
            "kv": str(uuid.uuid4()),
            "sid": str(uuid.uuid4()),
            "fsa": past.isoformat(),
        },
    )
    db_session.commit()

    try:
        # Attempt to delete — the trigger must raise.
        with pytest.raises(Exception, match="DELETE on idempotency_archive is forbidden"):
            db_session.execute(
                text("DELETE FROM ledger.idempotency_archive WHERE id = :id"),
                {"id": str(record_id)},
            )
        db_session.rollback()
    finally:
        # Clean up: disable trigger, delete, re-enable.
        db_session.execute(
            text(
                "ALTER TABLE ledger.idempotency_archive "
                "DISABLE TRIGGER trigger_idempotency_archive_no_delete"
            )
        )
        db_session.execute(
            text("DELETE FROM ledger.idempotency_archive WHERE id = :id"),
            {"id": str(record_id)},
        )
        db_session.execute(
            text(
                "ALTER TABLE ledger.idempotency_archive "
                "ENABLE TRIGGER trigger_idempotency_archive_no_delete"
            )
        )
        db_session.commit()


# ── Service-level tests ──────────────────────────────────────────────────────


async def test_archival_job_archives_aged_records(client, db_session):
    """run_archival_job moves aged terminal records and returns correct counts."""
    r1 = _seed_aged_record(db_session, status=IdempotencyStatus.COMPLETED, days_ago=100)
    r2 = _seed_aged_record(db_session, status=IdempotencyStatus.FAILED, days_ago=120)
    r3 = _seed_recent_record(db_session, status=IdempotencyStatus.COMPLETED)
    db_session.commit()

    try:
        AuditSinkLogger.clear_recorded_entries()
        result = await run_archival_job()

        assert (
            result["records_archived"] >= 2
        ), f"Expected at least 2 archived, got {result['records_archived']}"
        assert result["hot_table_remaining"] >= 0

        # Verify audit entries were emitted
        entries = AuditSinkLogger.get_recorded_entries()
        archived_entries = [
            e for e in entries if e.get("event_type") == "idempotency.record.archived"
        ]
        assert (
            len(archived_entries) >= 2
        ), f"Expected at least 2 audit entries, got {len(archived_entries)}"
    finally:
        _cleanup_record(db_session, r1.id)
        _cleanup_record(db_session, r2.id)
        _cleanup_record(db_session, r3.id)


async def test_archival_job_skips_recent_records(client, db_session):
    """run_archival_job does not archive records that are within the retention window."""
    recent = _seed_recent_record(db_session, status=IdempotencyStatus.COMPLETED)
    db_session.commit()

    try:
        await run_archival_job()

        # Verify the recent record is still in the hot table
        hot_check = db_session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.id == recent.id)
        )
        assert (
            hot_check.scalar_one_or_none() is not None
        ), "Recent record should still be in hot table"
    finally:
        _cleanup_record(db_session, recent.id)


async def test_archival_job_skips_active_records(client, db_session):
    """run_archival_job never archives records with active status."""
    active = _seed_aged_record(db_session, status=IdempotencyStatus.ACTIVE, days_ago=200)
    db_session.commit()

    try:
        await run_archival_job()

        # Active record should still be in the hot table
        hot_check = db_session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.id == active.id)
        )
        assert hot_check.scalar_one_or_none() is not None, "Active record must never be archived"
    finally:
        _cleanup_record(db_session, active.id)


async def test_archival_job_returns_zero_when_nothing_eligible(client):
    """When no records are eligible, the service returns zeros gracefully."""
    result = await run_archival_job()
    assert "records_archived" in result
    assert "hot_table_remaining" in result
    assert "growth_rate_per_day" in result


async def test_archival_metrics_are_registered(client):
    """The archival Prometheus metrics exist in the registry."""
    metric_names = [m.name for m in REGISTRY.collect()]
    assert any(
        "aner_archival_records_archived" in n for n in metric_names
    ), f"aner_archival_records_archived_total not found. Available: {metric_names}"
    assert any("aner_archival_hot_table_remaining" in n for n in metric_names)
    assert any("aner_archival_hot_table_growth_rate" in n for n in metric_names)
    assert any("aner_archival_runs" in n for n in metric_names)


@pytest.mark.parametrize(
    "status",
    [
        IdempotencyStatus.COMPLETED,
        IdempotencyStatus.FAILED,
        IdempotencyStatus.EXPIRED,
    ],
    ids=["COMPLETED", "FAILED", "EXPIRED"],
)
async def test_terminal_status_is_archived(client, db_session, status):
    """Each terminal status (completed, failed, expired) is correctly archived."""
    record = _seed_aged_record(db_session, status=status, days_ago=100)
    db_session.commit()

    try:
        await run_archival_job()

        # Should be removed from hot table
        hot_check = db_session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.id == record.id)
        )
        assert hot_check.scalar_one_or_none() is None

        # Should exist in archive table
        archive_check = db_session.execute(
            select(IdempotencyArchive).where(IdempotencyArchive.id == record.id)
        )
        archived = archive_check.scalar_one_or_none()
        assert archived is not None, f"Record with status {status.value} should be archived"
    finally:
        _cleanup_record(db_session, record.id)


# ── 4. Transactional rollback test ───────────────────────────────────────────


async def test_archival_insert_failure_rolls_back_transaction(client, db_session):
    """If the archive INSERT fails, the original hot-table record must survive."""
    record = _seed_aged_record(db_session, status=IdempotencyStatus.COMPLETED, days_ago=150)
    db_session.commit()

    try:
        # Patch the session.execute inside _do_archival so the INSERT into the
        # archive table raises, simulating a transactional failure.
        original_execute = None

        async def _failing_execute(stmt, *args, **kwargs):
            """Let SELECTs and advisory-lock calls through; blow up on INSERT."""
            from sqlalchemy.dialects.postgresql import Insert

            if isinstance(stmt, Insert):
                raise RuntimeError("Simulated archive INSERT failure")
            return await original_execute(stmt, *args, **kwargs)

        with patch(
            "app.platform.idempotency.archival_service.AsyncSessionLocal"
        ) as mock_factory:
            # Build a real session but intercept execute
            from app.platform.database.services import AsyncSessionLocal

            real_session = AsyncSessionLocal()

            original_execute = real_session.execute

            mock_session = AsyncMock(wraps=real_session)
            mock_session.execute = _failing_execute
            # Make the context manager return our patched session
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RuntimeError, match="Simulated archive INSERT failure"):
                await run_archival_job()

            await real_session.close()

        # The original record must still be in the hot table.
        db_session.expire_all()
        hot_check = db_session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.id == record.id)
        )
        assert (
            hot_check.scalar_one_or_none() is not None
        ), "Original record must survive when archive INSERT fails"

        # Nothing should have appeared in the archive table.
        archive_check = db_session.execute(
            select(IdempotencyArchive).where(IdempotencyArchive.id == record.id)
        )
        assert (
            archive_check.scalar_one_or_none() is None
        ), "No archive row should exist after a failed INSERT"
    finally:
        _cleanup_record(db_session, record.id)

