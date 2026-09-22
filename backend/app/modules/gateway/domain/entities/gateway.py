"""Gateway domain entities.

``api_request_logs`` is the gateway's own append-only trail of external
traffic — distinct from ``app.modules.audit`` (business audit events) and from
``app.platform.observability`` (stdout structured logs, not queryable after
the fact). It exists so "what did the gateway see and return" can be answered
even when log aggregation is unavailable.

Deliberately narrow: there is no request or response BODY column, and no
column that could carry an account number, PII, or any other sensitive value
by copy. ``customer_id`` is the only customer-linked field, and it is a bare
reference — nullable, because no authentication exists yet in this slice (see
ANER-4.4-S1T2, which will start populating it once callers are identified).

Whoever adds body-aware logging later must add a new, explicitly reviewed
column for it rather than repurposing an existing one, and must redact or
allowlist at the point of capture — this table is not the place to learn that
lesson from a leaked account number in an audit trail.
"""
import uuid

from sqlalchemy import BigInteger, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "gateway"


class ApiRequestLog(AppendOnlyModel):
    """One row per request the gateway's request-handling pipeline observed."""

    __tablename__ = "api_request_logs"
    __table_args__ = (
        Index("ix_api_request_logs_correlation_id", "correlation_id"),
        Index("ix_api_request_logs_customer_id", "customer_id"),
        {"schema": SCHEMA},
    )

    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # No FK: no authentication exists yet, so this is always NULL today. A bare
    # reference rather than a foreign key so this table is never blocked on
    # customers being resolvable at write time.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
