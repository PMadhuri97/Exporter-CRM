"""expires_at as written by registration (S3T1).

The unit tests in test_expiry_configuration.py pin the arithmetic. These pin what actually
lands in the database: that a customer key carries a window derived from configuration and
anchored on its own first_seen_at, and that IDK and RR carry none.
"""

import pathlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import settings
from app.platform.idempotency import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
    RegistrationResultType,
    derive_internal_key,
    generate_rail_reference,
    register_key_sync,
    reset_key_expiry_windows_cache,
)
from app.platform.idempotency.config import CONFIG_DIR, KEY_EXPIRY_FILENAME

OPERATION = "s3t1_expiry_registration_test"


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


@pytest.fixture(autouse=True)
def _clear_config_cache():
    reset_key_expiry_windows_cache()
    yield
    reset_key_expiry_windows_cache()


@pytest.fixture
def configured_windows(tmp_path, monkeypatch):
    """Point the loader at a fixture file so a test can choose the window."""

    def _configure(customer_key_seconds: int):
        (tmp_path / KEY_EXPIRY_FILENAME).write_text(
            "key_expiry:\n"
            f"  customer_key_seconds: {customer_key_seconds}\n"
            "  internal_derived_key_seconds: null\n"
            "  rail_reference_seconds: null\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))
        reset_key_expiry_windows_cache()

    return _configure


def _register(session, key_value, key_type, **kwargs):
    result = register_key_sync(
        session=session,
        key_value=key_value,
        key_type=key_type,
        scope_id=str(uuid.uuid4()),
        operation_type=OPERATION,
        **kwargs,
    )
    session.commit()
    return result


def _reload(session, record_id):
    session.expire_all()
    return session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.id == record_id)
    ).scalar_one()


def _deployed_customer_key_seconds() -> int:
    """The window in the deployed file, read from it so the test never restates it."""
    import yaml

    document = yaml.safe_load((CONFIG_DIR / KEY_EXPIRY_FILENAME).read_text(encoding="utf-8"))
    return document["key_expiry"]["customer_key_seconds"]


# ── Customer keys ─────────────────────────────────────────────────────────────────────


def test_customer_key_registration_sets_expires_at(db_session):
    """Before S3T1 this column was always NULL — nothing computed it."""
    result = _register(db_session, str(uuid.uuid4()), "customer_key")

    assert result.result == RegistrationResultType.NEW
    assert _reload(db_session, result.record.id).expires_at is not None


def test_expires_at_is_exactly_first_seen_at_plus_the_configured_window(db_session):
    """The equality the requirement states, asserted to the microsecond.

    The window comes from the loader rather than a literal, so changing the deployed file
    moves this assertion with it instead of breaking it.
    """
    from app.platform.idempotency.config import expiry_window_for

    window = expiry_window_for(IdempotencyKeyType.CUSTOMER_KEY)
    result = _register(db_session, str(uuid.uuid4()), "customer_key")

    record = _reload(db_session, result.record.id)
    assert record.expires_at - record.first_seen_at == window


def test_deployed_configuration_produces_a_24_hour_window(db_session):
    """The current business requirement, end to end through a real registration."""
    assert _deployed_customer_key_seconds() == 86400

    result = _register(db_session, str(uuid.uuid4()), "customer_key")

    record = _reload(db_session, result.record.id)
    assert record.expires_at - record.first_seen_at == timedelta(hours=24)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (3600, timedelta(hours=1)),
        (172800, timedelta(hours=48)),
        (1800, timedelta(minutes=30)),
        (604800, timedelta(days=7)),
    ],
)
def test_a_different_configured_window_is_applied(
    db_session, configured_windows, configured, expected
):
    """Requirement 3 end to end: the file decides, and only the file changed."""
    configured_windows(configured)

    result = _register(db_session, str(uuid.uuid4()), "customer_key")

    record = _reload(db_session, result.record.id)
    assert record.expires_at - record.first_seen_at == expected


def test_changing_configuration_changes_behaviour_with_no_code_change(
    db_session, configured_windows
):
    """Two registrations, identical call sites, different windows — only the file moved."""
    configured_windows(3600)
    first = _register(db_session, str(uuid.uuid4()), "customer_key")

    configured_windows(21600)
    second = _register(db_session, str(uuid.uuid4()), "customer_key")

    first_record = _reload(db_session, first.record.id)
    second_record = _reload(db_session, second.record.id)

    assert first_record.expires_at - first_record.first_seen_at == timedelta(hours=1)
    assert second_record.expires_at - second_record.first_seen_at == timedelta(hours=6)


def test_an_explicitly_supplied_expires_at_wins(db_session):
    """The parameter stays an escape hatch; nothing in the platform passes one."""
    from datetime import UTC, datetime

    explicit = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
    result = _register(
        db_session, str(uuid.uuid4()), "customer_key", expires_at=explicit
    )

    assert _reload(db_session, result.record.id).expires_at == explicit


def test_reuse_after_expiry_gets_a_fresh_window(db_session):
    """The new generation's window is anchored on its own first_seen_at, not the old one."""
    from sqlalchemy import update

    from app.platform.idempotency.config import expiry_window_for

    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    window = expiry_window_for(IdempotencyKeyType.CUSTOMER_KEY)

    first = register_key_sync(
        session=db_session,
        key_value=key,
        key_type="customer_key",
        scope_id=scope,
        operation_type=OPERATION,
    )
    db_session.commit()

    db_session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.id == first.record.id)
        .values(status=IdempotencyStatus.EXPIRED)
    )
    db_session.commit()

    second = register_key_sync(
        session=db_session,
        key_value=key,
        key_type="customer_key",
        scope_id=scope,
        operation_type=OPERATION,
    )
    db_session.commit()

    assert second.result == RegistrationResultType.NEW

    old = _reload(db_session, first.record.id)
    new = _reload(db_session, second.record.id)

    assert new.expires_at - new.first_seen_at == window
    assert new.expires_at > old.expires_at
    assert old.expires_at == old.first_seen_at + window, "old window must be untouched"


# ── IDK and RR carry no clock ─────────────────────────────────────────────────────────


def test_internal_derived_key_gets_no_time_based_expiry(db_session):
    """S3T2 ends an IDK's life on settlement terminal state; the clock never does."""
    key = derive_internal_key(str(uuid.uuid4()), "settle_leg")

    result = _register(db_session, key, "internal_derived_key")

    record = _reload(db_session, result.record.id)
    assert record.key_type == IdempotencyKeyType.INTERNAL_DERIVED_KEY
    assert record.expires_at is None


def test_rail_reference_gets_no_time_based_expiry(db_session):
    """Expiring a live rail reference would free a key the network still honours."""
    key = generate_rail_reference(str(uuid.uuid4()), 1, "SWIFT")

    result = _register(db_session, key, "rail_reference")

    record = _reload(db_session, result.record.id)
    assert record.key_type == IdempotencyKeyType.RAIL_REFERENCE
    assert record.expires_at is None


def test_idk_and_rr_stay_null_even_when_ck_window_changes(
    db_session, configured_windows
):
    """Reconfiguring the customer-key window must not leak a clock onto the other types."""
    configured_windows(900)

    idk = _register(
        db_session, derive_internal_key(str(uuid.uuid4()), "fund"), "internal_derived_key"
    )
    rr = _register(
        db_session, generate_rail_reference(str(uuid.uuid4()), 2, "ACH"), "rail_reference"
    )
    ck = _register(db_session, str(uuid.uuid4()), "customer_key")

    assert _reload(db_session, idk.record.id).expires_at is None
    assert _reload(db_session, rr.record.id).expires_at is None

    ck_record = _reload(db_session, ck.record.id)
    assert ck_record.expires_at - ck_record.first_seen_at == timedelta(minutes=15)


def test_non_customer_keys_are_absent_from_the_sweep_index_predicate():
    """Belt and braces: even a stray expires_at could not pull them into the CK sweep."""
    from app.platform.idempotency.models import CK_SWEEP_PREDICATE_SQL

    assert "customer_key" in CK_SWEEP_PREDICATE_SQL
    assert "internal_derived_key" not in CK_SWEEP_PREDICATE_SQL
    assert "rail_reference" not in CK_SWEEP_PREDICATE_SQL


def test_gitops_configuration_lives_under_the_deployments_tree():
    """The window must be GitOps data, not an application constant or an env var."""
    parts = CONFIG_DIR.parts
    assert "deployments" in parts and "gitops" in parts and "reference-data" in parts
    assert (CONFIG_DIR / KEY_EXPIRY_FILENAME).is_file()
    assert pathlib.Path(CONFIG_DIR).is_absolute()
