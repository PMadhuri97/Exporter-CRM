"""
Customer onboarding foundation tests.

Runs entirely against the in-process MockIdentityProvider (SUMSUB_ENABLED=false),
so no network or real credentials are needed. A fresh InMemoryEventBus is injected
as the process singleton for the module so `customer.*` event publication can be
asserted, then reset so other modules are unaffected (mirrors test_event_flow).
"""
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient, Response

from app.platform.configuration.config import get_settings
from app.platform.messaging.ports import InMemoryEventBus, set_event_bus
from app.platform.messaging.schemas import EventType

# ── sync DB helpers (per project test conventions) ────────────────────────────

def _pg_connect():
    import psycopg2

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _scalar(query: str, params: tuple):
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def _customer_status(customer_id: str) -> str:
    return _scalar(
        "SELECT status FROM onboarding.onboarding_customers WHERE id = %s", (customer_id,)
    )


def _verification_count(customer_id: str) -> int:
    return _scalar(
        "SELECT COUNT(*) FROM onboarding.onboarding_verifications WHERE customer_id = %s", (customer_id,)
    )


# ── auth + signing helpers ────────────────────────────────────────────────────

async def _api_token(client: AsyncClient) -> str:
    email = f"onboard-{uuid.uuid4().hex[:8]}@aner-test.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password1", "role": "API_USER"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password1"}
    )
    return login.json()["access_token"]


def _sign(raw: bytes) -> str:
    secret = get_settings().SUMSUB_WEBHOOK_SECRET
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _webhook_body(applicant_id: str, external_user_id: str, review_answer: str = "GREEN") -> bytes:
    payload = {
        "type": "applicantReviewed",
        "applicantId": applicant_id,
        "externalUserId": external_user_id,
        "reviewStatus": "completed",
        "reviewResult": {"reviewAnswer": review_answer},
    }
    return json.dumps(payload).encode("utf-8")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def event_bus() -> Iterator[InMemoryEventBus]:
    """A fresh in-memory bus installed as the singleton (no consumers wired)."""
    bus = InMemoryEventBus()
    set_event_bus(bus)
    yield bus
    set_event_bus(None)


async def _register(client: AsyncClient, token: str, email: str | None = None) -> Response:
    body = {
        "email": email or f"cust-{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "Meera Textiles Pvt Ltd",
        "company_name": "Meera Textiles",
        "country": "IN",
    }
    resp = await client.post(
        "/api/v1/onboarding/register",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp


# ── POST /onboarding/register ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/onboarding/register",
        json={"email": "x@example.com", "full_name": "X"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_creates_customer_applicant_and_event(
    client: AsyncClient, event_bus: InMemoryEventBus
):
    event_bus.clear()
    token = await _api_token(client)
    resp = await _register(client, token)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["provider"] == "mock"
    assert body["external_user_id"].startswith("aner-")
    assert body["applicant_id"] == f"mock-applicant-{body['external_user_id']}"

    # customer.registered event published on the bus
    registered = event_bus.events_of_type(EventType.CUSTOMER_REGISTERED)
    assert any(e.partition_key == body["customer_id"] for e in registered)


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client: AsyncClient, event_bus: InMemoryEventBus):
    token = await _api_token(client)
    email = f"dupe-{uuid.uuid4().hex[:8]}@example.com"
    first = await _register(client, token, email=email)
    assert first.status_code == 201
    second = await _register(client, token, email=email)
    assert second.status_code == 409
    assert second.json()["error_code"] == "CUSTOMER_ALREADY_EXISTS"


# ── GET /onboarding/{id}/sdk-token ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sdk_token_success(client: AsyncClient, event_bus: InMemoryEventBus):
    token = await _api_token(client)
    reg = await _register(client, token)
    customer_id = reg.json()["customer_id"]

    resp = await client.get(
        f"/api/v1/onboarding/{customer_id}/sdk-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"].startswith("mock-token-")
    assert body["user_id"] == reg.json()["external_user_id"]
    assert body["customer_id"] == customer_id


@pytest.mark.asyncio
async def test_sdk_token_not_found(client: AsyncClient, event_bus: InMemoryEventBus):
    token = await _api_token(client)
    resp = await client.get(
        f"/api/v1/onboarding/{uuid.uuid4()}/sdk-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── POST /onboarding/webhooks/sumsub ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(client: AsyncClient, event_bus: InMemoryEventBus):
    raw = _webhook_body("mock-applicant-x", "aner-x")
    resp = await client.post(
        "/api/v1/onboarding/webhooks/sumsub",
        content=raw,
        headers={"X-Payload-Digest": "deadbeef", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "INVALID_WEBHOOK_SIGNATURE"


@pytest.mark.asyncio
async def test_webhook_approves_customer_and_records_verification(
    client: AsyncClient, event_bus: InMemoryEventBus
):
    token = await _api_token(client)
    reg = await _register(client, token)
    customer_id = reg.json()["customer_id"]
    applicant_id = reg.json()["applicant_id"]
    external_user_id = reg.json()["external_user_id"]

    event_bus.clear()
    raw = _webhook_body(applicant_id, external_user_id, review_answer="GREEN")
    resp = await client.post(
        "/api/v1/onboarding/webhooks/sumsub",
        content=raw,
        headers={
            "X-Payload-Digest": _sign(raw),
            "X-Payload-Digest-Alg": "HMAC_SHA256_HEX",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    assert _customer_status(customer_id) == "APPROVED"
    assert _verification_count(customer_id) == 1

    updated = event_bus.events_of_type(EventType.CUSTOMER_VERIFICATION_UPDATED)
    assert any(e.partition_key == customer_id for e in updated)


@pytest.mark.asyncio
async def test_webhook_rejected_answer_sets_rejected(client: AsyncClient, event_bus: InMemoryEventBus):
    token = await _api_token(client)
    reg = await _register(client, token)
    customer_id = reg.json()["customer_id"]
    applicant_id = reg.json()["applicant_id"]
    external_user_id = reg.json()["external_user_id"]

    raw = _webhook_body(applicant_id, external_user_id, review_answer="RED")
    resp = await client.post(
        "/api/v1/onboarding/webhooks/sumsub",
        content=raw,
        headers={"X-Payload-Digest": _sign(raw), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert _customer_status(customer_id) == "REJECTED"


@pytest.mark.asyncio
async def test_webhook_is_idempotent(client: AsyncClient, event_bus: InMemoryEventBus):
    token = await _api_token(client)
    reg = await _register(client, token)
    customer_id = reg.json()["customer_id"]
    applicant_id = reg.json()["applicant_id"]
    external_user_id = reg.json()["external_user_id"]

    raw = _webhook_body(applicant_id, external_user_id, review_answer="GREEN")
    headers = {"X-Payload-Digest": _sign(raw), "Content-Type": "application/json"}

    first = await client.post("/api/v1/onboarding/webhooks/sumsub", content=raw, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    # Identical redelivery — deduplicated, no second verification row.
    second = await client.post("/api/v1/onboarding/webhooks/sumsub", content=raw, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"

    assert _verification_count(customer_id) == 1
