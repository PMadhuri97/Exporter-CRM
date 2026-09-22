"""
Persistence for the Kafka consumer tier.

  • EventLog       — durable, append-only materialisation of every consumed event.
                     This is the Audit Service's write-once store (aner.audit.events,
                     7-year retention at the cluster level).
  • ProcessedEvent — per-consumer-group idempotency ledger. Kafka delivers
                     at-least-once; every consumer records (consumer_group, event_id)
                     here and refuses to act twice on the same delivery.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel, Base

SCHEMA = "messaging"


class EventLog(AppendOnlyModel):
    """Write-once record of a consumed event. Append-only — never updated or deleted."""

    __tablename__ = "event_log"
    __table_args__ = (
        # Declared here because the database has it: b7e4a1c92f10 created it and
        # the model never did, so autogenerate proposed dropping a live index.
        Index("ix_event_log_transaction_id", "transaction_id"),
        {"schema": SCHEMA},
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    producer: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ProcessedEvent(Base):
    """
    Consumer idempotency ledger. Composite PK (consumer_group, event_id) lets each
    consumer group process an event exactly once while other groups still see it.
    """

    __tablename__ = "processed_events"
    __table_args__ = (
        PrimaryKeyConstraint("consumer_group", "event_id"),
        {"schema": SCHEMA},
    )

    consumer_group: Mapped[str] = mapped_column(String(100), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
