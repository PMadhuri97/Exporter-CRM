"""Read-only sessions refuse writes at the ORM and at the transaction.

Three layers stand between a query service and a write: the ORM guard, the
READ ONLY transaction, and the role's privileges. This suite covers the first
two — the ones that belong to `app.platform.database` — and asserts they are
independent, because a guard that only works when the other is also present
proves nothing about either.

The role layer is covered where the roles are provisioned:
`app/platform/idempotency/tests/test_audit_query_roles.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.platform.configuration.config import get_settings
from app.platform.database.read_only import (
    READ_ONLY_CONNECT_ARGS,
    READ_ONLY_SQL_TRANSACTION,
    ReadOnlySessionError,
    forbid_writes,
)
from app.platform.idempotency.models import IdempotencyRecord

pytestmark = pytest.mark.anyio


def _sqlstate(error: DBAPIError) -> str | None:
    """The driver's SQLSTATE. ``orig`` is typed loosely, so read it defensively."""
    return getattr(error.orig, "sqlstate", None)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _session_factory(*, read_only_transaction: bool):
    """A NullPool session factory on the owner's credentials.

    Deliberately the *writable* role. The point of these tests is that the two
    application-side guards refuse a write on their own, without the database
    role helping — running them as a read-only role would let a privilege error
    masquerade as the guard working.
    """
    engine = create_async_engine(
        get_settings().DATABASE_URL,
        poolclass=NullPool,
        connect_args=READ_ONLY_CONNECT_ARGS if read_only_transaction else {},
    )
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


# ── Layer 1: the ORM guard ────────────────────────────────────────────────────


async def test_orm_guard_rejects_a_pending_insert() -> None:
    """add() then flush() raises in Python, before any SQL reaches the database."""
    engine, factory = _session_factory(read_only_transaction=False)
    try:
        async with factory() as session:
            forbid_writes(session)
            session.add(
                IdempotencyRecord(
                    key_value="guarded",
                    scope_id="guarded",
                    key_type="customer_key",
                    operation_type="test",
                    status="active",
                )
            )
            with pytest.raises(ReadOnlySessionError) as exc:
                await session.flush()
    finally:
        await engine.dispose()

    assert "IdempotencyRecord" in str(exc.value), (
        "the guard should name what was pending, so the message points at the mistake"
    )


async def test_orm_guard_rejects_a_pending_delete() -> None:
    """delete() is a write too — the guard must not only cover inserts."""
    engine, factory = _session_factory(read_only_transaction=False)
    try:
        async with factory() as session:
            existing = (
                await session.execute(text("SELECT id FROM ledger.idempotency_record LIMIT 1"))
            ).first()
            if existing is None:
                pytest.skip("no idempotency record available to attempt a delete against")
            record = await session.get(IdempotencyRecord, existing[0])
            forbid_writes(session)
            await session.delete(record)
            with pytest.raises(ReadOnlySessionError):
                await session.flush()
    finally:
        await engine.dispose()


async def test_a_session_without_the_guard_still_flushes() -> None:
    """The guard is what refuses the write, not something else in the stack.

    Without this, every assertion above would also pass if flush() were broken
    for an unrelated reason.
    """
    engine, factory = _session_factory(read_only_transaction=False)
    try:
        async with factory() as session:
            session.add(
                IdempotencyRecord(
                    key_value="unguarded-probe",
                    scope_id="unguarded-probe",
                    key_type="customer_key",
                    operation_type="test",
                    status="active",
                )
            )
            await session.flush()
            await session.rollback()
    finally:
        await engine.dispose()


async def test_reads_are_unaffected_by_the_guard() -> None:
    """A guard that also blocked SELECT would make the query service useless."""
    engine, factory = _session_factory(read_only_transaction=False)
    try:
        async with factory() as session:
            forbid_writes(session)
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


# ── Layer 2: the READ ONLY transaction ────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO ledger.idempotency_record (id, key_value, scope_id, key_type, "
        "operation_type, status) VALUES (gen_random_uuid(), 'x', 'x', 'customer_key', 'x', 'active')",
        "UPDATE ledger.idempotency_record SET operation_type = 'x'",
        "DELETE FROM ledger.idempotency_record",
    ),
    ids=("insert", "update", "delete"),
)
async def test_read_only_transaction_refuses_raw_sql(statement: str) -> None:
    """Raw SQL bypasses the ORM entirely, so the ORM guard cannot be the thing stopping it.

    Runs on the owner's credentials: the role could write, and the transaction
    setting is the only reason it does not.
    """
    engine, factory = _session_factory(read_only_transaction=True)
    try:
        async with factory() as session:
            with pytest.raises(DBAPIError) as exc:
                await session.execute(text(statement))
    finally:
        await engine.dispose()

    assert _sqlstate(exc.value) == READ_ONLY_SQL_TRANSACTION, (
        f"expected a read-only-transaction refusal, got {_sqlstate(exc.value)}"
    )


async def test_read_only_transaction_permits_select() -> None:
    engine, factory = _session_factory(read_only_transaction=True)
    try:
        async with factory() as session:
            result = await session.execute(text("SELECT count(*) FROM ledger.idempotency_record"))
            assert result.scalar_one() >= 0
    finally:
        await engine.dispose()


async def test_ddl_is_refused_in_a_read_only_transaction() -> None:
    """CREATE TABLE is not DML, and a read-only guard that missed it would leak."""
    engine, factory = _session_factory(read_only_transaction=True)
    try:
        async with factory() as session:
            with pytest.raises(DBAPIError) as exc:
                await session.execute(text("CREATE TABLE ledger.should_not_exist (id integer)"))
    finally:
        await engine.dispose()

    assert _sqlstate(exc.value) == READ_ONLY_SQL_TRANSACTION
