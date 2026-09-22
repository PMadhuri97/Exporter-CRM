"""The accepted key as outbound context, read through the public accessor.

``test_idempotency_context.py`` asserts what the middleware binds, in terms of the
raw contextvars store. This file asserts the contract downstream code actually
depends on: that ``current_idempotency_key()`` — not a hand-rolled read of the
logging context — returns the caller's key inside a gated request and ``None``
everywhere else.

The distinction matters because the two can drift. A change to the field name, or
to which middleware owns the binding, has to keep the accessor working; a test
that only reads ``get_contextvars()["idempotency_key"]`` would keep passing while
every real caller broke.
"""
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.platform.idempotency import current_idempotency_key
from app.platform.middleware.services import (
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)

GATED_PATH = "/api/v1/settlement/execute"
UNGATED_PATH = "/api/v1/payments"


@pytest.fixture
def key() -> str:
    return str(uuid4())


@pytest.fixture
def observed() -> list[str | None]:
    """What ``current_idempotency_key()`` returned inside each handler call."""
    return []


@pytest.fixture
def stub_app(observed: list[str | None]) -> FastAPI:
    """Two routes, one gated, sharing a handler that records what it can see."""
    app = FastAPI()

    async def endpoint(request: Request) -> dict[str, Any]:
        observed.append(current_idempotency_key())
        return {"handler": "reached"}

    app.add_api_route(GATED_PATH, endpoint, methods=["POST"])
    app.add_api_route(UNGATED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


@pytest.fixture
async def client(stub_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        yield ac


async def test_accessor_returns_the_callers_key_inside_a_gated_request(
    client: AsyncClient, observed: list[str | None], key: str
) -> None:
    """The exact string the caller sent, not a copy the platform generated.

    This is the property the whole derivation chain rests on: a retry carrying the
    same header must produce the same root, so every key derived from it downstream
    comes out identical and the far side recognises the repeat.
    """
    response = await client.post(GATED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert observed == [key]


async def test_accessor_is_none_on_an_ungated_route(
    client: AsyncClient, observed: list[str | None], key: str
) -> None:
    """An unlisted route registers nothing, so there is no key to hand out.

    Sent *with* a header, which is the case that would go wrong quietly: returning
    an unregistered key would let a caller believe an operation was replay-protected
    when the middleware never looked at it.
    """
    response = await client.post(UNGATED_PATH, headers={"X-Idempotency-Key": key})

    assert response.status_code == 200
    assert observed == [None]


async def test_accessor_is_none_outside_any_request() -> None:
    """Workers, schedulers and scripts have no caller and therefore no key."""
    assert current_idempotency_key() is None


async def test_a_rejected_key_is_never_published(
    client: AsyncClient, observed: list[str | None]
) -> None:
    """Only a validated, registered key becomes context.

    A malformed key is refused before the handler runs, so nothing downstream can
    derive from a string the platform declined to accept.
    """
    response = await client.post(GATED_PATH, headers={"X-Idempotency-Key": "nope"})

    assert response.status_code == 400
    assert observed == []


async def test_the_key_does_not_survive_into_the_next_request(
    client: AsyncClient, observed: list[str | None], key: str
) -> None:
    """Context is per-request, so an ungated request after a gated one sees nothing.

    Leakage here would be the worst possible failure: a later operation would derive
    its downstream keys from an unrelated caller's key and be deduped against work it
    has nothing to do with.
    """
    await client.post(GATED_PATH, headers={"X-Idempotency-Key": key})
    await client.post(UNGATED_PATH)

    assert observed == [key, None]


async def test_concurrent_requests_each_see_their_own_key(
    client: AsyncClient, observed: list[str | None]
) -> None:
    """Contextvars are per-task, so parallel gated requests cannot cross over."""
    import asyncio

    keys = [str(uuid4()) for _ in range(5)]
    await asyncio.gather(
        *(client.post(GATED_PATH, headers={"X-Idempotency-Key": k}) for k in keys)
    )

    assert sorted(x for x in observed if x is not None) == sorted(keys)
