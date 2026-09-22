"""Integration and contract tests for the Idempotency Duplicate Handling Contract."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import psycopg2
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency import (
    DuplicateHandlingAction,
    DuplicateOperationConflictError,
    DuplicateOperationFailedError,
    IdempotencyRecord,
    IdempotencyStatus,
    RegistrationResultType,
    ResponseCacheExceededError,
    complete_key_sync,
    evaluate_duplicate_contract,
    handle_duplicate_contract,
    register_key_sync,
)


def pg_connect():
    settings = get_settings()
    url = settings.DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url, options="-c search_path=ledger,public")


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
def clean_records():
    records = []
    yield records
    if records:
        conn = pg_connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM ledger.idempotency_record WHERE id = ANY(%s)", (records,))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()


def test_contract_active_status_returns_conflict(db_session, clean_records):
    """Active key duplicate registration evaluates to CONFLICT_ACTIVE (409 Conflict)."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="create_payment",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None
    clean_records.append(str(res1.record.id))

    res2 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="create_payment",
    )
    assert res2.result == RegistrationResultType.DUPLICATE

    contract_eval = evaluate_duplicate_contract(res2)
    assert contract_eval.action == DuplicateHandlingAction.CONFLICT_ACTIVE
    assert contract_eval.status == IdempotencyStatus.ACTIVE

    # Calling handle_duplicate_contract raises DuplicateOperationConflictError (HTTP 409)
    with pytest.raises(DuplicateOperationConflictError) as exc_info:
        handle_duplicate_contract(res2)

    assert key_value in str(exc_info.value)
    assert "in progress" in str(exc_info.value)


def test_contract_completed_status_returns_cached_response(db_session, clean_records):
    """Completed key duplicate registration evaluates to RETURN_CACHED_SUCCESS with payload."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="ledger_posting",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None
    clean_records.append(str(res1.record.id))

    cached_ledger_transaction = {
        "transaction_id": "tx_abc123",
        "amount": "250.00",
        "currency": "USD",
        "status": "posted",
    }

    complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=cached_ledger_transaction,
    )
    db_session.commit()

    res2 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="ledger_posting",
    )
    assert res2.result == RegistrationResultType.DUPLICATE

    contract_eval = evaluate_duplicate_contract(res2)
    assert contract_eval.action == DuplicateHandlingAction.RETURN_CACHED_SUCCESS
    assert contract_eval.status == IdempotencyStatus.COMPLETED
    assert contract_eval.response_cache == cached_ledger_transaction


def test_contract_failed_status_returns_cached_failure_and_blocks_reexecution(db_session, clean_records):
    """Failed key duplicate registration evaluates to RETURN_CACHED_FAILURE and prevents re-execution."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="settle_batch",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None
    clean_records.append(str(res1.record.id))

    cached_failure = {
        "error_code": "RAIL_UNAVAILABLE",
        "message": "Payment rail response timed out",
    }

    complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="failed",
        response_payload=cached_failure,
    )
    db_session.commit()

    res2 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="settle_batch",
    )
    assert res2.result == RegistrationResultType.DUPLICATE

    contract_eval = evaluate_duplicate_contract(res2)
    assert contract_eval.action == DuplicateHandlingAction.RETURN_CACHED_FAILURE
    assert contract_eval.status == IdempotencyStatus.FAILED
    assert contract_eval.response_cache == cached_failure

    # Calling handle_duplicate_contract raises DuplicateOperationFailedError
    with pytest.raises(DuplicateOperationFailedError) as exc_info:
        handle_duplicate_contract(res2)

    assert "previously failed" in str(exc_info.value)
    assert "new key must be generated" in str(exc_info.value)


def test_contract_expired_status_treats_as_new_key(db_session, clean_records):
    """An EXPIRED key is reusable: registration creates a NEW record beside the old one.

    S3T1 lifecycle: a key becomes reusable only once it carries status EXPIRED, which the
    sweep assigns to terminal (completed/failed) records whose window has closed. A record
    that is still ACTIVE stays a duplicate however old its expires_at is, so the transition
    is made explicitly here rather than by backdating the window.
    """
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="payout",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None
    clean_records.append(str(res1.record.id))

    original_id = res1.record.id
    original = {
        "key_value": res1.record.key_value,
        "scope_id": res1.record.scope_id,
        "first_seen_at": res1.record.first_seen_at,
        "expires_at": res1.record.expires_at,
    }

    db_session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.id == original_id)
        .values(status=IdempotencyStatus.EXPIRED)
    )
    db_session.commit()

    future_expiration = datetime.now(UTC) + timedelta(hours=1)
    res2 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="payout",
        expires_at=future_expiration,
    )
    db_session.commit()
    assert res2.result == RegistrationResultType.NEW
    assert res2.record is not None
    clean_records.append(str(res2.record.id))

    # Reuse is permitted, and it creates a record rather than mutating the old one.
    assert res2.record.id != original_id
    assert res2.record.status == IdempotencyStatus.ACTIVE
    assert res2.record.expires_at is not None
    assert res2.record.expires_at > datetime.now(UTC)

    # The expired generation survives untouched beside the new one.
    db_session.expire_all()
    old = db_session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.id == original_id)
    ).scalar_one()
    assert old.status == IdempotencyStatus.EXPIRED
    assert {k: getattr(old, k) for k in original} == original


def test_response_cache_size_limit_exceeded(db_session, clean_records):
    """Response cache payload exceeding 64 KB raises ResponseCacheExceededError."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    res1 = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="large_payload_test",
    )
    db_session.commit()
    assert res1.result == RegistrationResultType.NEW
    assert res1.record is not None
    clean_records.append(str(res1.record.id))

    oversized_payload = {"data": "x" * 66000}

    with pytest.raises(ResponseCacheExceededError) as exc_info:
        complete_key_sync(
            session=db_session,
            key_value=key_value,
            scope_id=scope_id,
            terminal_status="completed",
            response_payload=oversized_payload,
        )

    assert "exceeds maximum limit" in str(exc_info.value)


def test_duplicate_completed_key_bypasses_downstream_service(db_session, clean_records):
    """Duplicate request against a completed key returns cached response without calling downstream service."""
    key_value = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())

    downstream_service = MagicMock()

    # Initial registration & completion
    reg_result = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="transfer",
    )
    db_session.commit()
    assert reg_result.result == RegistrationResultType.NEW
    assert reg_result.record is not None
    clean_records.append(str(reg_result.record.id))

    # Downstream service executes initial transfer
    downstream_result = {"settlement_id": "stl_8899", "status": "SETTLED"}
    downstream_service.execute_transfer(amount=100)

    complete_key_sync(
        session=db_session,
        key_value=key_value,
        scope_id=scope_id,
        terminal_status="completed",
        response_payload=downstream_result,
    )
    db_session.commit()
    downstream_service.reset_mock()

    # Duplicate call
    dup_reg_result = register_key_sync(
        session=db_session,
        key_value=key_value,
        key_type="customer_key",
        scope_id=scope_id,
        operation_type="transfer",
    )
    assert dup_reg_result.result == RegistrationResultType.DUPLICATE

    contract_eval = evaluate_duplicate_contract(dup_reg_result)
    assert contract_eval.action == DuplicateHandlingAction.RETURN_CACHED_SUCCESS

    # Downstream service MUST NOT be invoked
    downstream_service.execute_transfer.assert_not_called()
    assert contract_eval.response_cache == downstream_result
