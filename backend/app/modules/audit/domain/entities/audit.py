import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "audit"
PAYMENTS_SCHEMA = "payments"


class ActorType(str, enum.Enum):
    """Class of principal an audit row is attributed to — not the user's role.

    SYSTEM: platform acting on its own; actor_id is NULL.
    COMPLIANCE_OFFICER: internal staff acting with privileged authority
        (any role-gated back-office endpoint, incl. OPERATIONS/ADMIN).
    API_CLIENT: external caller acting on its own resources.
    """

    SYSTEM = "SYSTEM"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    API_CLIENT = "API_CLIENT"


class AuditEvent(AppendOnlyModel):
    """
    Write-once. REVOKE UPDATE, DELETE enforced by DB trigger (see migration).
    Retained 7 years per financial compliance requirements.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # Named explicitly: index=True would auto-name it
        # ix_<schema>_<table>_<column> now the table carries a schema, which is
        # not the name the database has.
        Index("ix_audit_events_correlation_id", "correlation_id"),
        # Newest-first reads filtered by event type: the audit API's own feed and
        # the idempotency violations query. Without it, both sort the whole
        # platform-wide audit log on every page.
        Index("ix_audit_events_event_type_created_at", "event_type", "created_at"),
        {"schema": SCHEMA},
    )

    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=True,
    )
    # End-to-end trace key. Auto-populated from the request's X-Correlation-Id
    # (structlog contextvars) so audit events can be followed across services.
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type_enum", schema=SCHEMA), nullable=False
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    synced_to_sink_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
