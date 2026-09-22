import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AppendOnlyModel, Base, CreatedOnlyMixin, TimestampMixin

SCHEMA = "payments"
CUSTOMERS_SCHEMA = "customers"


class TransactionStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    VALIDATED = "VALIDATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    DIGITAL_ASSET_SETTLED = "DIGITAL_ASSET_SETTLED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    RECONCILED = "RECONCILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BLOCKED = "BLOCKED"
    DECLINED = "DECLINED"
    FAILED = "FAILED"
    RECALLED_VIA_COMPENSATION = "RECALLED_VIA_COMPENSATION"


class SettlementRoute(str, enum.Enum):
    FIAT = "FIAT"
    DIGITAL_ASSET_BRIDGE = "DIGITAL_ASSET_BRIDGE"


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = ({"schema": SCHEMA},)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sender_customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{CUSTOMERS_SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    beneficiary_customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{CUSTOMERS_SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Rule 1: integer minor units, scaled by source_currency's registry precision.
    # Previously String(30), which stored whatever text the caller sent.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    destination_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transaction_status_enum", schema=SCHEMA),
        nullable=False,
        default=TransactionStatus.INITIATED,
    )
    settlement_route: Mapped[SettlementRoute | None] = mapped_column(
        Enum(SettlementRoute, name="settlement_route_enum", schema=SCHEMA),
        nullable=True,
    )
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status_history: Mapped[list["TransactionStatusHistory"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class TransactionStatusHistory(AppendOnlyModel):
    """Immutable status audit trail — append-only, enforced by DB trigger."""

    __tablename__ = "transaction_status_history"
    __table_args__ = ({"schema": SCHEMA},)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.transactions.transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[TransactionStatus | None] = mapped_column(
        Enum(TransactionStatus, name="transaction_status_enum", schema=SCHEMA),
        nullable=True,
    )
    to_status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transaction_status_enum", schema=SCHEMA),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    transaction: Mapped["Transaction"] = relationship(back_populates="status_history")


class IdempotencyKey(CreatedOnlyMixin, Base):
    """Prevents duplicate payment submissions within a 24-hour window."""

    __tablename__ = "idempotency_keys"
    __table_args__ = ({"schema": SCHEMA},)

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


