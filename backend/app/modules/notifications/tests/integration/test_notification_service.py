import hashlib
import hmac
import uuid

import pytest

from app.modules.notifications.application.services import NotificationService
from app.modules.notifications.domain.entities.notifications import (
    NotificationChannel,
    WebhookStatus,
)
from app.modules.notifications.domain.ports import (
    DeliveryResult,
    NotificationProvider,
)
from app.modules.notifications.infrastructure import providers
from app.modules.notifications.infrastructure.providers import (
    MockEmailProvider,
    MockWebhookProvider,
)
from app.platform.configuration.config import get_settings
from app.platform.database import services as database
from app.platform.security import sign_payload

INVOICE_REF = "INV-NOTIF-001"


def _pg_connect():
    import psycopg2

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _create_customer_sync(name: str) -> str:
    cid = str(uuid.uuid4())
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customers.customers
            (customer_id, entity_name, entity_type, kyb_status, risk_rating, created_at, updated_at)
        VALUES (%s, %s, 'BUYER', 'VERIFIED', 'LOW', NOW(), NOW())
        """,
        (cid, name),
    )
    conn.commit()
    cur.close()
    conn.close()
    return cid


def _create_transaction_sync(sender_id: str, beneficiary_id: str) -> str:
    tid = str(uuid.uuid4())
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO payments.transactions
            (transaction_id, idempotency_key, correlation_id,
             sender_customer_id, beneficiary_customer_id,
             amount, source_currency, destination_currency,
             invoice_reference, status, settlement_route, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s,
                1000000, 'USD', 'INR',
                %s, 'FAILED', 'DIGITAL_ASSET_BRIDGE', NOW(), NOW())
        """,
        (tid, str(uuid.uuid4()), str(uuid.uuid4()), sender_id, beneficiary_id, INVOICE_REF),
    )
    conn.commit()
    cur.close()
    conn.close()
    return tid


def _clear_deliverable_notifications() -> None:
    """Drain any PENDING/FAILED (still-deliverable) events left by prior runs so the
    queue holds only this test's events — otherwise process_pending may deliver an
    unrelated leftover instead of the event under test. DELIVERED/EXHAUSTED are
    terminal and left in place."""
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM notifications.notification_events WHERE status IN ('PENDING', 'FAILED')")
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture(scope="module")
def notification_tx_id() -> str:
    sender_id = _create_customer_sync("Notification Sender")
    beneficiary_id = _create_customer_sync("Notification Beneficiary")
    return _create_transaction_sync(sender_id, beneficiary_id)


# ── Provider-level unit tests (no DB) ────────────────────────────────────────

def test_sign_payload_matches_hmac_sha256_contract():
    secret = get_settings().NOTIFICATION_WEBHOOK_SECRET
    raw = b'{"event_type":"payment.failed"}'
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert sign_payload(raw, secret) == f"hmac-sha256={expected}"


@pytest.mark.asyncio
async def test_mock_webhook_provider_signs_and_sets_event_id_header():
    provider = MockWebhookProvider()
    event_id = uuid.uuid4()
    result = await provider.send(
        event_id=event_id,
        destination="https://customer.example/webhooks/aner",
        event_type="payment.failed",
        body={"transaction_id": "abc", "message": "hi"},
    )
    assert result.success is True
    assert result.signature.startswith("hmac-sha256=")
    assert result.headers["X-Aner-Signature"] == result.signature
    assert result.headers["X-Aner-Event-Id"] == str(event_id)


@pytest.mark.asyncio
async def test_mock_webhook_provider_fails_without_destination():
    result = await MockWebhookProvider().send(
        event_id=uuid.uuid4(), destination="", event_type="payment.failed", body={}
    )
    assert result.success is False
    assert "webhook_url" in (result.detail or "")


@pytest.mark.asyncio
async def test_mock_email_provider_renders_subject():
    result = await MockEmailProvider().send(
        event_id=uuid.uuid4(),
        destination="ops@customer.example",
        event_type="payment.settled",
        body={"transaction_id": "abc", "message": "done"},
    )
    assert result.success is True
    assert "payment.settled" in result.headers["Subject"]


# ── Service-level tests (real DB) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_notification_delivers(notification_tx_id: str):
    _clear_deliverable_notifications()
    async with database.AsyncSessionLocal() as db:
        service = NotificationService(db)
        event = await service.queue_notification(
            transaction_id=uuid.UUID(notification_tx_id),
            event_type="payment.failed",
            channel=NotificationChannel.WEBHOOK,
            webhook_url="https://example.com/webhooks/aner",
        )

        processed = await service.process_pending(limit=1)

        assert len(processed) == 1
        await db.refresh(event)
        assert event.status == WebhookStatus.DELIVERED
        assert event.attempt_count == 1
        assert event.delivered_at is not None


@pytest.mark.asyncio
async def test_email_notification_delivers(notification_tx_id: str):
    _clear_deliverable_notifications()
    async with database.AsyncSessionLocal() as db:
        service = NotificationService(db)
        event = await service.queue_notification(
            transaction_id=uuid.UUID(notification_tx_id),
            event_type="payment.settled",
            channel=NotificationChannel.EMAIL,
            recipient="ops@customer.example",
        )

        processed = await service.process_pending(limit=1)

        assert len(processed) == 1
        await db.refresh(event)
        assert event.channel == NotificationChannel.EMAIL
        assert event.status == WebhookStatus.DELIVERED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type, expected_status, expected_phrase",
    [
        ("payment.settled", "SETTLED", "settled successfully"),
        ("payment.failed", "FAILED", "Funds secured"),
        ("payment.recalled", "RECALLED_VIA_COMPENSATION", "recalled via compensation"),
    ],
)
async def test_per_event_message_and_status(
    notification_tx_id: str, event_type, expected_status, expected_phrase
):
    async with database.AsyncSessionLocal() as db:
        service = NotificationService(db)
        event = await service.queue_notification(
            transaction_id=uuid.UUID(notification_tx_id),
            event_type=event_type,
            webhook_url="https://example.com/webhooks/aner",
        )
        body = await service._build_body(event)

    assert body["event_type"] == event_type
    assert body["status"] == expected_status
    assert expected_phrase in body["message"]
    assert INVOICE_REF in body["message"]          # reference resolved from the transaction
    assert body["correlation_id"] is not None       # resolved from the transaction


class _FailingProvider(NotificationProvider):
    channel = NotificationChannel.WEBHOOK

    async def send(self, **_kwargs) -> DeliveryResult:
        return DeliveryResult(success=False, detail="simulated endpoint down")


@pytest.mark.asyncio
async def test_failed_delivery_retries_then_exhausts(notification_tx_id, monkeypatch):
    _clear_deliverable_notifications()
    monkeypatch.setitem(providers._PROVIDERS, NotificationChannel.WEBHOOK, _FailingProvider())
    max_attempts = get_settings().NOTIFICATION_MAX_ATTEMPTS

    async with database.AsyncSessionLocal() as db:
        service = NotificationService(db)
        event = await service.queue_notification(
            transaction_id=uuid.UUID(notification_tx_id),
            event_type="payment.failed",
            webhook_url="https://example.com/webhooks/aner",
        )

        # Each drain re-picks the retryable FAILED event (it is the only deliverable one).
        for attempt in range(1, max_attempts + 1):
            await service.process_pending(limit=1)
            await db.refresh(event)
            assert event.attempt_count == attempt
            if attempt < max_attempts:
                assert event.status == WebhookStatus.FAILED
            else:
                assert event.status == WebhookStatus.EXHAUSTED

        # Exhausted events are terminal — no longer re-delivered.
        await service.process_pending(limit=1)
        await db.refresh(event)
        assert event.attempt_count == max_attempts
        assert event.failure_reason == "simulated endpoint down"
