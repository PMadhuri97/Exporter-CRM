"""Domain models and typed validation results for idempotency key validation."""

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    func,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base

SCHEMA = "ledger"


class ValidationReason(str, Enum):
    """Specific failure reasons for idempotency key format validation."""

    EMPTY_KEY = "EMPTY_KEY"
    EXCEEDS_MAX_LENGTH = "EXCEEDS_MAX_LENGTH"
    INVALID_UUID_V4 = "INVALID_UUID_V4"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_STEP_IDENTIFIER = "INVALID_STEP_IDENTIFIER"
    UNKNOWN_RAIL_CODE = "UNKNOWN_RAIL_CODE"


@dataclass(frozen=True)
class KeyValidationResult:
    """Typed result representing the validation status of an idempotency key."""

    is_valid: bool
    reason: ValidationReason | None = None
    message: str | None = None

    @classmethod
    def valid(cls) -> "KeyValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True)

    @classmethod
    def invalid(cls, reason: ValidationReason, message: str) -> "KeyValidationResult":
        """Create a failed validation result with specific reason and message."""
        return cls(is_valid=False, reason=reason, message=message)


class RegistrationResultType(str, Enum):
    """Outcome type for idempotency key registration."""

    NEW = "new"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class RegistrationResult:
    """Typed outcome returned when registering an idempotency key."""

    result: RegistrationResultType
    record: "IdempotencyRecord | None"
    validation_result: KeyValidationResult | None = None

    @property
    def registration_result(self) -> str:
        """String representation of registration result ('new' or 'duplicate')."""
        return self.result.value if isinstance(self.result, RegistrationResultType) else str(self.result)

    @classmethod
    def new(cls, record: "IdempotencyRecord | None") -> "RegistrationResult":
        return cls(result=RegistrationResultType.NEW, record=record)

    @classmethod
    def duplicate(cls, record: "IdempotencyRecord | None") -> "RegistrationResult":
        return cls(result=RegistrationResultType.DUPLICATE, record=record)


class DuplicateHandlingAction(str, Enum):
    """Action required by consuming service when evaluating a duplicate idempotency record."""

    CONFLICT_ACTIVE = "conflict_active"
    RETURN_CACHED_SUCCESS = "return_cached_success"
    RETURN_CACHED_FAILURE = "return_cached_failure"
    EXECUTE_NEW = "execute_new"


@dataclass(frozen=True)
class DuplicateContractResult:
    """Typed evaluation result of duplicate handling contract."""

    action: DuplicateHandlingAction
    status: "IdempotencyStatus"
    response_cache: dict | None = None
    message: str | None = None


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


def _idempotency_enum(py_enum: type[enum.Enum], name: str) -> SQLEnum:
    return SQLEnum(
        py_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda e: [m.value for m in e],
    )


#: Predicate isolating the *live* records — everything that is not expired history.
#:
#: Uniqueness of (key_value, scope_id) holds over these rows only, which is what lets an
#: expired record stay in the table for audit while its key becomes registrable again
#: (S3T1 requirement 3). At most one live record per pair; unlimited expired ones beside it.
#:
#: Held as raw SQL rather than a SQLAlchemy expression because it is used in two places
#: that must agree *textually*: this index, and the ON CONFLICT index inference in
#: services.py. A column expression there would render as a bound parameter, and Postgres
#: cannot prove a parameterised predicate implies the index predicate — inference fails at
#: runtime with "no unique or exclusion constraint matching the ON CONFLICT specification".
LIVE_RECORD_PREDICATE_SQL = "status <> 'expired'"

#: Predicate for the S3T1 time-based expiry sweep, which processes customer keys ONLY.
#:
#: IDK and RR never expire on a clock — their lifecycle ends when the parent settlement
#: reaches a terminal state, which S3T2 owns. Encoding key_type into the index predicate
#: makes that rule structural rather than conventional: a sweep query that drops the
#: key_type filter also loses this index and shows up as a sequential scan in review.
CK_SWEEP_PREDICATE_SQL = (
    "key_type = 'customer_key' AND status IN ('completed', 'failed')"
)


class IdempotencyRecord(Base):
    """Generic idempotency ledger table ledger.idempotency_record."""

    __tablename__ = "idempotency_record"
    __table_args__ = (
        # Partial unique index, not a UNIQUE constraint: expired rows are excluded so a
        # key becomes registrable again once its window closes. The name is retained from
        # the constraint it replaced — existing tests assert on it in pg_indexes and in
        # UniqueViolation messages, and a unique index satisfies both.
        Index(
            "uq_idempotency_record_key_scope",
            "key_value",
            "scope_id",
            unique=True,
            postgresql_where=text(LIVE_RECORD_PREDICATE_SQL),
        ),
        CheckConstraint(
            "response_cache IS NULL OR octet_length(response_cache::text) <= 65536",
            name="ck_response_cache_size",
        ),
        Index("ix_idempotency_record_scope_status", "scope_id", "status"),
        # Serves the audit interface's scope-and-date reconstruction. Distinct
        # from the index above: that one's second column cannot satisfy a range
        # on first_seen_at, nor the ordering the query asks for.
        Index("ix_idempotency_record_scope_first_seen", "scope_id", "first_seen_at"),
        Index("ix_idempotency_record_expires_at", "expires_at"),
        Index(
            "ix_idempotency_record_ck_expiry",
            "expires_at",
            postgresql_where=text(CK_SWEEP_PREDICATE_SQL),
        ),
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
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
