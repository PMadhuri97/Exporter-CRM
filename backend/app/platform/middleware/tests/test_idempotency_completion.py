import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.responses import JSONResponse, PlainTextResponse

from app.platform.configuration.config import get_settings
from app.platform.idempotency import IdempotencyStatus
from app.platform.middleware import services as middleware_services
from app.platform.middleware.services import (
    ERROR_ALREADY_USED,
    REPLAY_HEADER,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)

ENABLED_PATH = "/api/v1/settlement/execute"


@pytest.fixture
def key() -> str:
    return str(uuid4())


@pytest.fixture
async def probe_sessions() -> AsyncGenerator[Any, None]:
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _record(factory: Any, key_value: str) -> Any:
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT status, response_cache, completed_at "
                "FROM ledger.idempotency_record WHERE key_value = :k"
            ),
            {"k": key_value},
        )
        return result.mappings().one_or_none()


def _app(handler: Any, calls: list[str]) -> FastAPI:
    app = FastAPI()

    async def endpoint(request: Request) -> Any:
        calls.append(request.url.path)
        return await handler(request)

    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


async def _call(app: FastAPI, key_value: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        return await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key_value})


# ── 1. A successful response is cached ───────────────────────────────────────


async def test_successful_response_is_cached(
    key: str, probe_sessions: Any
) -> None:
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse({"transaction": "settled"}, status_code=202)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 202
    assert response.json() == {"transaction": "settled"}

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.COMPLETED.value
    assert record["completed_at"] is not None
    assert record["response_cache"] == {
        "status_code": 202,
        "body": {"transaction": "settled"},
    }


# ── 2 & 3. Replay does not re-execute, and preserves the cached status ───────


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(200, id="200"),
        pytest.param(201, id="201"),
        pytest.param(202, id="202-async-accepted"),
    ],
)
async def test_replay_preserves_the_cached_status_without_re_executing(
    key: str, status_code: int
) -> None:
    """The status is carried in the envelope precisely so it is not flattened.

    POST /settlement/execute is a 200 today, but POST /payments is a 202 and the
    allowlist is meant to grow. A replay that always answered 200 would silently
    change the contract of any route that does not.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse({"n": len(calls)}, status_code=status_code)

    app = _app(handler, calls)

    first = await _call(app, key)
    second = await _call(app, key)

    assert first.status_code == status_code
    assert second.status_code == status_code, "the replay flattened the status"
    assert second.json() == first.json()
    assert second.headers[REPLAY_HEADER] == "true"
    assert calls == [ENABLED_PATH], "the handler ran again on replay"


# ── 4 & 5. A failed response is cached, and replays ──────────────────────────


async def test_failed_response_is_cached_and_replays(
    key: str, probe_sessions: Any
) -> None:
    """A 4xx is a completed outcome, not an absence of one.

    Replaying it matters: without this, a client retrying a request that was
    rejected for a business reason would re-execute the handler and could get a
    different answer.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse({"error_code": "INVALID_STATUS"}, status_code=422)

    app = _app(handler, calls)

    first = await _call(app, key)
    assert first.status_code == 422

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.FAILED.value
    assert record["response_cache"]["status_code"] == 422

    second = await _call(app, key)

    assert second.status_code == 422
    assert second.json() == {"error_code": "INVALID_STATUS"}
    assert second.headers[REPLAY_HEADER] == "true"
    assert calls == [ENABLED_PATH]


# ── 6. An unhandled exception still becomes a 500 ────────────────────────────


async def test_unhandled_exception_is_a_500_and_the_key_is_failed(
    key: str, probe_sessions: Any
) -> None:
    """The original exception must reach the server's own handling, unchanged.

    Swallowing it to record the failure would replace a 500 with something else
    and lose the traceback. The key is marked FAILED with no cache, so a retry is
    refused rather than replaying a response that never existed.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        raise RuntimeError("handler exploded")

    app = _app(handler, calls)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        with pytest.raises(RuntimeError, match="handler exploded"):
            await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.FAILED.value
    assert record["response_cache"] is None


async def test_exception_path_key_is_not_replayable(key: str) -> None:
    """FAILED with no cache is refused, not re-executed.

    Re-running is the duplicate execution the key exists to prevent, so the
    caller is told the key is spent and needs a new one.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        raise RuntimeError("handler exploded")

    app = _app(handler, calls)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        with pytest.raises(RuntimeError):
            await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

        second = await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert second.status_code == 409
    assert second.json()["error_code"] == ERROR_ALREADY_USED
    assert calls == [ENABLED_PATH], "the handler re-ran after failing"


# ── 7. A completion failure never replaces the response ──────────────────────


async def test_completion_failure_does_not_break_the_response(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bookkeeping must never cost the caller their result.

    Simulates the database being unavailable exactly at completion time. The
    handler already did the work; failing the request now would report a false
    error for an operation that actually succeeded.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse({"transaction": "settled"}, status_code=200)

    async def exploding_complete(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(middleware_services, "complete_key", exploding_complete)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 200
    assert response.json() == {"transaction": "settled"}
    assert calls == [ENABLED_PATH]


async def test_completion_failure_on_the_exception_path_preserves_the_exception(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing completion must not mask the error that caused it."""
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        raise RuntimeError("handler exploded")

    async def exploding_complete(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(middleware_services, "complete_key", exploding_complete)

    app = _app(handler, calls)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        with pytest.raises(RuntimeError, match="handler exploded"):
            await ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})


# ── 8 & 9. Uncacheable responses are still delivered ─────────────────────────


async def test_oversized_response_is_delivered_but_not_cached(
    key: str, probe_sessions: Any
) -> None:
    """Past the cache ceiling the payload is dropped, never truncated.

    A truncated cache would replay a body that is not what the caller received,
    which is worse than not replaying at all. The DB's own 64 KiB constraint would
    reject an oversized write and take the request down with it.
    """
    calls: list[str] = []
    big = "x" * (middleware_services.MAX_CACHE_BYTES + 1000)

    async def handler(request: Request) -> Any:
        return JSONResponse({"blob": big}, status_code=200)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 200
    assert response.json()["blob"] == big, "the delivered body was altered"

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.COMPLETED.value
    assert record["response_cache"] is None, "an oversized payload was written"


async def test_non_json_response_is_delivered_but_not_cached(
    key: str, probe_sessions: Any
) -> None:
    """The envelope holds JSON; anything else completes with no cache."""
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return PlainTextResponse("not json at all", status_code=200)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 200
    assert response.text == "not json at all"
    assert response.headers["content-type"].startswith("text/plain")

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.COMPLETED.value
    assert record["response_cache"] is None


async def test_uncacheable_response_replays_as_a_conflict(key: str) -> None:
    """Completed but uncacheable is refused rather than silently re-executed."""
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return PlainTextResponse("not json", status_code=200)

    app = _app(handler, calls)

    await _call(app, key)
    second = await _call(app, key)

    assert second.status_code == 409
    assert second.json()["error_code"] == ERROR_ALREADY_USED
    assert calls == [ENABLED_PATH]


# ── 10. The body survives being consumed ─────────────────────────────────────


async def test_response_body_is_intact_after_the_iterator_is_consumed(
    key: str,
) -> None:
    """Draining body_iterator is one-shot; the response has to be rebuilt.

    Checked byte-for-byte, and with a payload large enough to arrive in several
    chunks — a rebuild that mishandled chunking or left a stale content-length
    would truncate here rather than fail outright.
    """
    calls: list[str] = []
    payload = {"items": [{"i": i, "pad": "y" * 200} for i in range(50)]}

    async def handler(request: Request) -> Any:
        return JSONResponse(payload, status_code=200)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 200
    assert response.json() == payload
    assert response.content == json.dumps(payload, separators=(",", ":")).encode()
    assert int(response.headers["content-length"]) == len(response.content)


async def test_empty_body_response_is_handled(key: str, probe_sessions: Any) -> None:
    """A 204 has no body to drain and no JSON to cache; it must still complete."""
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse(None, status_code=204)

    response = await _call(_app(handler, calls), key)

    assert response.status_code == 204

    record = await _record(probe_sessions, key)
    assert record["status"] == IdempotencyStatus.COMPLETED.value


# ── Capture edge cases, exercised directly ───────────────────────────────────


async def test_capture_reemits_a_non_bytes_chunk_without_caching() -> None:
    """A zero-copy `http.response.pathsend` cannot be buffered, only forwarded.

    Driven against ``_capture`` directly: the ASGI servers that emit pathsend do
    so for file responses, which no allowlisted route returns, so there is no way
    to reach this branch through a request. Without a test it would be the one
    path in the capture that nothing ever executes.
    """
    from starlette.responses import Response as StarletteResponse

    from app.platform.middleware.services import _capture

    class _Streamed(StarletteResponse):
        def __init__(self) -> None:
            self.status_code = 200
            self.raw_headers = [
                (b"content-type", b"application/json"),
                (b"content-length", b"9"),
                (b"x-keep", b"1"),
            ]

        async def _chunks(self) -> Any:
            yield b"partial"
            yield {"type": "http.response.pathsend", "path": "/tmp/x"}

        @property
        def body_iterator(self) -> Any:
            return self._chunks()

    body, rebuilt = await _capture(_Streamed())

    assert body is None, "a non-bytes chunk must not be treated as a cacheable body"
    assert rebuilt.status_code == 200
    names = [k for k, _ in rebuilt.raw_headers]
    assert b"x-keep" in names, "unrelated headers were dropped"
    assert b"content-length" not in names, (
        "a stale content-length was carried onto a streamed response"
    )


async def test_replay_rejects_a_boolean_status_code() -> None:
    """bool subclasses int, so a naive isinstance check would accept `true`.

    Unreachable through our own writer; this pins the guard against a hand-edited
    row or a future envelope shape, which would otherwise replay as status 1.
    """
    from app.platform.middleware.services import _replay

    assert _replay({"status_code": True, "body": {}}) is None
    assert _replay({"status_code": 200, "body": {}}) is not None


async def test_replay_marks_the_response_without_leaking_internal_state(
    key: str,
) -> None:
    """The boolean marker only — the terminal state is not published.

    It is inferable from the replayed status code anyway, and exporting the
    registry's enum vocabulary would make an internal name part of the API.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler, calls)
    await _call(app, key)
    replayed = await _call(app, key)

    assert replayed.headers[REPLAY_HEADER] == "true"
    assert "X-Idempotent-Replay-Status" not in replayed.headers


# ── Concurrency across the whole lifecycle ───────────────────────────────────


async def test_one_execution_across_a_concurrent_burst(key: str) -> None:
    """The end-to-end guarantee: one key, one execution, whatever the timing.

    Losers may conflict or replay depending on whether the winner has completed
    yet; neither may re-execute.
    """
    calls: list[str] = []

    async def handler(request: Request) -> Any:
        await asyncio.sleep(0.05)
        return JSONResponse({"ok": True}, status_code=200)

    app = _app(handler, calls)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        responses = await asyncio.gather(
            *(
                ac.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
                for _ in range(6)
            )
        )

    assert calls == [ENABLED_PATH], "the handler executed more than once"
    assert {r.status_code for r in responses} <= {200, 409}
