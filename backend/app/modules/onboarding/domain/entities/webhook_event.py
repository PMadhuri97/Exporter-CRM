from sqlalchemy import Boolean, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class WebhookEvent(AnerModel):
    """
    Persisted record of an inbound provider webhook.

    Serves two purposes:
      1. Durable audit of every (signature-verified) webhook received.
      2. Idempotency — `dedup_key` (a SHA-256 of the raw request body) carries a
         UNIQUE constraint, so a redelivered identical webhook is rejected at
         insert time and processed exactly once.
    """

    __tablename__ = "onboarding_webhook_events"
    __table_args__ = (
        Index("ix_onboarding_webhook_events_dedup_key", "dedup_key", unique=True),
        {"schema": SCHEMA},
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applicant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # SHA-256 hex of the raw request body — the idempotency key.
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
