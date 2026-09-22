"""SQLAlchemy model for the duplicate detection log.

A duplicate detection is the idempotency mechanism *working*: a key was
re-presented, recognised, and the operation was not executed a second time.
That is the opposite of an idempotency violation, which is a key that failed to
deduplicate and let a real duplicate through. The two are recorded in different
places for that reason — violations go to the audit log as compliance events,
detections come here as an operational history.

WHY A ROW PER DETECTION AND NOT A COUNTER
``aner_idempotency_duplicates_total`` already counts these, and continues to:
the counter drives the dashboard and the alert. What a counter cannot answer is
*which* key, *whose* caller, and *when* — it is labelled by operation type and
key type only, because labelling a metric with a key value would be an unbounded
cardinality explosion. The audit query in S4T3 needs the individual rows.

``time_since_original_ms`` is stored rather than derived on read. It is the
field that carries the diagnostic weight — a duplicate 200ms after the original
is a network retry, one six hours later is a client replaying stale state — and
the original record it would be derived from may have been archived by the time
anyone queries this table.

Lives in the ``ledger`` schema beside ``idempotency_record``, so it is covered by
that schema's existing default SELECT privilege for ``ledger_ro`` and can be read
by the audit interface without a new role.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base

SCHEMA = "ledger"


class DuplicateDetection(Base):
    """One re-presentation of an idempotency key that was correctly short-circuited.

    Append-only: ``public.prevent_mutation()`` rejects UPDATE and DELETE at the
    database level, so a detection cannot be revised after the fact.
    """

    __tablename__ = "duplicate_detection"
    __table_args__ = (
        # The S4T3 access path: an operation type over a time window. Leading
        # equality column, range and ordering on the second.
        Index("ix_duplicate_detection_operation_detected", "operation_type", "detected_at"),
        # Reaching a detection from the key it belongs to, which is how an
        # investigation arrives here from a registry record.
        Index("ix_duplicate_detection_key_scope", "idempotency_key", "scope_id"),
        Index("ix_duplicate_detection_correlation_id", "correlation_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: The key that was re-presented. Matches idempotency_record.key_value.
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    #: The scope the key was re-presented under. Not in the epic's field list, but
    #: the registry is unique on (key_value, scope_id) and a key alone identifies
    #: nothing — without this, a detection cannot be joined back to its record.
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The idempotency_record this duplicate matched against. Deliberately NOT a
    #: foreign key: the nightly archival job DELETEs from idempotency_record after
    #: copying to idempotency_archive, and an FK — RESTRICT per BUILD.md for
    #: financial references — would make that job fail the first time it touched
    #: an archived key. The referenced record may live in either table, which is
    #: exactly the split the audit repository already resolves.
    original_request_ref: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    #: When the original ran. Its completion, or its registration where it had not
    #: completed — a duplicate can arrive against a still-active record.
    original_executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: Who submitted the duplicate — not who submitted the original. Nullable
    #: because the HTTP middleware does not currently thread an authenticated
    #: principal into registration, so it is NULL on the customer-key path.
    caller_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Correlation ID of the duplicate request, not of the original.
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time_since_original_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The result handed back instead of re-executing. The registry keeps request
    #: and cached response on one row, so this resolves to the same record as
    #: original_request_ref; it is kept distinct because the two answer different
    #: questions and will diverge if a result ever becomes its own entity.
    returned_result_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
