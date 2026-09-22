import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base, TimestampMixin

SCHEMA = "notifications"
PAYMENTS_SCHEMA = "payments"


class WebhookStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"


class NotificationChannel(str, enum.Enum):
    """Delivery channel — each channel is backed by a pluggable provider."""

    WEBHOOK = "WEBHOOK"
    EMAIL = "EMAIL"


class NotificationEvent(TimestampMixin, Base):
    """Tracks outbound notification delivery attempts across pluggable channels.

    Webhook deliveries carry an HMAC-SHA256 X-Aner-Signature; email deliveries go
    to ``recipient``. For webhooks the destination is ``webhook_url``; for email it
    is ``recipient`` — exactly one is populated per row depending on ``channel``.
    """

    __tablename__ = "notification_events"
    __table_args__ = ({"schema": SCHEMA},)

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel_enum", schema=SCHEMA),
        nullable=False,
        default=NotificationChannel.WEBHOOK,
    )
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        Enum(WebhookStatus, name="webhook_status_enum", schema=SCHEMA),
        nullable=False,
        default=WebhookStatus.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
