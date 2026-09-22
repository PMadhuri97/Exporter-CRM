"""
Notification delivery providers — implementations of the module's
NotificationProvider port (app.modules.notifications.domain.ports).

Thin slice: MOCK providers only. They simulate delivery in-process — no real HTTP
POST, no SMTP — but the webhook provider still computes the true HMAC-SHA256
X-Aner-Signature and X-Aner-Event-Id headers per the outbound webhook contract, so
the wire format a live provider would send is exercised and asserted in tests.

The HMAC itself comes from platform/security (ARCHITECTURE.md §8: never roll
bespoke crypto). These are mocks, not vendor clients, so they are module
infrastructure rather than integrations (§3).
"""
from __future__ import annotations

import json
import uuid

import structlog

from app.modules.notifications.domain.entities.notifications import NotificationChannel
from app.modules.notifications.domain.ports import DeliveryResult, NotificationProvider
from app.platform.configuration.config import get_settings
from app.platform.security import sign_payload

logger = structlog.get_logger(__name__)


class MockWebhookProvider(NotificationProvider):
    """Simulates an outbound webhook POST to the customer's configured URL.

    Computes the real signature/headers per architecture-api-design.md but does not
    transmit (mock). A missing destination URL is treated as a delivery failure so
    the retry/EXHAUSTED path can be exercised.
    """

    channel = NotificationChannel.WEBHOOK

    async def send(
        self,
        *,
        event_id: uuid.UUID,
        destination: str,
        event_type: str,
        body: dict,
    ) -> DeliveryResult:
        if not destination:
            return DeliveryResult(success=False, detail="missing webhook_url")

        raw_body = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = sign_payload(raw_body, get_settings().NOTIFICATION_WEBHOOK_SECRET)
        headers = {
            "Content-Type": "application/json",
            "X-Aner-Signature": signature,
            "X-Aner-Event-Id": str(event_id),
        }
        logger.info(
            "webhook_delivered_mock",
            event_id=str(event_id),
            destination=destination,
            event_type=event_type,
            signature=signature,
        )
        return DeliveryResult(success=True, signature=signature, headers=headers)


class MockEmailProvider(NotificationProvider):
    """Simulates an email send to the beneficiary/sender contact address.

    Renders a subject + body and 'sends' in-process (no SMTP). A missing recipient
    is a delivery failure.
    """

    channel = NotificationChannel.EMAIL

    async def send(
        self,
        *,
        event_id: uuid.UUID,
        destination: str,
        event_type: str,
        body: dict,
    ) -> DeliveryResult:
        if not destination:
            return DeliveryResult(success=False, detail="missing recipient")

        subject = f"[Aner] {event_type} — {body.get('transaction_id', '')}"
        rendered = f"Subject: {subject}\n\n{body.get('message', '')}"  # noqa: F841
        logger.info(
            "email_delivered_mock",
            event_id=str(event_id),
            **{"to": destination},
            event_type=event_type,
            subject=subject,
            from_=get_settings().NOTIFICATION_EMAIL_FROM,
        )
        return DeliveryResult(
            success=True,
            detail="mock-email-sent",
            headers={"Subject": subject, "From": get_settings().NOTIFICATION_EMAIL_FROM},
        )


# Channel → provider registry. Tests may monkeypatch this mapping (e.g. to inject a
# provider that fails) to exercise the FAILED / EXHAUSTED delivery path.
_PROVIDERS: dict[NotificationChannel, NotificationProvider] = {
    NotificationChannel.WEBHOOK: MockWebhookProvider(),
    NotificationChannel.EMAIL: MockEmailProvider(),
}


def resolve_provider(channel: NotificationChannel) -> NotificationProvider:
    provider = _PROVIDERS.get(channel)
    if provider is None:
        raise ValueError(f"no provider registered for channel {channel}")
    return provider
