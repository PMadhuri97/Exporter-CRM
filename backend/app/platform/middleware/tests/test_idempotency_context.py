import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.platform.middleware.services import (
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)

ENABLED_PATH = "/api/v1/settlement/execute"
OTHER_PATH = "/api/v1/payments"


@pytest.fixture
def key() -> str:
    return str(uuid4())


@pytest.fixture
def seen() -> list[dict[str, Any]]:
    """The contextvars snapshot each handler invocation observed."""
    return []


def _build(seen: list[dict[str, Any]]) -> FastAPI:
    """A stub wired in the same order as ``create_app()``.

    Both routes share one handler so a request that reaches *either* records what
    it saw — which is how the leak tests tell "cleared" from "never bound".
    """
    app = FastAPI()

    async def endpoint(request: Request) -> dict[str, str]:
        seen.append(structlog.contextvars.get_contextvars())
        return {"handler": "reached"}

    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_api_route(OTHER_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


@pytest.fixture
def stub_app(seen: list[dict[str, Any]]) -> FastAPI:
    return _build(seen)


@pytest.fixture
async def client(stub_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        yield ac


# ── 1 & 2. The handler sees both values ──────────────────────────────────────


async def test_handler_sees_the_idempotency_key(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """Also proves the binding precedes the downstream task's creation.

    The handler runs in a child task that copied the context when it was created.
    If the bind happened after ``call_next``, this snapshot would not contain the
    key at all.
    """
    response = await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert seen[0]["idempotency_key"] == key


async def test_handler_sees_the_correlation_id(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    correlation_id = str(uuid4())

    await client.post(
        ENABLED_PATH,
        headers={"X-Idempotency-Key": key, "X-Correlation-Id": correlation_id},
    )

    assert seen[0]["correlation_id"] == correlation_id
    assert seen[0]["idempotency_key"] == key


# ── 3. The correlation ID is not disturbed ───────────────────────────────────


async def test_correlation_id_is_not_rebound(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """The client's ID must survive intact, in the context and on the response.

    CorrelationIdMiddleware owns this value. Re-binding it here could only
    overwrite a live value with a stale read, so the middleware binds the key and
    nothing else.
    """
    correlation_id = str(uuid4())

    response = await client.post(
        ENABLED_PATH,
        headers={"X-Idempotency-Key": key, "X-Correlation-Id": correlation_id},
    )

    assert seen[0]["correlation_id"] == correlation_id
    assert response.headers["X-Correlation-Id"] == correlation_id


async def test_binding_adds_only_the_key(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """Nothing else is introduced into the shared context.

    CorrelationIdMiddleware binds correlation_id, method and path; this middleware
    contributes exactly one more entry. Pinned because the context is shared
    platform state and every addition lands on every log line.
    """
    await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert set(seen[0]) == {"correlation_id", "method", "path", "idempotency_key"}


# ── 4. Parallel requests keep their own key ──────────────────────────────────


async def test_parallel_requests_do_not_cross_contaminate(
    client: AsyncClient, seen: list[dict[str, Any]]
) -> None:
    """Each in-flight request must observe its own key and no one else's.

    asyncio.gather wraps each coroutine in a task, and a task copies the context
    at creation, so sibling requests cannot see each other's bindings. Distinct
    keys are used so a leak shows up as a mismatch rather than a coincidence.
    """
    keys = [str(uuid4()) for _ in range(8)]

    responses = await asyncio.gather(
        *(
            client.post(ENABLED_PATH, headers={"X-Idempotency-Key": k})
            for k in keys
        )
    )

    assert all(r.status_code == 200 for r in responses)
    observed = [snapshot["idempotency_key"] for snapshot in seen]

    assert sorted(observed) == sorted(keys), (
        "a request observed a key that was not its own"
    )
    assert len(set(observed)) == len(keys), "a key was observed by two requests"


async def test_parallel_requests_keep_their_own_correlation_id(
    client: AsyncClient, seen: list[dict[str, Any]]
) -> None:
    """The same isolation must hold for the pair, not just the key alone.

    A binding that leaked would most plausibly show up as a key paired with
    another request's correlation ID, which asserting either field alone would
    miss.
    """
    pairs = [(str(uuid4()), str(uuid4())) for _ in range(6)]

    await asyncio.gather(
        *(
            client.post(
                ENABLED_PATH,
                headers={"X-Idempotency-Key": k, "X-Correlation-Id": c},
            )
            for k, c in pairs
        )
    )

    observed = {(s["idempotency_key"], s["correlation_id"]) for s in seen}

    assert observed == set(pairs), "a key was paired with the wrong correlation id"


# ── 5. Short-circuited requests bind nothing ─────────────────────────────────


@pytest.mark.parametrize(
    ("headers", "expected_status", "description"),
    [
        pytest.param({}, 400, "no key supplied", id="missing-key"),
        pytest.param({"X-Idempotency-Key": "not-a-uuid"}, 400, "malformed key", id="invalid-key"),
    ],
)
async def test_rejected_requests_never_reach_a_handler_to_bind_for(
    client: AsyncClient,
    seen: list[dict[str, Any]],
    headers: dict[str, str],
    expected_status: int,
    description: str,
) -> None:
    """A short-circuit returns before call_next, so there is nothing to bind for."""
    response = await client.post(ENABLED_PATH, headers=headers)

    assert response.status_code == expected_status, description
    assert seen == [], f"a handler ran despite: {description}"


async def test_duplicate_short_circuit_does_not_bind(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """A duplicate is served from the cache without binding — only NEW keys bind.

    The second request replays rather than conflicting, because the first now
    completes. Either way it returns without calling ``call_next``, so there is no
    downstream handler to bind for.
    """
    first = await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
    assert first.status_code == 200
    assert len(seen) == 1

    second = await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert len(seen) == 1, "the handler ran for a duplicate"


async def test_key_does_not_leak_into_a_later_ungated_request(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """The guarantee that makes the binding safe, asserted rather than assumed.

    Under ASGITransport both requests share the caller's context, which is the
    *worst* case — a real server gives each request its own task. What clears the
    key is CorrelationIdMiddleware's clear_contextvars() at the start of the
    second request. If that middleware were ever removed or reordered inside this
    one, this test is what would notice.
    """
    await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})
    assert seen[0]["idempotency_key"] == key

    await client.post(OTHER_PATH)

    assert len(seen) == 2
    assert "idempotency_key" not in seen[1], (
        "an ungated request inherited the previous request's key"
    )
    assert seen[1]["correlation_id"] != seen[0]["correlation_id"]


async def test_key_does_not_leak_into_a_later_rejected_request(
    client: AsyncClient, seen: list[dict[str, Any]], key: str
) -> None:
    """A rejected request must not carry the previous request's key in its error.

    The error body reads correlation_id out of the same context the key is bound
    into, so a stale key here would surface to the client.
    """
    await client.post(ENABLED_PATH, headers={"X-Idempotency-Key": key})

    response = await client.post(ENABLED_PATH)

    assert response.status_code == 400
    assert response.json()["idempotency_key"] is None, (
        "the previous request's key leaked into an unrelated error body"
    )
