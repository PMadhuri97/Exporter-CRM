"""Integration and unit tests for the Idempotency Key Registration Service."""

import concurrent.futures
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency import (
    IdempotencyKeyRegistrationService,
    IdempotencyStatus,
    InvalidKeyFormatError,
    RegistrationResultType,
    complete_key_sync,
    register_key_sync,
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


@pytest.fixture
async def async_session():
    settings = get_settings()
    async_engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session
    await async_engine.dispose()


def test_register_new_customer_key_success(db_session):
    """A new key registers successfully and returns registration_result of 'new'."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="transfer_funds",
        correlation_id=str(uuid.uuid4()),
    )
    db_session.commit()

    assert res.result == RegistrationResultType.NEW
    assert res.registration_result == "new"
    assert res.record is not None
    assert res.record.key_value == key_value
    assert res.record.scope_id == scope_id
    assert res.record.status == IdempotencyStatus.ACTIVE
    assert res.record.first_seen_at is not None


def test_register_duplicate_key_returns_existing_record(db_session):
    """The same key registered again within the same scope returns registration_result of 'duplicate'."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="transfer_funds",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None

    res2 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="transfer_funds",
    )
    db_session.commit()

    assert res2.result == RegistrationResultType.DUPLICATE
    assert res2.registration_result == "duplicate"
    assert res1.record is not None
    assert res2.record is not None
    assert res2.record.id == res1.record.id
    assert res2.record.key_value == key_value


def test_register_invalid_format_key_rejected(db_session):
    """A key with an invalid format is rejected at registration with a structured error identifying the violation."""
    invalid_key = "not-a-valid-uuid-v4"
    scope_id = str(uuid.uuid4())

    with pytest.raises(InvalidKeyFormatError) as exc_info:
        register_key_sync(
            session=db_session,
            key_value=invalid_key,
            key_type="customer_key",
            scope_id=scope_id,
            operation_type="transfer_funds",
        )

    err = exc_info.value
    assert err.validation_result is not None
    assert err.validation_result.is_valid is False
    assert err.validation_result.reason.value == "INVALID_UUID_V4"


def test_complete_key_transitions_active_to_completed(db_session):
    """A complete call transitions an active key to completed and stores the response cache."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    reg_res = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="payment_authorization",
    )
    db_session.commit()
    assert reg_res.record is not None
    assert reg_res.record.status == IdempotencyStatus.ACTIVE

    response_payload = {"status": "SUCCESS", "transaction_id": "tx_12345", "amount": 1000}

    completed_record = complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=response_payload,
    )
    db_session.commit()

    assert completed_record.status == IdempotencyStatus.COMPLETED
    assert completed_record.completed_at is not None
    assert completed_record.response_cache == response_payload


def test_complete_key_already_completed_is_idempotent_noop(db_session):
    """A complete call on an already-completed key returns the existing record without modification."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="payout",
    )
    db_session.commit()

    first_payload = {"status": "OK", "reference": "ref_1"}
    first_completion = complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=first_payload,
    )
    db_session.commit()

    # Second complete call with a different payload (should be no-op)
    second_payload = {"status": "OVERWRITE_ATTEMPT", "reference": "ref_2"}
    second_completion = complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=second_payload,
    )
    db_session.commit()

    assert second_completion.id == first_completion.id
    assert second_completion.status == IdempotencyStatus.COMPLETED
    assert second_completion.response_cache == first_payload


def test_complete_key_invalid_terminal_status_raises_value_error(db_session):
    """Passing an invalid terminal status raises ValueError with a clear error message."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    with pytest.raises(ValueError) as exc_info:
        complete_key_sync(
            session=db_session,
            key_value=key_value,
            scope_id=scope_id,
            terminal_status="active",
        )

    assert "Invalid terminal status 'active'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_idempotency_key_registration_service_flow(async_session):
    """Test full async surface using IdempotencyKeyRegistrationService (register_key and complete_key)."""
    service = IdempotencyKeyRegistrationService(session=async_session)
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    reg_res = await service.register_key(
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="async_payout",
        correlation_id=str(uuid.uuid4()),
    )
    await async_session.commit()

    assert reg_res.result == RegistrationResultType.NEW
    assert reg_res.record is not None
    assert reg_res.record.status == IdempotencyStatus.ACTIVE

    # Duplicate registration
    dup_res = await service.register_key(
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="async_payout",
    )
    await async_session.commit()

    assert dup_res.result == RegistrationResultType.DUPLICATE
    assert dup_res.record is not None
    assert dup_res.record.id == reg_res.record.id

    # Complete key
    payload = {"status": "SUCCESS", "tx_id": "tx_async_123"}
    completed_record = await service.complete_key(
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=payload,
    )
    await async_session.commit()

    assert completed_record.status == IdempotencyStatus.COMPLETED
    assert completed_record.response_cache == payload


def test_concurrent_registrations_10_runs(sync_engine):
    """Two or more simultaneous registrations of the same key produce exactly 1 new result across 10 runs."""
    session_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    for run_idx in range(10):
        key_value = str(uuid.uuid4())
        scope_id = str(uuid.uuid4())

        def register_worker(worker_id):
            session = session_factory()
            try:
                res = register_key_sync(
                    session=session,
                    key_value=key_value,
                    key_type="customer_key",
                    scope_id=scope_id,
                    operation_type="concurrent_test",
                )
                session.commit()
                return res.registration_result
            except Exception as e:
                session.rollback()
                return str(e)
            finally:
                session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(register_worker, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        new_count = results.count("new")
        duplicate_count = results.count("duplicate")

        assert new_count == 1, f"Run {run_idx}: Expected 1 'new' result, got {new_count}. Results: {results}"
        assert duplicate_count == 9, f"Run {run_idx}: Expected 9 'duplicate' results, got {duplicate_count}. Results: {results}"
