"""Registration behaviour around expired records (S3T1).

Uniqueness of (key_value, scope_id) holds over live rows only, so a key whose record has
expired is registrable again while the expired record stays put for audit. These tests pin
both halves of that: the new behaviour, and the duplicate behaviour that must NOT change.

Everything here runs against PostgreSQL. The partial unique index and the ON CONFLICT
inference that targets it are the whole subject — neither exists in SQLite, and a mocked
session would assert nothing.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency import (
    IdempotencyRecord,
    IdempotencyStatus,
    RegistrationResultType,
    complete_key_sync,
    get_record_sync,
    register_key_sync,
)

OPERATION = "s3t1_reuse_test"


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    """Session whose rows are removed afterwards, keyed on this suite's operation_type.

    Deleting by operation_type rather than by collected id also sweeps rows created by a
    test that failed part-way through, which is how the four stale rows in the shared dev
    database got there in the first place.
    """
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


def _register(session, key_value, scope_id, key_type="customer_key"):
    result = register_key_sync(
        session=session,
        key_value=key_value,
        key_type=key_type,
        scope_id=scope_id,
        operation_type=OPERATION,
    )
    session.commit()
    return result


def _expire(session, record_id):
    """Force a record to 'expired' the way the S3T1 sweep will in a later phase."""
    session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.id == record_id)
        .values(status=IdempotencyStatus.EXPIRED)
    )
    session.commit()


def _rows_for(session, key_value, scope_id):
    """Read every generation of a key straight from the database.

    expire_on_commit=False means the session hands back cached objects, which will happily
    report a status the database no longer holds. expire_all() forces the reload.
    """
    session.expire_all()
    return list(
        session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.key_value == key_value,
                IdempotencyRecord.scope_id == scope_id,
            )
            .order_by(IdempotencyRecord.first_seen_at)
        ).scalars()
    )


# ── Duplicate behaviour that must not change ──────────────────────────────────────────


def test_duplicate_while_active_returns_existing_record(db_session):
    """Case A — a live active record still short-circuits registration."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    second = _register(db_session, key, scope)

    assert first.result == RegistrationResultType.NEW
    assert second.result == RegistrationResultType.DUPLICATE
    assert second.record.id == first.record.id
    assert len(_rows_for(db_session, key, scope)) == 1


def test_duplicate_while_completed_returns_existing_record(db_session):
    """A completed record is still live: its cached response is what replay depends on."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
    )
    db_session.commit()

    second = _register(db_session, key, scope)

    assert second.result == RegistrationResultType.DUPLICATE
    assert second.record.id == first.record.id


def test_duplicate_while_failed_returns_existing_record(db_session):
    """Failed is terminal but not expired — the key stays claimed until the window closes."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="failed"
    )
    db_session.commit()

    second = _register(db_session, key, scope)

    assert second.result == RegistrationResultType.DUPLICATE
    assert second.record.id == first.record.id


def test_two_live_records_same_key_and_scope_are_rejected(db_session):
    """The partial index still enforces one live record per pair.

    Registration routes the conflict into a duplicate result rather than an error, so the
    proof that uniqueness held is that only one row exists.
    """
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    _register(db_session, key, scope)
    _register(db_session, key, scope)
    _register(db_session, key, scope)

    assert len(_rows_for(db_session, key, scope)) == 1


def test_same_key_different_scope_remains_independent(db_session):
    """Scope is part of the index, so the same key in another scope is a separate record."""
    key = str(uuid.uuid4())
    scope_a, scope_b = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope_a)
    second = _register(db_session, key, scope_b)

    assert first.result == RegistrationResultType.NEW
    assert second.result == RegistrationResultType.NEW
    assert first.record.id != second.record.id


# ── Reuse after expiry ────────────────────────────────────────────────────────────────


def test_expired_record_does_not_block_registration(db_session):
    """Case B — the expired record is ignored and a NEW record is created."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    _expire(db_session, first.record.id)

    second = _register(db_session, key, scope)

    assert second.result == RegistrationResultType.NEW
    assert second.record.id != first.record.id
    assert second.record.status == IdempotencyStatus.ACTIVE


def test_expired_record_is_left_untouched_by_reuse(db_session):
    """The old generation must survive reuse byte for byte — it is the audit trail."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    old_id = first.record.id
    _expire(db_session, old_id)

    before = _rows_for(db_session, key, scope)[0]
    snapshot = {
        "id": before.id,
        "key_value": before.key_value,
        "scope_id": before.scope_id,
        "key_type": before.key_type,
        "operation_type": before.operation_type,
        "status": before.status,
        "first_seen_at": before.first_seen_at,
        "expires_at": before.expires_at,
        "completed_at": before.completed_at,
    }

    _register(db_session, key, scope)

    after = next(r for r in _rows_for(db_session, key, scope) if r.id == old_id)
    assert {k: getattr(after, k) for k in snapshot} == snapshot
    assert after.status == IdempotencyStatus.EXPIRED


def test_reuse_leaves_both_generations_in_the_table(db_session):
    """Old and new coexist: one expired, one active, same key and scope."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    _expire(db_session, first.record.id)
    second = _register(db_session, key, scope)

    rows = _rows_for(db_session, key, scope)
    assert len(rows) == 2
    assert {r.status for r in rows} == {
        IdempotencyStatus.EXPIRED,
        IdempotencyStatus.ACTIVE,
    }
    assert {r.id for r in rows} == {first.record.id, second.record.id}


def test_active_record_is_returned_when_expired_and_active_coexist(db_session):
    """Case C — registration returns the live record, never the expired one, and adds nothing."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    _expire(db_session, first.record.id)
    second = _register(db_session, key, scope)

    third = _register(db_session, key, scope)

    assert third.result == RegistrationResultType.DUPLICATE
    assert third.record.id == second.record.id
    assert third.record.id != first.record.id
    assert third.record.status == IdempotencyStatus.ACTIVE
    assert len(_rows_for(db_session, key, scope)) == 2


def test_many_expired_generations_do_not_raise_multiple_results_found(db_session):
    """Case D — the regression guard for the crash this change would otherwise introduce.

    Before the status filter, the post-conflict lookup matched every generation and
    scalar_one() raised MultipleResultsFound. Three expired rows plus a live one is the
    shape that triggered it.
    """
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    expired_ids = []
    for _ in range(3):
        result = _register(db_session, key, scope)
        assert result.result == RegistrationResultType.NEW
        expired_ids.append(result.record.id)
        _expire(db_session, result.record.id)

    live = _register(db_session, key, scope)
    assert live.result == RegistrationResultType.NEW

    try:
        duplicate = _register(db_session, key, scope)
    except MultipleResultsFound as exc:  # pragma: no cover - the bug being guarded against
        pytest.fail(f"post-conflict lookup matched expired history: {exc}")

    assert duplicate.result == RegistrationResultType.DUPLICATE
    assert duplicate.record.id == live.record.id

    rows = _rows_for(db_session, key, scope)
    assert len(rows) == 4
    assert sum(r.status == IdempotencyStatus.EXPIRED for r in rows) == 3
    assert {r.id for r in rows if r.status == IdempotencyStatus.EXPIRED} == set(expired_ids)


def test_completion_after_reuse_targets_the_new_record(db_session):
    """Completion must act on the live generation, leaving expired history alone."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    _expire(db_session, first.record.id)
    second = _register(db_session, key, scope)

    completed = complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
    )
    db_session.commit()

    assert completed.id == second.record.id

    old = next(r for r in _rows_for(db_session, key, scope) if r.id == first.record.id)
    assert old.status == IdempotencyStatus.EXPIRED
    assert old.completed_at is None


# ── The read-only lookup carries the same exposure ────────────────────────────────────


def test_get_record_returns_the_live_row_across_expired_history(db_session):
    """The read-only mirror of Case D.

    get_record_sync is AL-103's unlocked inspection path, and it reaches the same key
    through a different statement than the post-conflict lookup does. Partial uniqueness
    exposes both of them to expired history, but only the locked path had a guard, so this
    is the read-only half: three expired generations plus a live one must still resolve to
    one record rather than raising MultipleResultsFound.
    """
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    for _ in range(3):
        expired = _register(db_session, key, scope)
        _expire(db_session, expired.record.id)

    live = _register(db_session, key, scope)

    try:
        found = get_record_sync(session=db_session, key_value=key, scope_id=scope)
    except MultipleResultsFound as exc:  # pragma: no cover - the bug being guarded against
        pytest.fail(f"unlocked lookup matched expired history: {exc}")

    assert found is not None
    assert found.id == live.record.id
    assert found.status == IdempotencyStatus.ACTIVE


def test_get_record_reports_no_live_registration_once_every_generation_expired(db_session):
    """A key whose every generation has expired holds no claim, so inspection says so.

    Inspection answers the question registration answers — "is this key claimed right
    now" — and after expiry the answer is no. Returning the expired row instead would let
    a caller treat released history as a live claim.
    """
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    _expire(db_session, first.record.id)

    assert get_record_sync(session=db_session, key_value=key, scope_id=scope) is None

    # The row is still on the table — released, not deleted.
    rows = _rows_for(db_session, key, scope)
    assert [r.status for r in rows] == [IdempotencyStatus.EXPIRED]
