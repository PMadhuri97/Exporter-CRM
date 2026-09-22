import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base

SCHEMA = "ledger"


class IdempotencyKeyType(str, enum.Enum):
    """How the idempotency key was obtained."""

    CUSTOMER_KEY = "customer_key"
    INTERNAL_DERIVED_KEY = "internal_derived_key"
    RAIL_REFERENCE = "rail_reference"


class IdempotencyStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


def _idempotency_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Postgres enum storing the member VALUE, not the member NAME.

    c41c3d57d7cf declares these labels lowercase, so values_callable is required
    or SQLAlchemy would persist the uppercase member names instead.
    """
    return Enum(
        py_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda e: [m.value for m in e],
    )


class IdempotencyRecord(Base):
    """Generic idempotency ledger introduced by AL-41 (c41c3d57d7cf).

    Distinct from ``IdempotencyKey`` above, which is the older 24-hour payment
    submission guard. The two coexist and overlap in intent; consolidating them
    is tracked as a follow-up.

    Every index and constraint is named explicitly to match the migration. Left
    to ``index=True`` SQLAlchemy would auto-name them ``ix_ledger_...`` — the
    schema is part of the generated name — and diverge from the database.
    """

    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("key_value", "scope_id", name="uq_idempotency_record_key_scope"),
        # Caps a cached response at 64 KiB so the table cannot become a blob store.
        CheckConstraint(
            "response_cache IS NULL OR octet_length(response_cache::text) <= 65536",
            name="ck_response_cache_size",
        ),
        Index("ix_idempotency_record_scope_status", "scope_id", "status"),
        Index("ix_idempotency_record_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_value: Mapped[str] = mapped_column(String(256), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    key_type: Mapped[IdempotencyKeyType] = mapped_column(
        _idempotency_enum(IdempotencyKeyType, "idempotency_key_type_enum"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[IdempotencyStatus] = mapped_column(
        _idempotency_enum(IdempotencyStatus, "idempotency_status_enum"), nullable=False
    )
    response_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Immutable once written — enforced by ledger.prevent_first_seen_at_update().
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 'metadata' is reserved on declarative classes, so the attribute is renamed
    # while the column keeps the name the migration created.
    record_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
