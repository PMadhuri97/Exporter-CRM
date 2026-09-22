"""Audit Service Pydantic schemas — read-only projections of the write-once
`audit_events` store exposed by the audit query API."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.audit.domain.entities.audit import ActorType, AuditEvent


class AuditEventResponse(BaseModel):
    """A single immutable audit record."""

    event_id: uuid.UUID
    transaction_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    event_type: str
    actor_id: uuid.UUID | None = None
    actor_type: ActorType
    payload: dict | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, event: AuditEvent) -> AuditEventResponse:
        # The model's PK attribute is `id`; the API exposes it as `event_id`.
        return cls(
            event_id=event.id,
            transaction_id=event.transaction_id,
            correlation_id=event.correlation_id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            payload=event.payload,
            created_at=event.created_at,
        )


class AuditEventListResponse(BaseModel):
    """A page of audit records plus enough metadata to paginate the caller."""

    events: list[AuditEventResponse]
    total: int
    limit: int
    offset: int
