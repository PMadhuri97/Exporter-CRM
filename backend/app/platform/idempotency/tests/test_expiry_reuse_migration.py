"""Schema and backfill guarantees introduced by idem_0001_expiry_reuse_window (S3T1).

Covers the parts of the migration that are easy to break silently: the model being visible
to Alembic at all, the unique index being *partial* and keeping its name, and the backfill
touching exactly the rows it is supposed to.
"""

import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.database.models import Base
from app.platform.idempotency.migrations.idem_0001_expiry_reuse_window import (
    BACKFILL_SQL,
    CK_SWEEP_INDEX_NAME,
    HISTORICAL_CK_EXPIRY_WINDOW,
    UNIQUE_INDEX_NAME,
)
from app.platform.idempotency.models import IdempotencyRecord

OPERATION = "s3t1_migration_test"
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
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


def _insert_raw(session, *, key_type, status, first_seen_at, expires_at):
    """Insert a row in the shape a pre-S3T1 record would have had.

    Goes through raw SQL rather than register_key so the test can choose key_type, status
    and a first_seen_at in the past — none of which registration would let it set.
    """
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
            "first_seen_at": first_seen_at,
            "expires_at": expires_at,
        },
    )
    session.commit()
    return record_id


def _read(session, record_id):
    session.expire_all()
    return session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.id == record_id)
    ).scalar_one()


# ── 1. Alembic can see the model ──────────────────────────────────────────────────────


def test_idempotency_record_is_registered_in_metadata():
    """The table must be in Base.metadata or autogenerate proposes dropping it.

    app/platform/idempotency/models.py was imported by neither bootstrap nor the Alembic
    env, so `alembic revision --autogenerate` emitted remove_table for a live table.
    """
    assert "ledger.idempotency_record" in Base.metadata.tables


def test_alembic_env_imports_the_idempotency_model():
    """Guard the import itself — metadata registration is a side effect of it existing.

    Base.metadata can be populated by whatever else a test session imported, so asserting
    on metadata alone would keep passing after someone deleted this line.
    """
    env = (BACKEND_ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "import app.platform.idempotency.models" in env


def test_idempotency_migrations_dir_is_registered_with_alembic():
    """An unregistered version_locations entry is silently skipped by `upgrade head`."""
    ini = (BACKEND_ROOT / "alembic.ini").read_text(encoding="utf-8")
    version_locations = next(
        line for line in ini.splitlines() if line.startswith("version_locations")
    )
    assert "app/platform/idempotency/migrations" in version_locations


# ── 2. The index is partial, and keeps its name ───────────────────────────────────────


def test_unique_index_exists_is_unique_and_is_partial(db_session):
    """Name retained, uniqueness retained, but scoped to live rows."""
    definition = db_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
        {"name": UNIQUE_INDEX_NAME},
    ).scalar_one()

    assert "CREATE UNIQUE INDEX" in definition
    assert "key_value" in definition and "scope_id" in definition
    assert "WHERE" in definition
    assert "expired" in definition


def test_old_unconditional_unique_constraint_is_gone(db_session):
    """A leftover table constraint would re-block reuse regardless of the new index."""
    constraints = db_session.execute(
        text(
            """
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'ledger.idempotency_record'::regclass
               AND contype = 'u'
            """
        )
    ).scalars().all()

    assert constraints == []


def test_ck_sweep_index_exists_and_is_scoped_to_customer_keys(db_session):
    """The sweep index encodes the CK-only rule that keeps IDK/RR out of time expiry."""
    definition = db_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
        {"name": CK_SWEEP_INDEX_NAME},
    ).scalar_one()

    assert "customer_key" in definition
    assert "completed" in definition and "failed" in definition
    assert "internal_derived_key" not in definition
    assert "rail_reference" not in definition


# ── 9. ON CONFLICT infers the partial index ───────────────────────────────────────────


def test_on_conflict_inference_matches_the_partial_index(db_session):
    """The insert must compile and execute — inference failures surface only at runtime.

    If index_where drifts from the index predicate, Postgres raises "there is no unique or
    exclusion constraint matching the ON CONFLICT specification" on execution, not import.
    """
    from app.platform.idempotency.services import _build_register_insert_stmt

    stmt = _build_register_insert_stmt(
        key_value=str(uuid.uuid4()),
        key_type_enum="customer_key",
        scope_id=str(uuid.uuid4()),
        operation_type=OPERATION,
        now=datetime.now(UTC),
    )

    compiled = str(stmt.compile(dialect=db_session.bind.dialect))
    assert "ON CONFLICT" in compiled
    assert "WHERE status <> 'expired'" in compiled

    inserted = db_session.execute(stmt).scalar_one_or_none()
    db_session.commit()
    assert inserted is not None


# ── 11/12/13. Backfill touches exactly the right rows ─────────────────────────────────


def test_backfill_derives_expires_at_from_first_seen_at(db_session):
    """CK with a NULL window gets first_seen_at + 24h — never now() + 24h.

    The row is seeded 30 days in the past, so a now()-anchored backfill would land in the
    future and this assertion would fail by roughly a month.
    """
    first_seen = datetime.now(UTC) - timedelta(days=30)
    record_id = _insert_raw(
        db_session,
        key_type="customer_key",
        status="completed",
        first_seen_at=first_seen,
        expires_at=None,
    )

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()

    record = _read(db_session, record_id)
    assert record.expires_at is not None
    assert record.expires_at == record.first_seen_at + timedelta(hours=24)
    assert record.expires_at < datetime.now(UTC), (
        "a window that closed 29 days ago must remain in the past — "
        "a future value means the backfill was anchored on migration time"
    )


def test_backfill_window_matches_the_declared_historical_constant():
    """The migration's literal is the historical rule, and the test reads it from there."""
    assert HISTORICAL_CK_EXPIRY_WINDOW == "24 hours"
    assert "first_seen_at + INTERVAL" in BACKFILL_SQL
    assert "now()" not in BACKFILL_SQL.lower()


def test_backfill_does_not_overwrite_an_existing_expires_at(db_session):
    """A caller-supplied window is not ours to replace."""
    first_seen = datetime.now(UTC) - timedelta(days=30)
    caller_value = first_seen + timedelta(hours=1)
    record_id = _insert_raw(
        db_session,
        key_type="customer_key",
        status="completed",
        first_seen_at=first_seen,
        expires_at=caller_value,
    )

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()

    assert _read(db_session, record_id).expires_at == caller_value


@pytest.mark.parametrize("key_type", ["internal_derived_key", "rail_reference"])
def test_backfill_leaves_non_customer_keys_alone(db_session, key_type):
    """IDK and RR do not expire on a clock — S3T2 owns their lifecycle."""
    record_id = _insert_raw(
        db_session,
        key_type=key_type,
        status="completed",
        first_seen_at=datetime.now(UTC) - timedelta(days=30),
        expires_at=None,
    )

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()

    assert _read(db_session, record_id).expires_at is None


def test_backfill_leaves_already_expired_records_alone(db_session):
    """Writing a retroactive window onto a terminal record would fabricate an audit fact."""
    record_id = _insert_raw(
        db_session,
        key_type="customer_key",
        status="expired",
        first_seen_at=datetime.now(UTC) - timedelta(days=30),
        expires_at=None,
    )

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()

    assert _read(db_session, record_id).expires_at is None


def test_backfill_is_idempotent(db_session):
    """Re-running must not shift a window it already set."""
    record_id = _insert_raw(
        db_session,
        key_type="customer_key",
        status="failed",
        first_seen_at=datetime.now(UTC) - timedelta(days=30),
        expires_at=None,
    )

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()
    after_first = _read(db_session, record_id).expires_at

    db_session.execute(text(BACKFILL_SQL))
    db_session.commit()

    assert _read(db_session, record_id).expires_at == after_first
