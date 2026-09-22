"""Unit tests for the bulk scope-transition helpers (S3T2).

transition_records_by_scopes and list_records_by_scopes back the settlement lifecycle
consumer (app/modules/settlement/events/consumers.py): one settlement terminal event
must transition every IDK record (scope_id = settlement_id) and every RR record
(scope_id = a settlement leg id) in one shot, and redelivery of the same event must
change nothing on the second run.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency.models import IdempotencyKeyType, IdempotencyRecord, IdempotencyStatus
from app.platform.idempotency.services import (
    _build_bulk_transition_stmt,
    list_records_by_scopes,
    transition_records_by_scopes,
)


@pytest.fixture(scope="module")
def sync_engine():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
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


@pytest.fixture
async def async_session():
    # Uses the app's own shared AsyncSessionLocal rather than a throwaway
    # create_async_engine() per test. Root conftest.py's session-scoped autouse
    # _use_nullpool_engine fixture already swaps this to a NullPool factory before
    # any test runs, which is the pattern every other async test in this repo relies
    # on successfully. A private per-test engine here intermittently raised
    # "Task ... attached to a different loop" from asyncpg on CI (Linux, Python
    # 3.12), specifically on tests that never write (so never commit, leaving the
    # SELECT's transaction open into fixture teardown) — reusing the
    # already-correctly-scoped shared session factory avoids the engine churn that
    # caused it, rather than fighting the symptom test by test.
    from app.platform.database import services as database

    async with database.AsyncSessionLocal() as session:
        yield session
        await session.rollback()


def _seed_record(
    session: Session,
    *,
    scope_id: str,
    status: IdempotencyStatus = IdempotencyStatus.ACTIVE,
    key_type: IdempotencyKeyType = IdempotencyKeyType.CUSTOMER_KEY,
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        id=uuid.uuid4(),
        key_value=str(uuid.uuid4()),
        scope_id=scope_id,
        key_type=key_type,
        operation_type="test_lifecycle_transition",
        status=status,
        completed_at=datetime.now(UTC) if status != IdempotencyStatus.ACTIVE else None,
    )
    session.add(record)
    session.flush()
    return record


# ── transition_records_by_scopes ─────────────────────────────────────────────


async def test_transition_moves_active_records_across_scopes(db_session, async_session):
    settlement_scope = str(uuid.uuid4())
    leg_scope = str(uuid.uuid4())
    idk = _seed_record(db_session, scope_id=settlement_scope, key_type=IdempotencyKeyType.CUSTOMER_KEY)
    rr = _seed_record(db_session, scope_id=leg_scope, key_type=IdempotencyKeyType.RAIL_REFERENCE)
    db_session.commit()

    transitioned = await transition_records_by_scopes(
        async_session, [settlement_scope, leg_scope], IdempotencyStatus.COMPLETED
    )
    await async_session.commit()

    assert {r.id for r in transitioned} == {idk.id, rr.id}
    assert all(r.status == IdempotencyStatus.COMPLETED for r in transitioned)
    assert all(r.completed_at is not None for r in transitioned)


async def test_transition_leaves_already_terminal_records_untouched(db_session, async_session):
    scope_id = str(uuid.uuid4())
    already_done = _seed_record(db_session, scope_id=scope_id, status=IdempotencyStatus.COMPLETED)
    db_session.commit()
    original_completed_at = already_done.completed_at

    transitioned = await transition_records_by_scopes(async_session, [scope_id], IdempotencyStatus.COMPLETED)
    await async_session.commit()

    assert transitioned == []
    db_session.refresh(already_done)
    assert already_done.completed_at == original_completed_at


async def test_transition_mixed_scope_only_moves_active_ones(db_session, async_session):
    active_scope = str(uuid.uuid4())
    failed_scope = str(uuid.uuid4())
    active_record = _seed_record(db_session, scope_id=active_scope, status=IdempotencyStatus.ACTIVE)
    failed_record = _seed_record(db_session, scope_id=failed_scope, status=IdempotencyStatus.FAILED)
    db_session.commit()

    transitioned = await transition_records_by_scopes(
        async_session, [active_scope, failed_scope], IdempotencyStatus.COMPLETED
    )
    await async_session.commit()

    assert [r.id for r in transitioned] == [active_record.id]
    db_session.refresh(failed_record)
    assert failed_record.status == IdempotencyStatus.FAILED  # untouched, not force-flipped


async def test_transition_key_types_filter_excludes_other_key_types(db_session, async_session):
    """A customer_key record sharing a scope_id with an internal_derived_key/rail_reference
    record must survive a key_types-filtered transition untouched — CK's lifecycle belongs
    exclusively to S1T3's time-based expiry sweep, never to a settlement-scoped caller."""
    scope_id = str(uuid.uuid4())
    idk = _seed_record(db_session, scope_id=scope_id, key_type=IdempotencyKeyType.INTERNAL_DERIVED_KEY)
    ck = _seed_record(db_session, scope_id=scope_id, key_type=IdempotencyKeyType.CUSTOMER_KEY)
    db_session.commit()

    transitioned = await transition_records_by_scopes(
        async_session,
        [scope_id],
        IdempotencyStatus.COMPLETED,
        key_types=[IdempotencyKeyType.INTERNAL_DERIVED_KEY],
    )
    await async_session.commit()

    assert [r.id for r in transitioned] == [idk.id]
    db_session.refresh(ck)
    assert ck.status == IdempotencyStatus.ACTIVE  # untouched


async def test_list_records_key_types_filter_excludes_other_key_types(db_session):
    # Sync db_session deliberately, not async_session: list_records_by_scopes's async
    # def wrapper takes the plain synchronous session.execute() branch for a sync
    # Session, so no asyncpg connection is created here at all — see the note on the
    # async_session fixture above for why that matters on CI.
    scope_id = str(uuid.uuid4())
    rr = _seed_record(db_session, scope_id=scope_id, key_type=IdempotencyKeyType.RAIL_REFERENCE)
    _seed_record(db_session, scope_id=scope_id, key_type=IdempotencyKeyType.CUSTOMER_KEY)
    db_session.commit()

    records = await list_records_by_scopes(
        db_session, [scope_id], key_types=[IdempotencyKeyType.RAIL_REFERENCE]
    )

    assert [r.id for r in records] == [rr.id]


async def test_transition_empty_scope_list_returns_empty(async_session):
    assert await transition_records_by_scopes(async_session, [], IdempotencyStatus.COMPLETED) == []


async def test_transition_rejects_non_terminal_status(async_session):
    with pytest.raises(ValueError, match="Must be 'completed' or 'failed'"):
        await transition_records_by_scopes(async_session, [str(uuid.uuid4())], IdempotencyStatus.ACTIVE)


# ── list_records_by_scopes ────────────────────────────────────────────────────


async def test_list_records_by_scopes_returns_all_statuses(db_session):
    scope_id = str(uuid.uuid4())
    active = _seed_record(db_session, scope_id=scope_id, status=IdempotencyStatus.ACTIVE)
    completed = _seed_record(db_session, scope_id=scope_id, status=IdempotencyStatus.COMPLETED)
    db_session.commit()

    records = await list_records_by_scopes(db_session, [scope_id])

    assert {r.id for r in records} == {active.id, completed.id}


async def test_list_records_by_scopes_empty_when_nothing_registered(db_session):
    assert await list_records_by_scopes(db_session, [str(uuid.uuid4())]) == []


async def test_list_records_by_scopes_empty_scope_list_returns_empty(async_session):
    assert await list_records_by_scopes(async_session, []) == []


# ── concurrency ───────────────────────────────────────────────────────────────
# BUILD.md: "Concurrency criteria are real tests against a real database — mocks
# cannot verify locking." A redelivered settlement event (a duplicate Kafka message,
# or two consumer replicas racing on the same partition during a rebalance) can call
# transition_records_by_scopes for the same scope_ids concurrently. Postgres takes a
# row lock per matched row inside a single UPDATE statement, so only one caller's
# WHERE status='active' can actually match and move a given row — the other sees it
# already gone. Mirrors test_concurrent_registrations_10_runs's pattern.
#
# Workers call _build_bulk_transition_stmt + session.execute() directly rather than
# transition_records_by_scopes(session, ...) wrapped in asyncio.run(): with a sync
# Session that async function's body never actually awaits anything (the
# isinstance(session, AsyncSession) branch is False), so asyncio.run() per worker per
# run was pure unnecessary event-loop churn — up to 100 throwaway loops interleaved
# with pytest-asyncio's session-scoped loop, which corrupted asyncpg's loop-bound
# state for whichever async test in this file happened to run next (observed on CI as
# "RuntimeError: ... attached to a different loop" in unrelated later tests). The
# row-lock guarantee under test is a database property, identical under either
# calling convention, so exercising it synchronously loses nothing.


def test_concurrent_transitions_exactly_one_worker_moves_each_record(sync_engine):
    session_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    for run_idx in range(10):
        scope_id = str(uuid.uuid4())
        setup_session = session_factory()
        try:
            record = _seed_record(setup_session, scope_id=scope_id)
            record_id = record.id
            setup_session.commit()
        finally:
            setup_session.close()

        def transition_worker(worker_id):
            session = session_factory()
            try:
                stmt = _build_bulk_transition_stmt(
                    [scope_id], IdempotencyStatus.COMPLETED, datetime.now(UTC), None
                )
                moved = session.execute(stmt).scalars().all()
                session.commit()
                return len(moved)
            except Exception as exc:  # noqa: BLE001 — surfaced via the assertion below
                session.rollback()
                return str(exc)
            finally:
                session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(transition_worker, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        moved_count = results.count(1)
        untouched_count = results.count(0)
        assert moved_count == 1, (
            f"Run {run_idx}: expected exactly 1 worker to move the record, "
            f"got {moved_count}. Results: {results}"
        )
        assert untouched_count == 9, (
            f"Run {run_idx}: expected 9 workers to see it already gone, "
            f"got {untouched_count}. Results: {results}"
        )

        verify_session = session_factory()
        try:
            final = verify_session.execute(
                select(IdempotencyRecord).where(IdempotencyRecord.id == record_id)
            ).scalar_one()
            assert final.status == IdempotencyStatus.COMPLETED
            assert final.completed_at is not None
        finally:
            verify_session.close()
