from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"


class NotificationChannel(str, Enum):
    WEBHOOK = "WEBHOOK"
    EMAIL = "EMAIL"


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    transaction_id: uuid.UUID
    event_type: str
    channel: NotificationChannel
    webhook_url: str | None = None
    recipient: str | None = None
    payload_hash: str
    status: NotificationStatus
    attempt_count: int = Field(default=0)
    last_attempted_at: datetime | None = None
    delivered_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
