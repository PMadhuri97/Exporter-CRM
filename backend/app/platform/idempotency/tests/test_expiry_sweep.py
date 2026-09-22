"""The S3T1 expiry sweep (Phase 4).

Two things are under test and they carry different weight. The eligibility rules — which
records move to `expired` — are ordinary correctness. The IDK/RR exclusions are a safety
boundary: expiring a rail reference frees a key the payment network still honours, so those
tests deliberately construct records the sweep *could* pick up if the key_type predicate
were ever dropped, and assert it does not.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import settings
from app.platform.idempotency import IdempotencyExpiryService, IdempotencyStatus
from app.platform.idempotency.expiry import (
    EXPIRABLE_STATUSES,
    IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY,
    guard_rails,
)
from app.platform.idempotency.models import IdempotencyRecord

OPERATION = "s3t1_sweep_test"

PAST = datetime(2020, 1, 1, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(
            IdempotencyRecord.__table__.delete().where(
                IdempotencyRecord.operation_type == OPERATION
            )
        )
        session.commit()
        session.close()


def _seed(session, *, key_type, status, expires_at):
    """Insert a record directly so the test can choose key_type, status and expiry."""
    record_id = uuid.uuid4()
    session.execute(
        text(
            """
            INSERT INTO ledger.idempotency_record
                (id, key_value, scope_id, key_type, operation_type, status,
                 first_seen_at, expires_at)
            VALUES
                (:id, :key_value, :scope_id, :key_type, :operation_type, :status,
                 :first_seen_at, :expires_at)
            """
        ),
        {
            "id": record_id,
            "key_value": f"{key_type}-{uuid.uuid4()}",
            "scope_id": str(uuid.uuid4()),
            "key_type": key_type,
            "operation_type": OPERATION,
            "status": status,
            "first_seen_at": PAST,
            "expires_at": expires_at,
        },
    )
    session.commit()
    return record_id


def _status_of(session, record_id) -> IdempotencyStatus:
    session.expire_all()
    return session.execute(
        select(IdempotencyRecord.status).where(IdempotencyRecord.id == record_id)
    ).scalar_one()


async def _sweep(session):
    return await IdempotencyExpiryService(session).run_expiry_sweep()


# ── Records the sweep must expire ─────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_customer_key_past_expiry_is_expired(db_session, status):
    """Cases 1 and 2 — a closed window on a finished operation releases the key."""
    record_id = _seed(
        db_session, key_type="customer_key", status=status, expires_at=PAST
    )

    result = await _sweep(db_session)
    db_session.commit()

    assert result.expired_count >= 1
    assert result.ran
    assert _status_of(db_session, record_id) == IdempotencyStatus.EXPIRED


# ── Records the sweep must leave alone ────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_customer_key_before_expiry_is_unchanged(db_session, status):
    """Cases 3 and 4 — the window is still open."""
    record_id = _seed(
        db_session, key_type="customer_key", status=status, expires_at=FUTURE
    )

    await _sweep(db_session)
    db_session.commit()

    assert _status_of(db_session, record_id) == IdempotencyStatus(status)


def test_active_is_not_expirable_by_configuration_of_the_predicate():
    """`active` must not be in the expirable set — the guard behind the next test."""
    assert IdempotencyStatus.ACTIVE not in EXPIRABLE_STATUSES
    assert set(EXPIRABLE_STATUSES) == {
        IdempotencyStatus.COMPLETED,
        IdempotencyStatus.FAILED,
    }


async def test_active_customer_key_past_expiry_is_unchanged(db_session):
    """An in-flight operation is never expired out from under its caller.

    It becomes eligible only once it reaches a terminal state — and then the already-past
    window makes it eligible on the very next sweep.
    """
    record_id = _seed(
        db_session, key_type="customer_key", status="active", expires_at=PAST
    )

    await _sweep(db_session)
    db_session.commit()

    assert _status_of(db_session, record_id) == IdempotencyStatus.ACTIVE


async def test_customer_key_with_null_expiry_is_unchanged(db_session):
    """Case 5 — no window means no clock, whatever the status."""
    record_id = _seed(
        db_session, key_type="customer_key", status="completed", expires_at=None
    )

    await _sweep(db_session)
    db_session.commit()

    assert _status_of(db_session, record_id) == IdempotencyStatus.COMPLETED


async def test_already_expired_record_is_unchanged(db_session):
    """Case 8 — the status predicate excludes it, which is what makes re-runs no-ops."""
    record_id = _seed(
        db_session, key_type="customer_key", status="expired", expires_at=PAST
    )

    await _sweep(db_session)
    db_session.commit()

    assert _status_of(db_session, record_id) == IdempotencyStatus.EXPIRED


# ── IDK and RR: the safety boundary ───────────────────────────────────────────────────


@pytest.mark.parametrize("key_type", ["internal_derived_key", "rail_reference"])
@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_non_customer_keys_past_expiry_are_never_expired(
    db_session, key_type, status
):
    """Cases 6 and 7 — the adversarial test.

    These records are given a past expires_at deliberately, which registration would never
    do: their configured window is null. The point is to construct exactly the row the
    sweep would take if the key_type predicate were dropped, so this test fails the moment
    that protection is removed rather than the moment a rail reference is wrongly freed.
    """
    record_id = _seed(db_session, key_type=key_type, status=status, expires_at=PAST)

    await _sweep(db_session)
    db_session.commit()

    assert _status_of(db_session, record_id) == IdempotencyStatus(status)


async def test_a_mixed_population_is_swept_correctly(db_session):
    """Every key type against every status, one sweep, the whole matrix asserted at once."""
    seeded = {
        (key_type, status, when_label): _seed(
            db_session, key_type=key_type, status=status, expires_at=when
        )
        for key_type in ("customer_key", "internal_derived_key", "rail_reference")
        for status in ("active", "completed", "failed")
        for when_label, when in (("past", PAST), ("future", FUTURE))
    }

    await _sweep(db_session)
    db_session.commit()

    for (key_type, status, when_label), record_id in seeded.items():
        should_expire = (
            key_type == "customer_key"
            and status in ("completed", "failed")
            and when_label == "past"
        )
        expected = IdempotencyStatus.EXPIRED if should_expire else IdempotencyStatus(status)
        assert _status_of(db_session, record_id) == expected, (
            f"{key_type}/{status}/{when_label} expected {expected.value}"
        )


def test_guard_rails_are_documented_and_layered():
    """The IDK/RR protections are more than the one predicate."""
    rails = guard_rails()
    assert set(rails) == {
        "query_predicate",
        "configuration",
        "null_guard",
        "index_predicate",
    }
    assert all(text_.strip() for text_ in rails.values())


# ── Repeatability ─────────────────────────────────────────────────────────────────────


async def test_sweep_is_idempotent_across_runs(db_session):
    """Case 9 — the second run finds nothing left to do."""
    record_id = _seed(
        db_session, key_type="customer_key", status="completed", expires_at=PAST
    )

    first = await _sweep(db_session)
    db_session.commit()
    assert first.expired_count >= 1

    second = await _sweep(db_session)
    db_session.commit()

    assert second.expired_count == 0
    assert _status_of(db_session, record_id) == IdempotencyStatus.EXPIRED


async def test_sweep_on_an_empty_population_is_a_no_op(db_session):
    result = await _sweep(db_session)
    db_session.commit()

    assert result.expired_count == 0
    assert result.ran
    assert not result.truncated


async def test_sweep_does_not_touch_first_seen_at(db_session):
    """first_seen_at is immutable at the database level — a trigger would raise."""
    record_id = _seed(
        db_session, key_type="customer_key", status="completed", expires_at=PAST
    )

    await _sweep(db_session)
    db_session.commit()

    db_session.expire_all()
    record = db_session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.id == record_id)
    ).scalar_one()
    assert record.first_seen_at == PAST
    assert record.expires_at == PAST, "the sweep changes status only"


async def test_batching_expires_everything_across_multiple_batches(db_session):
    """More rows than one batch holds must still all be expired."""
    ids = [
        _seed(db_session, key_type="customer_key", status="completed", expires_at=PAST)
        for _ in range(5)
    ]

    result = await IdempotencyExpiryService(db_session).run_expiry_sweep(batch_size=2)
    db_session.commit()

    assert result.expired_count >= 5
    assert not result.truncated
    assert all(
        _status_of(db_session, record_id) == IdempotencyStatus.EXPIRED for record_id in ids
    )


# ── Locking ───────────────────────────────────────────────────────────────────────────


async def test_sweep_skips_when_another_holder_has_the_lock(db_session, sync_engine):
    """Case 11 — a concurrent sweep returns immediately instead of duplicating the work."""
    record_id = _seed(
        db_session, key_type="customer_key", status="completed", expires_at=PAST
    )

    holder_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    holder = holder_factory()
    try:
        held = holder.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY},
        ).scalar_one()
        assert held, "the probe must own the lock for this test to mean anything"

        result = await _sweep(db_session)
        db_session.commit()

        assert result.skipped
        assert not result.ran
        assert result.expired_count == 0
        assert _status_of(db_session, record_id) == IdempotencyStatus.COMPLETED
    finally:
        holder.rollback()  # transaction-scoped lock is released here
        holder.close()

    # With the lock free the same record sweeps normally.
    after = await _sweep(db_session)
    db_session.commit()
    assert after.ran
    assert _status_of(db_session, record_id) == IdempotencyStatus.EXPIRED


async def test_lock_is_released_when_the_transaction_ends(db_session, sync_engine):
    """A held lock must not outlive its transaction, or one sweep would wedge the rest."""
    await _sweep(db_session)
    db_session.commit()

    probe_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    probe = probe_factory()
    try:
        acquired = probe.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY},
        ).scalar_one()
        assert acquired, "the sweep's commit should have released the advisory lock"
    finally:
        probe.rollback()
        probe.close()


# ── Efficiency ────────────────────────────────────────────────────────────────────────


async def test_sweep_can_use_the_partial_ck_index(db_session):
    """The sweep must be an index scan at scale, not a full table read.

    seqscan is disabled for the plan because the test table holds a handful of rows and the
    planner is right to prefer a sequential scan there — the question is whether the index
    is *usable*, which is what governs behaviour once the table is large. The existing
    query-plan test in test_idempotency_db.py uses the same technique.

    The assertion is deliberately only that the partial index is chosen. The exact plan
    shape is the planner's business and changes with table size — a small table gets a plain
    Index Scan with no Sort node, a larger one a Bitmap Index Scan with a Recheck Cond and a
    Sort. Asserting either shape makes the test fail on data volume rather than on a real
    regression, which is exactly what an earlier version of it did.
    """
    db_session.execute(text("SET enable_seqscan = OFF"))
    plan = "\n".join(
        row[0]
        for row in db_session.execute(
            text(
                """
                EXPLAIN (COSTS OFF)
                SELECT id FROM ledger.idempotency_record
                 WHERE key_type = 'customer_key'
                   AND status IN ('completed','failed')
                   AND expires_at IS NOT NULL
                   AND expires_at <= now()
                 ORDER BY expires_at LIMIT 1000
                """
            )
        )
    )
    db_session.execute(text("SET enable_seqscan = ON"))

    assert "ix_idempotency_record_ck_expiry" in plan, plan
    assert "Seq Scan" not in plan, plan
