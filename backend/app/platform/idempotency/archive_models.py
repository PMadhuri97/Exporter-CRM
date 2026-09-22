"""SQLAlchemy model for the idempotency archive table.

Mirrors every column of ``IdempotencyRecord`` plus ``archived_at``. This model
lives in the **platform** idempotency package (not ``modules/ledger``) so the
archival service can import it without violating the layering rule that
``app.platform`` must not import from ``app.modules``.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base
from app.platform.idempotency.models import IdempotencyKeyType, IdempotencyStatus

SCHEMA = "ledger"


def _idempotency_enum(py_enum: type[enum.Enum], name: str) -> SQLEnum:
    return SQLEnum(
        py_enum,
        name=name,
        schema=SCHEMA,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )


class IdempotencyArchive(Base):
    """Archive table for aged idempotency records (S3T3).

    Same schema as ``idempotency_record`` plus ``archived_at``. Records are
    moved here by the nightly archival job and are protected by a DELETE-blocking
    trigger at the database level.

    The Postgres enum types ``idempotency_key_type_enum`` and
    ``idempotency_status_enum`` are shared with ``idempotency_record`` and were
    already created by migration c41c3d57d7cf; ``create_type=False`` prevents a
    duplicate CREATE TYPE.
    """

    __tablename__ = "idempotency_archive"
    __table_args__ = (
        Index("ix_idempotency_archive_key_scope", "key_value", "scope_id"),
        # The archive is never swept, so a scope query without this reads a
        # table that only ever grows. key_scope above cannot help: scope_id is
        # its second column, and a query by scope alone has no leading match.
        Index("ix_idempotency_archive_scope_first_seen", "scope_id", "first_seen_at"),
        Index("ix_idempotency_archive_archived_at", "archived_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    key_value: Mapped[str] = mapped_column(String(256), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    key_type: Mapped[IdempotencyKeyType] = mapped_column(
        _idempotency_enum(IdempotencyKeyType, "idempotency_key_type_enum"),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[IdempotencyStatus] = mapped_column(
        _idempotency_enum(IdempotencyStatus, "idempotency_status_enum"),
        nullable=False,
    )
    response_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # Archive-specific column
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
