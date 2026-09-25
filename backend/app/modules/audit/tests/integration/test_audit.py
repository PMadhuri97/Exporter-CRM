"""
Immutable audit-logging tests.

Covers the audit trail end to end:

  • Write path — AuditService.record() is the single shared write path used by every
    module; here we seed events directly through it (as the real services do).
  • Immutability — the audit_events table is write-once: the DB trigger rejects
    UPDATE and DELETE even for the application role.
  • Correlation IDs — captured as a first-class column, both explicitly and
    auto-resolved from the request's X-Correlation-Id (structlog contextvars), and
    exercised end-to-end via a real FX-quote API call.
  • Query API — per-transaction trail, per-correlation trace, the privileged global
    feed (COMPLIANCE/ADMIN only) with event_type / actor_type filters, single-event
    fetch, pagination, auth and not-found behaviour.
  • The documented GET /api/v1/payments/{transaction_id}/audit alias.

Transaction + customer rows are created via psycopg2 (mirrors the settlement /
reconciliation suites); audit events are written through AuditService against a real
async session.
"""
import uuid

import psycopg2
import pytest
import structlog.contextvars
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import user_with_role

AUDIT_BASE = "/api/v1/audit"
PAYMENTS_BASE = "/api/v1/payments"
FX_BASE = "/api/v1/fx"


# ── psycopg2 sync helpers ─────────────────────────────────────────────────────

def _pg_connect():
    from app.platform.configuration.config import get_settings

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _create_customer_sync(entity_name: str) -> str:
    cid = str(uuid.uuid4())
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customers.customers
            (customer_id, entity_name, entity_type, kyb_status, risk_rating,
             created_at, updated_at)
        VALUES (%s, %s, 'BUYER', 'VERIFIED', 'LOW', NOW(), NOW())
        """,
        (cid, entity_name),
    )
    conn.commit()
    cur.close()
    conn.close()
    return cid


def _create_transaction_sync(sender_id: str, beneficiary_id: str, status: str = "INITIATED") -> str:
    tid = str(uuid.uuid4())
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO payments.transactions
            (transaction_id, idempotency_key, correlation_id,
             sender_customer_id, beneficiary_customer_id,
             amount, source_currency, destination_currency,
             status, settlement_route, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s,
                1000000, 'USD', 'INR',
                %s, 'DIGITAL_ASSET_BRIDGE', NOW(), NOW())
        """,
        (tid, str(uuid.uuid4()), str(uuid.uuid4()), sender_id, beneficiary_id, status),
    )
    conn.commit()
    cur.close()
    conn.close()
    return tid


async def _record_event(
    event_type: str,
    *,
    transaction_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
    actor_type: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Write one audit event through the real shared write path, in its own
    committed transaction so created_at is strictly monotonic across events."""
    import app.platform.database.services as database
    from app.modules.audit.application.services import AuditService
    from app.modules.audit.domain.entities.audit import ActorType

    async with database.AsyncSessionLocal() as db:
        await AuditService(db).record(
            event_type,
            transaction_id=transaction_id,
            actor_id=actor_id,
            actor_type=ActorType[actor_type],
            correlation_id=correlation_id,
        )
        await db.commit()


# ── auth helper ───────────────────────────────────────────────────────────────

async def _register_login(client: AsyncClient, role: str) -> str:
    _, token = await user_with_role(client, UserRole(role), email_prefix=f"{role.lower()}-audit")
    return token


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
async def compliance_token(client: AsyncClient) -> str:
    return await _register_login(client, "COMPLIANCE")


@pytest.fixture(scope="module")
def customer_ids() -> tuple[str, str]:
    return (
        _create_customer_sync("Audit Gemstone Imports LLC"),
        _create_customer_sync("Audit Surat Diamond Works Pvt Ltd"),
    )


# The three seeded event types, in the chronological order they are written.
_SEEDED_EVENTS = [
    ("transaction.initiated", "API_CLIENT"),
    ("compliance.checker_approved", "COMPLIANCE_OFFICER"),
    ("settlement.completed", "SYSTEM"),
]


@pytest.fixture(scope="module")
async def seeded(customer_ids: tuple[str, str]) -> tuple[str, str]:
    """A transaction with three audit events all sharing one correlation ID.
    Returns (transaction_id, correlation_id)."""
    sender_id, beneficiary_id = customer_ids
    tx_id = _create_transaction_sync(sender_id, beneficiary_id)
    correlation_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    for event_type, actor_type in _SEEDED_EVENTS:
        await _record_event(
            event_type,
            transaction_id=uuid.UUID(tx_id),
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id if actor_type != "SYSTEM" else None,
        )
    return tx_id, str(correlation_id)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── per-transaction trail ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_transaction_audit_trail(client: AsyncClient, compliance_token: str, seeded):
    tx_id, correlation_id = seeded
    resp = await client.get(f"{AUDIT_BASE}/transactions/{tx_id}", headers=_auth(compliance_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["events"]) == 3
    # Chronological order (oldest → newest).
    assert [e["event_type"] for e in body["events"]] == [t for t, _ in _SEEDED_EVENTS]
    # Every event carries the transaction and the shared correlation ID.
    assert all(e["transaction_id"] == tx_id for e in body["events"])
    assert all(e["correlation_id"] == correlation_id for e in body["events"])


@pytest.mark.asyncio
async def test_actor_types_recorded(client: AsyncClient, compliance_token: str, seeded):
    tx_id, _ = seeded
    resp = await client.get(f"{AUDIT_BASE}/transactions/{tx_id}", headers=_auth(compliance_token))
    actor_types = {e["actor_type"] for e in resp.json()["events"]}
    assert actor_types == {"API_CLIENT", "COMPLIANCE_OFFICER", "SYSTEM"}


@pytest.mark.asyncio
async def test_payments_audit_alias(client: AsyncClient, compliance_token: str, seeded):
    """The documented GET /payments/{id}/audit returns the same trail."""
    tx_id, _ = seeded
    resp = await client.get(f"{PAYMENTS_BASE}/{tx_id}/audit", headers=_auth(compliance_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert [e["event_type"] for e in body["events"]] == [t for t, _ in _SEEDED_EVENTS]


@pytest.mark.asyncio
async def test_transaction_trail_missing_auth(client: AsyncClient, seeded):
    tx_id, _ = seeded
    resp = await client.get(f"{AUDIT_BASE}/transactions/{tx_id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_transaction_trail_not_found(client: AsyncClient, compliance_token: str):
    resp = await client.get(
        f"{AUDIT_BASE}/transactions/{uuid.uuid4()}", headers=_auth(compliance_token)
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_transaction_trail_pagination(client: AsyncClient, compliance_token: str, seeded):
    tx_id, _ = seeded
    resp = await client.get(
        f"{AUDIT_BASE}/transactions/{tx_id}?limit=1&offset=0", headers=_auth(compliance_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1          # one item on the page
    assert body["total"] == 3                # ...but three in total
    assert body["limit"] == 1 and body["offset"] == 0
    assert body["events"][0]["event_type"] == "transaction.initiated"


# ── correlation trace ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correlation_trace(client: AsyncClient, compliance_token: str, seeded):
    tx_id, correlation_id = seeded
    resp = await client.get(
        f"{AUDIT_BASE}/correlations/{correlation_id}", headers=_auth(compliance_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert all(e["correlation_id"] == correlation_id for e in body["events"])


@pytest.mark.asyncio
async def test_correlation_captured_from_request_header(client: AsyncClient, compliance_token: str):
    """End-to-end: a real FX-quote request carries X-Correlation-Id → the
    fx.quote.created audit event is written with that correlation ID (proving the
    middleware → contextvars → AuditService chain), and is retrievable by it."""
    correlation_id = str(uuid.uuid4())
    quote = await client.post(
        f"{FX_BASE}/quotes",
        json={"from_currency": "USD", "to_currency": "INR", "amount": "10000.00"},
        headers={**_auth(compliance_token), "X-Correlation-Id": correlation_id},
    )
    assert quote.status_code == 200, quote.text
    assert quote.headers["X-Correlation-Id"] == correlation_id

    resp = await client.get(
        f"{AUDIT_BASE}/correlations/{correlation_id}", headers=_auth(compliance_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    types = {e["event_type"] for e in body["events"]}
    assert "fx.quote.created" in types
    assert all(e["correlation_id"] == correlation_id for e in body["events"])


# ── single event ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_single_event(client: AsyncClient, compliance_token: str, seeded):
    tx_id, correlation_id = seeded
    trail = await client.get(f"{AUDIT_BASE}/transactions/{tx_id}", headers=_auth(compliance_token))
    first = trail.json()["events"][0]

    resp = await client.get(f"{AUDIT_BASE}/events/{first['event_id']}", headers=_auth(compliance_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_id"] == first["event_id"]
    assert body["event_type"] == "transaction.initiated"
    assert body["correlation_id"] == correlation_id


@pytest.mark.asyncio
async def test_get_single_event_not_found(client: AsyncClient, compliance_token: str):
    resp = await client.get(f"{AUDIT_BASE}/events/{uuid.uuid4()}", headers=_auth(compliance_token))
    assert resp.status_code == 404


# ── global feed (privileged) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feed_requires_privileged_role(client: AsyncClient, seeded):
    """The negative case, so it mints its own unprivileged token.

    Every other test in this file now uses `compliance_token` because the read
    routes are COMPLIANCE/ADMIN-only (L1-07). This one is asserting the
    refusal, so it needs the opposite — an API_USER token, created here rather
    than as a shared fixture so nothing can accidentally reuse it for a
    positive assertion again.
    """
    tx_id, _ = seeded
    api_token = await _register_login(client, "API_USER")
    resp = await client.get(
        f"{AUDIT_BASE}/events?transaction_id={tx_id}", headers=_auth(api_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_feed_missing_auth(client: AsyncClient):
    resp = await client.get(f"{AUDIT_BASE}/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_feed_filter_by_event_type(client: AsyncClient, compliance_token: str, seeded):
    tx_id, _ = seeded
    resp = await client.get(
        f"{AUDIT_BASE}/events?transaction_id={tx_id}&event_type=settlement.completed",
        headers=_auth(compliance_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["event_type"] == "settlement.completed"


@pytest.mark.asyncio
async def test_feed_filter_by_actor_type(client: AsyncClient, compliance_token: str, seeded):
    tx_id, _ = seeded
    resp = await client.get(
        f"{AUDIT_BASE}/events?transaction_id={tx_id}&actor_type=COMPLIANCE_OFFICER",
        headers=_auth(compliance_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["actor_type"] == "COMPLIANCE_OFFICER"


@pytest.mark.asyncio
async def test_feed_default_order_recent_first(client: AsyncClient, compliance_token: str, seeded):
    tx_id, _ = seeded
    resp = await client.get(
        f"{AUDIT_BASE}/events?transaction_id={tx_id}", headers=_auth(compliance_token)
    )
    assert resp.status_code == 200
    # Global feed is most-recent-first — reverse of the chronological trail.
    types = [e["event_type"] for e in resp.json()["events"]]
    assert types == [t for t, _ in reversed(_SEEDED_EVENTS)]


# ── immutability (write-once enforced at the DB) ──────────────────────────────

@pytest.mark.asyncio
async def test_update_blocked_by_trigger(client: AsyncClient, seeded):
    tx_id, _ = seeded
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM audit.audit_events WHERE transaction_id = %s LIMIT 1", (tx_id,))
    event_id = cur.fetchone()[0]
    with pytest.raises(psycopg2.Error):
        cur.execute(
            "UPDATE audit.audit_events SET event_type = 'tampered' WHERE id = %s", (str(event_id),)
        )
        conn.commit()
    conn.rollback()
    cur.close()
    conn.close()


@pytest.mark.asyncio
async def test_delete_blocked_by_trigger(client: AsyncClient, seeded):
    tx_id, _ = seeded
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM audit.audit_events WHERE transaction_id = %s LIMIT 1", (tx_id,))
    event_id = cur.fetchone()[0]
    with pytest.raises(psycopg2.Error):
        cur.execute("DELETE FROM audit.audit_events WHERE id = %s", (str(event_id),))
        conn.commit()
    conn.rollback()
    cur.close()
    conn.close()


# ── correlation-ID resolution (service level) ─────────────────────────────────

@pytest.mark.asyncio
async def test_explicit_correlation_overrides_contextvars(customer_ids: tuple[str, str]):
    """An explicit correlation_id wins over the bound contextvar."""
    import app.platform.database.services as database
    from app.modules.audit.application.services import AuditService
    from app.modules.audit.domain.entities.audit import ActorType

    sender_id, beneficiary_id = customer_ids
    tx_id = uuid.UUID(_create_transaction_sync(sender_id, beneficiary_id))
    explicit = uuid.uuid4()
    context_value = uuid.uuid4()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=str(context_value))
    try:
        async with database.AsyncSessionLocal() as db:
            event = await AuditService(db).record(
                "test.explicit_correlation",
                transaction_id=tx_id,
                actor_type=ActorType.SYSTEM,
                correlation_id=explicit,
            )
            await db.commit()
            assert event.correlation_id == explicit
    finally:
        structlog.contextvars.clear_contextvars()


@pytest.mark.asyncio
async def test_correlation_auto_resolved_from_contextvars(customer_ids: tuple[str, str]):
    """With no explicit value, record() picks up the bound correlation_id."""
    import app.platform.database.services as database
    from app.modules.audit.application.services import AuditService
    from app.modules.audit.domain.entities.audit import ActorType

    sender_id, beneficiary_id = customer_ids
    tx_id = uuid.UUID(_create_transaction_sync(sender_id, beneficiary_id))
    context_value = uuid.uuid4()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=str(context_value))
    try:
        async with database.AsyncSessionLocal() as db:
            event = await AuditService(db).record(
                "test.auto_correlation",
                transaction_id=tx_id,
                actor_type=ActorType.SYSTEM,
            )
            await db.commit()
            assert event.correlation_id == context_value
    finally:
        structlog.contextvars.clear_contextvars()
