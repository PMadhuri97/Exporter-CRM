"""Registration and duplicate routing.

These are integration tests and need a real PostgreSQL. The central guarantee
cannot be established any other way: *the registration is committed
before the handler runs*, and "committed" only means anything when a second,
independent connection can see it.

Several tests therefore reach into the database from **inside** the handler,
through a connection the middleware knows nothing about. That is deliberate — a
same-session read would be satisfied by an uncommitted transaction and would
prove nothing.

Registration is persistent, so every test mints its own key. A shared constant is
accepted exactly once and is a duplicate on every later use, in this run or the
next.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.platform.configuration.config import get_settings
from app.platform.idempotency import IdempotencyStatus
from app.platform.middleware import services as middleware_services
from app.platform.middleware.services import (
    ERROR_ALREADY_USED,
    ERROR_IN_PROGRESS,
    REPLAY_HEADER,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)

ENABLED_PATH = "/api/v1/settlement/execute"
SCOPE_ID = ENABLED_PATH
OPERATION_TYPE = f"POST {ENABLED_PATH}"


@pytest.fixture
def key() -> str:
    return str(uuid4())


@pytest.fixture
async def probe_sessions() -> AsyncGenerator[Any, None]:
    """A session factory on its own engine, independent of the app's.

    Not ``database.AsyncSessionLocal``: that is the very factory the middleware
    uses, and conftest rebinds it. A separate engine guarantees a separate
    connection, which is what makes "the row is visible elsewhere" a real claim.
    """
    # NullPool for the same reason conftest uses it: on Windows, asyncpg's
    # overlapped-IO futures are cancelled for idle pooled connections between
    # tests, which surfaces as noise during teardown.
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _row(factory: Any, key_value: str) -> Any:
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT key_value, scope_id, operation_type, status, key_type, "
                "       expires_at, first_seen_at, correlation_id, created_by "
                "FROM ledger.idempotency_record WHERE key_value = :k"
            ),
            {"k": key_value},
        )
        return result.mappings().one_or_none()


async def _count(factory: Any, key_value: str) -> int:
    async with factory() as session:
        return await session.scalar(
            text("SELECT count(*) FROM ledger.idempotency_record WHERE key_value = :k"),
            {"k": key_value},
        )


@pytest.fixture
def handled() -> list[str]:
    return []


@pytest.fixture
def stub_app(handled: list[str]) -> FastAPI:
    app = FastAPI()

    async def endpoint(request: Request) -> dict[str, str]:
        handled.append(request.url.path)
        return {"handler": "reached"}

    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


@pytest.fixture
async def client(stub_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=stub_app), base_url="http://test") as ac:
        yield ac


def _post(client: AsyncClient, key_value: str):
    return client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key_value})


# ── 1. A new key registers and the handler runs ──────────────────────────────


async def test_new_key_registers_and_reaches_the_handler(
    client: AsyncClient, handled: list[str], key: str, probe_sessions: Any
) -> None:
    """The record is ACTIVE while the handler runs and COMPLETED once it returns.

    The intermediate state is asserted in
    ``test_registration_is_visible_from_an_independent_session_inside_handler``,
    which is the only place it is observable from outside.
    """
    response = await _post(client, key)

    assert response.status_code == 200
    assert handled == [ENABLED_PATH]

    row = await _row(probe_sessions, key)
    assert row is not None, "no record was written"
    assert row["status"] == IdempotencyStatus.COMPLETED.value


# ── 2. An active duplicate is refused ────────────────────────────────────────


async def test_active_duplicate_returns_409_without_running_the_handler(
    stub_app: FastAPI, handled: list[str], key: str
) -> None:
    """A genuinely in-flight duplicate, not a sequential one.

    Now that completion works, a second request issued *after* the first returns
    finds a COMPLETED record and replays it. Reaching the ACTIVE branch requires a
    real overlap, so the handler is held open while the second request is issued —
    which is also the situation the branch exists for.
    """
    inside = asyncio.Event()
    release = asyncio.Event()

    async def slow(request: Request) -> dict[str, str]:
        handled.append(request.url.path)
        inside.set()
        await release.wait()
        return {"handler": "reached"}

    app = FastAPI()
    app.add_api_route(ENABLED_PATH, slow, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        first = asyncio.create_task(ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key}))
        await asyncio.wait_for(inside.wait(), timeout=5)

        second = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

        release.set()
        first_response = await first

    assert second.status_code == 409
    assert second.json()["error_code"] == ERROR_IN_PROGRESS
    assert second.json()["error_context"]["reason"] == IdempotencyStatus.ACTIVE.value
    assert first_response.status_code == 200
    assert handled == [ENABLED_PATH], "the handler ran a second time for one key"


# ── 3. The registration is committed before the handler runs ─────────────────


async def test_registration_is_visible_from_an_independent_session_inside_handler(
    stub_app: FastAPI, key: str, probe_sessions: Any
) -> None:
    """The guarantee registration exists to provide, asserted where it matters.

    Reading through a connection the middleware never touches: if the
    registration were still in an open transaction, this SELECT would find
    nothing, and a concurrent request could execute the same operation twice.
    """
    seen: dict[str, Any] = {}

    async def endpoint(request: Request) -> dict[str, str]:
        seen["row"] = await _row(probe_sessions, key)
        return {"handler": "reached"}

    app = FastAPI()
    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert seen["row"] is not None, "registration was not committed before call_next"
    assert seen["row"]["status"] == IdempotencyStatus.ACTIVE.value


# ── 4. Concurrency ───────────────────────────────────────────────────────────


async def test_concurrent_same_key_requests_register_exactly_once(
    client: AsyncClient, handled: list[str], key: str, probe_sessions: Any
) -> None:
    """The property the unique constraint exists for, driven through HTTP."""
    responses = await asyncio.gather(
        *(_post(client, key) for _ in range(8)), return_exceptions=True
    )

    # `not isinstance(r, BaseException)` rather than Exception: gather with
    # return_exceptions=True can hand back either, and narrowing on the narrower
    # type leaves a BaseException in the list that has no status_code.
    statuses = [r.status_code for r in responses if not isinstance(r, BaseException)]

    # Asserted on the invariants rather than on an exact status split: a loser
    # that arrives after the winner has completed replays a 200 instead of
    # conflicting with a 409, and which it gets is a matter of timing. What must
    # hold regardless is that the operation executed once and owns one row.
    assert handled == [ENABLED_PATH], "the handler ran more than once for one key"
    assert await _count(probe_sessions, key) == 1
    assert set(statuses) <= {200, 409}, statuses
    assert len(statuses) == 8


# ── 5. The post-conflict lookup race ─────────────────────────────────────────


async def test_registration_retries_once_on_no_result_found(
    client: AsyncClient, handled: list[str], key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ON CONFLICT DO NOTHING can return no row while none was ever committed.

    The registration service resolves that with `scalar_one()`, which raises
    NoResultFound rather than
    returning None — not an IdempotencyError, so unhandled it would surface as a
    500. The middleware retries the whole registration once.
    """
    calls = {"n": 0}
    real = middleware_services.register_key

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NoResultFound("simulated post-conflict lookup race")
        return await real(*args, **kwargs)

    monkeypatch.setattr(middleware_services, "register_key", flaky)

    response = await _post(client, key)

    assert calls["n"] == 2, "the registration was not retried exactly once"
    assert response.status_code == 200
    assert handled == [ENABLED_PATH]


async def test_registration_propagates_a_second_no_result_found(
    client: AsyncClient, handled: list[str], key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One retry, not a loop: a second failure is not this race and must surface."""

    async def always_raises(*args: Any, **kwargs: Any) -> Any:
        raise NoResultFound("persistent")

    monkeypatch.setattr(middleware_services, "register_key", always_raises)

    with pytest.raises(NoResultFound):
        await _post(client, key)

    assert handled == [], "the handler ran despite registration failing"


# ── 6. No lock survives into the handler ─────────────────────────────────────


async def test_no_row_lock_is_held_across_call_next(
    stub_app: FastAPI, key: str, probe_sessions: Any
) -> None:
    """The duplicate path takes SELECT … FOR UPDATE; it must not outlive commit.

    Held open, that lock would block every retry of the same key for as long as
    the handler runs. `FOR UPDATE NOWAIT` from inside the handler fails loudly if
    anyone still holds it, so this asserts the absence of a lock rather than
    hoping for it.
    """
    outcome: dict[str, Any] = {}

    async def endpoint(request: Request) -> dict[str, str]:
        async with probe_sessions() as session:
            try:
                await session.execute(
                    text(
                        "SELECT 1 FROM ledger.idempotency_record "
                        "WHERE key_value = :k FOR UPDATE NOWAIT"
                    ),
                    {"k": key},
                )
                outcome["locked"] = False
            except Exception as exc:  # noqa: BLE001 - recorded, asserted below
                outcome["locked"] = True
                outcome["error"] = str(exc)
            await session.rollback()
        return {"handler": "reached"}

    app = FastAPI()
    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert (
        outcome["locked"] is False
    ), f"a row lock survived into the handler: {outcome.get('error')}"


# ── 7, 8, 9. What gets written ───────────────────────────────────────────────


async def test_scope_id_is_the_route_template(
    client: AsyncClient, key: str, probe_sessions: Any
) -> None:
    """The template, not the concrete URL — bounded cardinality, and stable."""
    await _post(client, key)
    row = await _row(probe_sessions, key)

    assert row["scope_id"] == SCOPE_ID


async def test_operation_type_is_method_and_template(
    client: AsyncClient, key: str, probe_sessions: Any
) -> None:
    await _post(client, key)
    row = await _row(probe_sessions, key)

    assert row["operation_type"] == OPERATION_TYPE
    assert len(row["operation_type"]) <= 100, "would not fit the column"


async def test_expires_at_is_populated(client: AsyncClient, key: str, probe_sessions: Any) -> None:
    """Nothing reads expires_at yet, but a row written without it is unrecoverable.

    There is no reaper and nothing ever writes EXPIRED, so a key stranded ACTIVE by
    a crash stays that way. Writing the timestamp now is what makes those rows
    reclaimable when a reaper is built.
    """
    await _post(client, key)
    row = await _row(probe_sessions, key)

    assert row["expires_at"] is not None
    delta = row["expires_at"] - row["first_seen_at"]
    assert abs(delta - middleware_services.KEY_TTL).total_seconds() < 60


async def test_key_type_and_identity_columns(
    client: AsyncClient, key: str, probe_sessions: Any
) -> None:
    """The inbound key is a root/customer key, and there is no actor to record.

    `created_by` stays null on purpose: this runs before the route's auth
    dependency, so no authenticated identity exists to attribute the row to.
    """
    await _post(client, key)
    row = await _row(probe_sessions, key)

    assert row["key_type"] == "customer_key"
    assert row["created_by"] is None
    assert row["correlation_id"] is not None


# ── Terminal states ──────────────────────────────────────────────────────────


async def _complete(factory: Any, key_value: str, status: str, cache: str | None) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE ledger.idempotency_record "
                "SET status = CAST(:s AS ledger.idempotency_status_enum), "
                "    response_cache = CAST(:c AS jsonb), completed_at = now() "
                "WHERE key_value = :k"
            ),
            {"s": status, "c": cache, "k": key_value},
        )
        await session.commit()


@pytest.mark.parametrize(
    ("status", "cached_status_code"),
    [
        pytest.param(IdempotencyStatus.COMPLETED.value, 202, id="completed"),
        pytest.param(IdempotencyStatus.FAILED.value, 422, id="failed"),
    ],
)
async def test_terminal_duplicate_replays_the_cached_response(
    client: AsyncClient,
    handled: list[str],
    key: str,
    probe_sessions: Any,
    status: str,
    cached_status_code: int,
) -> None:
    """Both terminal states replay; the cached status is preserved, not flattened.

    The record is completed directly here because the slice that writes the cache
    is not built yet — this asserts the read side against the envelope shape it
    will write.
    """
    await _post(client, key)
    handled.clear()
    await _complete(
        probe_sessions,
        key,
        status,
        f'{{"status_code": {cached_status_code}, "body": {{"replayed": true}}}}',
    )

    response = await _post(client, key)

    assert response.status_code == cached_status_code
    assert response.json() == {"replayed": True}
    assert response.headers[REPLAY_HEADER] == "true"
    assert handled == [], "the handler ran on a replay"


async def test_terminal_duplicate_without_a_cache_is_refused(
    client: AsyncClient, handled: list[str], key: str, probe_sessions: Any
) -> None:
    """Nothing to replay, and re-running is the duplicate execution to prevent.

    Distinct from the in-progress conflict: retrying will never help here, so the
    code says the key is spent rather than busy.
    """
    await _post(client, key)
    handled.clear()
    await _complete(probe_sessions, key, IdempotencyStatus.COMPLETED.value, None)

    response = await _post(client, key)

    assert response.status_code == 409
    assert response.json()["error_code"] == ERROR_ALREADY_USED
    assert handled == []


async def test_expired_is_reclaimed_and_treated_as_new(
    client: AsyncClient, handled: list[str], key: str, probe_sessions: Any
) -> None:
    """EXPIRED keys are now reclaimed by the registration service.

    Instead of failing closed, an explicitly EXPIRED status is treated as abandoned
    and automatically reset to ACTIVE for the new execution.
    """
    await _post(client, key)
    handled.clear()
    async with probe_sessions() as session:
        await session.execute(
            text(
                "UPDATE ledger.idempotency_record "
                "SET status = CAST('expired' AS ledger.idempotency_status_enum) "
                "WHERE key_value = :k"
            ),
            {"k": key},
        )
        await session.commit()

    response = await _post(client, key)

    assert response.status_code == 200
    assert handled == [ENABLED_PATH]
