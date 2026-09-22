"""Header extraction and key-format validation.

These answer one question for a request the gate has already accepted: does it
carry a usable idempotency key? A request that does not is rejected with a 400
**before the handler runs**; a request that does is passed straight through,
because registration is a later slice and nothing is recorded yet.

Two behaviours are load-bearing and are asserted throughout rather than once:

* **the handler is never invoked on invalid input** — the whole point of doing
  this in middleware is that a bad key costs nothing downstream, and
* **`correlation_id` survives into the error body** — the response is built here
  rather than by ``aner_exception_handler``, so it has to reproduce the platform
  shape itself instead of inheriting it.

Key *grammar* belongs to the idempotency package's validator and is tested
exhaustively in ``app/platform/idempotency/tests/test_validation.py``. What is
tested here is the mapping from that verdict onto an HTTP response — one
representative case per branch, not a second copy of the UUID rules.
"""

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.platform.idempotency import ValidationReason
from app.platform.middleware.services import (
    ERROR_INVALID_KEY,
    ERROR_MISSING_KEY,
    IDEMPOTENCY_HEADER,
    IdempotencyMiddleware,
)

ENABLED_PATH = "/api/v1/settlement/execute"

#: Canonical UUID v4, used only where the key is never accepted (so it is
#: never registered). Anything that must reach the handler uses ``fresh_key``:
#: registration persists, so a reused key is a duplicate on its second use.
VALID_KEY = "c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c"

#: A real UUID, but version 1 — the timestamp/MAC kind. Structurally a UUID and
#: the right length, so it is only rejected by the version check itself.
UUID_V1 = "a8098c1a-f86e-11da-bd1a-00112444be1e"

#: 65 characters: one past MAX_CUSTOMER_KEY_LENGTH.
OVERLONG_KEY = "a" * 65

CORRELATION_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def handled() -> list[str]:
    """Records every handler invocation. Must stay empty on rejected requests."""
    return []


@pytest.fixture
def fresh_key() -> str:
    """A key no earlier test has registered.

    Registration is persistent, so a shared constant is accepted exactly once —
    every later use, in this run or the next, is a duplicate and returns 409.
    """
    return str(uuid4())


@pytest.fixture
def stub_app(handled: list[str]) -> FastAPI:
    """Minimal app carrying only the enabled route.

    ``CorrelationIdMiddleware`` is added *outside* ``IdempotencyMiddleware``,
    mirroring ``create_app()``, because the error body reads the correlation ID
    out of the contextvars that middleware binds. Wiring them the other way round
    here would test a stack the application does not have.
    """
    from app.platform.middleware.services import CorrelationIdMiddleware

    app = FastAPI()

    async def endpoint(request: Request) -> dict[str, str]:
        handled.append(f"{request.method} {request.url.path}")
        return {"handler": "reached"}

    app.add_api_route(ENABLED_PATH, endpoint, methods=["POST"])
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app


@pytest.fixture
async def client(stub_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        yield ac


async def _post(client: AsyncClient, key: str | None = None, **kwargs):
    headers = {"X-Correlation-Id": CORRELATION_ID}
    if key is not None:
        headers[IDEMPOTENCY_HEADER] = key
    headers.update(kwargs.pop("headers", {}))
    return await client.post(ENABLED_PATH, headers=headers, **kwargs)


# ── Rejected: no usable key supplied ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "description"),
    [
        pytest.param(None, "header absent entirely", id="missing"),
        pytest.param("", "header present but empty", id="empty"),
        pytest.param("   ", "header present but whitespace only", id="whitespace"),
        pytest.param("\t\n", "header present but tab/newline only", id="whitespace-tab-newline"),
    ],
)
async def test_no_usable_key_is_rejected(
    client: AsyncClient, handled: list[str], key: str | None, description: str
) -> None:
    """Absent, empty and blank are one condition and take one error code."""
    response = await _post(client, key)

    assert response.status_code == 400, description
    body = response.json()
    assert body["error_code"] == ERROR_MISSING_KEY
    assert body["error_context"]["reason"] == ValidationReason.EMPTY_KEY.value
    assert IDEMPOTENCY_HEADER in body["detail"]
    assert handled == [], f"handler ran despite: {description}"


# ── Rejected: a key was supplied but is not usable ───────────────────────────


@pytest.mark.parametrize(
    ("key", "expected_reason"),
    [
        pytest.param("not-a-uuid", ValidationReason.INVALID_UUID_V4.value, id="malformed"),
        pytest.param(UUID_V1, ValidationReason.INVALID_UUID_V4.value, id="uuid-v1"),
        pytest.param(
            "c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0",
            ValidationReason.INVALID_UUID_V4.value,
            id="truncated",
        ),
        pytest.param(
            "c8f3b2a14e2d4f1a8c3b5d6e7f8a9b0c",
            ValidationReason.INVALID_UUID_V4.value,
            id="no-hyphens",
        ),
        pytest.param(OVERLONG_KEY, ValidationReason.EXCEEDS_MAX_LENGTH.value, id="over-length"),
    ],
)
async def test_malformed_key_is_rejected(
    client: AsyncClient, handled: list[str], key: str, expected_reason: str
) -> None:
    """A supplied-but-invalid key is a different client bug from a missing one."""
    response = await _post(client, key)

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == ERROR_INVALID_KEY
    assert body["error_context"]["reason"] == expected_reason
    assert handled == [], "handler ran on an invalid key"


async def test_uuid_v1_is_rejected_specifically_on_version(client: AsyncClient) -> None:
    """Pins that the version check is real, not incidental length/shape matching.

    A v1 UUID is 36 characters, correctly hyphenated and parses as a UUID. If it
    were accepted, the key space would silently include timestamp-derived
    identifiers that are predictable and, in the same millisecond on the same
    host, colliding.
    """
    import uuid as uuid_module

    assert uuid_module.UUID(UUID_V1).version == 1, "fixture is not actually a v1 UUID"
    assert len(UUID_V1) == len(VALID_KEY)

    response = await _post(client, UUID_V1)

    assert response.status_code == 400
    assert response.json()["error_code"] == ERROR_INVALID_KEY


# ── Accepted ─────────────────────────────────────────────────────────────────


async def test_valid_key_reaches_the_handler(
    client: AsyncClient, handled: list[str], fresh_key: str
) -> None:
    response = await _post(client, fresh_key)

    assert response.status_code == 200
    assert response.json() == {"handler": "reached"}
    assert handled == [f"POST {ENABLED_PATH}"]


@pytest.mark.parametrize(
    "wrapper",
    [
        pytest.param("  {key}  ", id="spaces-both-sides"),
        pytest.param("{key}\n", id="trailing-newline"),
        pytest.param("\t{key}", id="leading-tab"),
    ],
)
async def test_surrounding_whitespace_is_stripped_then_accepted(
    client: AsyncClient, handled: list[str], fresh_key: str, wrapper: str
) -> None:
    """A trailing newline from a shell client is not a malformed key.

    Without stripping, the anchored UUID pattern rejects these with
    INVALID_UUID_V4 — an error that sends the caller looking at their key
    generation rather than at their transport.
    """
    response = await _post(client, wrapper.format(key=fresh_key))

    assert response.status_code == 200
    assert handled == [f"POST {ENABLED_PATH}"]


@pytest.mark.parametrize(
    "header_name",
    [
        pytest.param("X-Idempotency-Key", id="canonical"),
        pytest.param("x-idempotency-key", id="lower"),
        pytest.param("X-IDEMPOTENCY-KEY", id="upper"),
        pytest.param("x-IdEmPoTeNcY-kEy", id="mixed"),
    ],
)
async def test_header_lookup_is_case_insensitive(
    client: AsyncClient, handled: list[str], fresh_key: str, header_name: str
) -> None:
    """HTTP header names are case-insensitive; Starlette's Headers honours that."""
    response = await client.post(ENABLED_PATH, headers={header_name: fresh_key})

    assert response.status_code == 200
    assert handled == [f"POST {ENABLED_PATH}"]


async def test_uppercase_uuid_is_accepted(
    client: AsyncClient, handled: list[str], fresh_key: str
) -> None:
    """The validator accepts any case in the hex digits; the middleware must
    not narrow it."""
    response = await _post(client, fresh_key.upper())

    assert response.status_code == 200
    assert handled == [f"POST {ENABLED_PATH}"]


# ── The error body ───────────────────────────────────────────────────────────


#: The platform error shape, as emitted by ``aner_exception_handler`` since AL-47.
#: ``error_context`` is the optional seventh key, present when there is context.
PLATFORM_ERROR_KEYS = {
    "error_code",
    "human_readable_message",
    "detail",
    "idempotency_key",
    "correlation_id",
    "timestamp",
    "error_context",
}


@pytest.mark.parametrize(
    ("key", "expected_code", "expected_echo"),
    [
        pytest.param(None, ERROR_MISSING_KEY, None, id="missing"),
        pytest.param("not-a-uuid", ERROR_INVALID_KEY, "not-a-uuid", id="invalid"),
    ],
)
async def test_error_body_matches_the_platform_shape(
    client: AsyncClient, key: str | None, expected_code: str, expected_echo: str | None
) -> None:
    """A middleware error must be indistinguishable in shape from a handler error.

    This response is built by the middleware, not by ``aner_exception_handler``,
    so nothing reproduces the platform shape for it automatically — every field
    has to be asserted or it will drift.
    """
    response = await _post(client, key)
    body = response.json()

    assert set(body) == PLATFORM_ERROR_KEYS
    assert body["error_code"] == expected_code
    assert body["correlation_id"] == CORRELATION_ID
    assert body["idempotency_key"] == expected_echo
    assert body["detail"] == body["human_readable_message"]
    assert isinstance(body["detail"], str) and body["detail"]
    assert set(body["error_context"]) == {"reason"}


async def test_error_timestamp_is_iso_utc(client: AsyncClient) -> None:
    """`timestamp` must parse, and be timezone-aware — a naive one is unusable."""
    from datetime import datetime

    body = (await _post(client, None)).json()
    parsed = datetime.fromisoformat(body["timestamp"])

    assert parsed.tzinfo is not None


async def test_error_shape_matches_a_real_handler_error(client: AsyncClient) -> None:
    """Pins the two shapes together so they cannot drift apart independently.

    Compares the middleware's body against one produced by
    ``aner_exception_handler`` for the same status class. If AL-47's shape changes
    again, this fails here rather than in a client.
    """
    from starlette.requests import Request

    from app.platform.middleware.handlers import aner_exception_handler
    from app.shared.exceptions import AnerBaseException

    scope = {"type": "http", "method": "POST", "path": ENABLED_PATH, "headers": [], "query_string": b""}
    handler_response = await aner_exception_handler(
        Request(scope), AnerBaseException(detail="x", error_code="X", extensions={"reason": "y"})
    )
    import json

    handler_keys = set(json.loads(bytes(handler_response.body)))
    middleware_keys = set((await _post(client, None)).json())

    assert middleware_keys == handler_keys


async def test_error_response_carries_the_correlation_id_header(
    client: AsyncClient,
) -> None:
    """CorrelationIdMiddleware sits outside, so it stamps short-circuits too."""
    response = await _post(client, None)

    assert response.status_code == 400
    assert response.headers["X-Correlation-Id"] == CORRELATION_ID


async def test_correlation_id_is_generated_when_client_sends_none(
    client: AsyncClient,
) -> None:
    """An error body must never carry a null correlation id."""
    response = await client.post(ENABLED_PATH)

    assert response.status_code == 400
    assert response.json()["correlation_id"]


# ── Scope: validation applies only where the gate applies ────────────────────


async def test_non_enabled_route_is_not_asked_for_a_key(
    stub_app: FastAPI, handled: list[str]
) -> None:
    """A route outside the allowlist must not acquire a header requirement.

    Guards the failure mode the allowlist exists to prevent: the header
    requirement turning into a platform-wide mandate the moment it ships.
    """

    async def other(request: Request) -> dict[str, str]:
        handled.append(f"{request.method} {request.url.path}")
        return {"handler": "reached"}

    stub_app.add_api_route("/api/v1/payments", other, methods=["POST"])

    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/payments")

    assert response.status_code == 200
    assert handled == ["POST /api/v1/payments"]


async def test_get_on_the_enabled_path_is_not_asked_for_a_key(
    stub_app: FastAPI, handled: list[str]
) -> None:
    """Validation keys off the gate's verdict, which is method-sensitive."""

    async def read(request: Request) -> dict[str, str]:
        handled.append(f"{request.method} {request.url.path}")
        return {"handler": "reached"}

    stub_app.add_api_route(ENABLED_PATH, read, methods=["GET"])

    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        response = await ac.get(ENABLED_PATH)

    assert response.status_code == 200
    assert handled == [f"GET {ENABLED_PATH}"]
