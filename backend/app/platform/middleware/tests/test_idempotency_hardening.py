"""Hardening pass over the assembled idempotency middleware.

The per-slice suites each verify their own slice. This one verifies the
properties that only exist once all of them are assembled, and that are the ones
most likely to break silently:

* the state machine actually moves NEW → ACTIVE → COMPLETED/FAILED,
* concurrency is settled by the database, not by application timing,
* nothing holds a transaction or a row lock across the handler,
* the response the caller receives is byte- and header-identical to the one the
  handler produced, and
* the routes that were never in scope stayed out of it.

Integration tests; they need a real PostgreSQL.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.responses import JSONResponse

from app.platform.configuration.config import get_settings
from app.platform.idempotency import IdempotencyStatus
from app.platform.middleware.handlers import aner_exception_handler
from app.platform.middleware.services import (
    ERROR_IN_PROGRESS,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)
from app.shared.exceptions import AnerBaseException

ENABLED_PATH = "/api/v1/settlement/execute"


@pytest.fixture
def key() -> str:
    return str(uuid4())


@pytest.fixture
async def sessions() -> AsyncGenerator[Any, None]:
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _status(factory: Any, key_value: str) -> str | None:
    async with factory() as session:
        return await session.scalar(
            text("SELECT status FROM ledger.idempotency_record WHERE key_value = :k"),
            {"k": key_value},
        )


async def _count(factory: Any, key_value: str) -> int:
    async with factory() as session:
        return await session.scalar(
            text("SELECT count(*) FROM ledger.idempotency_record WHERE key_value = :k"),
            {"k": key_value},
        )


def _app(handler: Any, path: str = ENABLED_PATH) -> FastAPI:
    app = FastAPI()
    app.add_api_route(path, handler, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


# ── The state machine ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status_code", "terminal"),
    [
        pytest.param(200, IdempotencyStatus.COMPLETED, id="success-completed"),
        pytest.param(422, IdempotencyStatus.FAILED, id="business-error-failed"),
    ],
)
async def test_record_is_active_during_the_handler_and_terminal_after(
    key: str, sessions: Any, status_code: int, terminal: IdempotencyStatus
) -> None:
    """Both transitions in one request, observed from outside the middleware.

    The ACTIVE state exists only while the handler runs, so it can only be caught
    from inside it — and only through an independent connection, since an
    uncommitted registration would be invisible there.
    """
    observed: dict[str, Any] = {}

    async def handler(request: Request) -> Any:
        observed["during"] = await _status(sessions, key)
        return JSONResponse({"n": 1}, status_code=status_code)

    async with AsyncClient(
        transport=ASGITransport(app=_app(handler)), base_url="http://test"
    ) as ac:
        response = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == status_code
    assert observed["during"] == IdempotencyStatus.ACTIVE.value
    assert await _status(sessions, key) == terminal.value


# ── Concurrency is settled by the database ───────────────────────────────────


async def test_concurrent_burst_executes_the_operation_exactly_once(
    key: str, sessions: Any
) -> None:
    """N identical requests, one execution, one row — under a slow handler.

    The sleep widens the window in which every other request is contending, so
    the outcome is decided by the unique constraint rather than by the requests
    happening not to overlap.
    """
    executions: list[int] = []

    async def handler(request: Request) -> Any:
        executions.append(1)
        await asyncio.sleep(0.1)
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        responses = await asyncio.gather(
            *(
                ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
                for _ in range(10)
            )
        )

    assert len(executions) == 1, f"handler ran {len(executions)} times for one key"
    assert await _count(sessions, key) == 1
    assert sum(r.status_code == 200 for r in responses) >= 1
    assert {r.status_code for r in responses} <= {200, 409}


async def test_duplicates_do_not_execute_while_the_first_is_active(
    key: str,
) -> None:
    """Every request arriving during the first one is refused, not queued."""
    executions: list[int] = []
    inside = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: Request) -> Any:
        executions.append(1)
        inside.set()
        await release.wait()
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = asyncio.create_task(
            ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
        )
        await asyncio.wait_for(inside.wait(), timeout=5)

        others = await asyncio.gather(
            *(
                ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
                for _ in range(5)
            )
        )

        release.set()
        await first

    assert all(r.status_code == 409 for r in others), [r.status_code for r in others]
    assert all(r.json()["error_code"] == ERROR_IN_PROGRESS for r in others)
    assert len(executions) == 1


# ── Transaction boundaries ───────────────────────────────────────────────────


async def test_a_duplicate_is_answered_without_waiting_for_the_handler(
    key: str,
) -> None:
    """The 409 must not queue behind the in-flight request's handler.

    ``register_key``'s duplicate path takes ``SELECT … FOR UPDATE``. If the
    registration transaction were still open during the handler, this call would
    block for the handler's full duration instead of answering immediately — the
    failure mode that committing before ``call_next`` exists to prevent.
    """
    inside = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: Request) -> Any:
        inside.set()
        await release.wait()
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = asyncio.create_task(
            ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
        )
        await asyncio.wait_for(inside.wait(), timeout=5)

        started = asyncio.get_running_loop().time()
        second = await asyncio.wait_for(
            ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key}), timeout=5
        )
        elapsed = asyncio.get_running_loop().time() - started

        release.set()
        await first

    assert second.status_code == 409
    assert elapsed < 2.0, f"the duplicate waited {elapsed:.2f}s — a lock is held"


async def test_completion_commits_in_its_own_transaction(
    key: str, sessions: Any
) -> None:
    """Registration and completion are two commits, not one.

    Observed as two distinct visible states from an independent connection:
    ACTIVE while the handler runs, terminal afterwards. A single transaction
    could not show both.
    """
    during: dict[str, Any] = {}

    async def handler(request: Request) -> Any:
        during["status"] = await _status(sessions, key)
        return JSONResponse({"ok": True}, status_code=200)

    async with AsyncClient(
        transport=ASGITransport(app=_app(handler)), base_url="http://test"
    ) as ac:
        await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert during["status"] == IdempotencyStatus.ACTIVE.value
    assert await _status(sessions, key) == IdempotencyStatus.COMPLETED.value


# ── The rollback race, at the database level ─────────────────────────────────


async def test_conflicting_transaction_rollback_does_not_produce_a_500(
    key: str, sessions: Any
) -> None:
    """A conflict that never commits must not surface as NoResultFound.

    Driven through the database rather than by patching: a competing session
    inserts the same key and holds it uncommitted, so the request blocks inside
    ``INSERT … ON CONFLICT DO NOTHING``. When that session rolls back, the
    request must resolve normally — the window the registration service's
    ``scalar_one()`` can turn
    into an unhandled 500.
    """
    executions: list[int] = []

    async def handler(request: Request) -> Any:
        executions.append(1)
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler)

    async with sessions() as blocker:
        await blocker.execute(
            text(
                "INSERT INTO ledger.idempotency_record "
                "(id, key_value, scope_id, key_type, operation_type, status, first_seen_at) "
                "VALUES (gen_random_uuid(), :k, :s, "
                "CAST('customer_key' AS ledger.idempotency_key_type_enum), 'probe', "
                "CAST('active' AS ledger.idempotency_status_enum), now())"
            ),
            {"k": key, "s": ENABLED_PATH},
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            request = asyncio.create_task(
                ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
            )
            await asyncio.sleep(0.4)
            assert not request.done(), "expected the insert to block on the conflict"

            await blocker.rollback()
            response = await asyncio.wait_for(request, timeout=10)

    assert response.status_code != 500, response.text
    assert response.status_code == 200
    assert len(executions) == 1
    assert await _count(sessions, key) == 1


# ── Exceptions ───────────────────────────────────────────────────────────────


async def test_business_exception_becomes_a_cached_failed_response(
    key: str, sessions: Any
) -> None:
    """AnerBaseException is rendered below this middleware, so it is a response.

    ExceptionMiddleware is built *inside* IdempotencyMiddleware, which means a
    handled business error never reaches the except branch — it arrives as an
    ordinary 4xx and is cached like any other outcome, and therefore replays.
    """
    executions: list[int] = []

    async def handler(request: Request) -> Any:
        executions.append(1)
        raise AnerBaseException(
            detail="transaction is not APPROVED",
            error_code="INVALID_TRANSACTION_STATUS",
            status_code=409,
        )

    app = _app(handler)
    # Same ignore as app/main.py: Starlette types the handler as taking a bare
    # Exception, so a handler narrowed to a specific subclass never type-checks.
    app.add_exception_handler(AnerBaseException, aner_exception_handler)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
        second = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert first.status_code == 409
    assert first.json()["error_code"] == "INVALID_TRANSACTION_STATUS"
    assert await _status(sessions, key) == IdempotencyStatus.FAILED.value

    assert second.status_code == 409
    assert second.json()["error_code"] == "INVALID_TRANSACTION_STATUS"
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert len(executions) == 1, "the handler re-ran on replay"


# ── The response the caller receives ─────────────────────────────────────────


async def test_repeated_response_headers_survive_the_rebuild(key: str) -> None:
    """Regression: dict(response.headers) collapsed repeats and dropped cookies.

    Buffering the body means rebuilding the response, and rebuilding through a
    dict keeps one value per header name. HTTP allows several — Set-Cookie is the
    case that bites, but Vary, Link and WWW-Authenticate repeat too. A gated route
    must return exactly what an ungated one would.
    """

    async def handler(request: Request) -> Any:
        response = JSONResponse({"ok": True})
        response.raw_headers.append((b"set-cookie", b"a=1; Path=/"))
        response.raw_headers.append((b"set-cookie", b"b=2; Path=/"))
        response.raw_headers.append((b"vary", b"Accept"))
        response.raw_headers.append((b"vary", b"Origin"))
        return response

    async with AsyncClient(
        transport=ASGITransport(app=_app(handler)), base_url="http://test"
    ) as ac:
        gated = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    async with AsyncClient(
        transport=ASGITransport(app=_app(handler, path="/api/v1/payments")),
        base_url="http://test",
    ) as ac:
        ungated = await ac.post("/api/v1/payments")

    def multi(response: Any, name: str) -> list[str]:
        return [v for k, v in response.headers.multi_items() if k == name]

    assert multi(gated, "set-cookie") == ["a=1; Path=/", "b=2; Path=/"]
    assert multi(gated, "vary") == ["Accept", "Origin"]
    assert multi(gated, "set-cookie") == multi(ungated, "set-cookie")
    assert gated.headers["content-type"] == ungated.headers["content-type"]
    assert int(gated.headers["content-length"]) == len(gated.content)


async def test_background_tasks_still_run(key: str) -> None:
    """Draining the body must not strip work attached to the response.

    Background tasks execute in the downstream task after the body is sent, so
    buffering upstream should leave them alone — worth pinning, because the
    payments route uses exactly this pattern to start its workflow.
    """
    ran: list[str] = []

    async def handler(background_tasks: BackgroundTasks) -> dict[str, bool]:
        background_tasks.add_task(ran.append, "ran")
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=_app(handler)), base_url="http://test"
    ) as ac:
        response = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert ran == ["ran"], "background tasks did not run"


# ── Routes that were never in scope ──────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/api/v1/payments", id="payments"),
        pytest.param("/api/v1/onboarding/cases", id="onboarding"),
        pytest.param("/api/v1/ledger/transactions", id="ledger"),
    ],
)
async def test_legacy_idempotency_routes_are_untouched(
    path: str, key: str, sessions: Any
) -> None:
    """The three legacy implementations must see no middleware behaviour at all.

    Sent *with* an X-Idempotency-Key, which is the case most likely to go wrong:
    the header being present must not be enough to opt a route in. Nothing is
    registered, and a second identical call is not intercepted.
    """
    executions: list[int] = []

    async def handler(request: Request) -> Any:
        executions.append(1)
        return JSONResponse({"legacy": True}, status_code=200)

    app = _app(handler, path=path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = await ac.post(path, headers={"X-Idempotency-Key": key})
        second = await ac.post(path, headers={"X-Idempotency-Key": key})

    assert first.status_code == 200
    assert second.status_code == 200, "a legacy route was intercepted as a duplicate"
    assert len(executions) == 2, (
        "the idempotency middleware suppressed a legacy route's second execution"
    )
    assert await _count(sessions, key) == 0, "a legacy route registered a key"
