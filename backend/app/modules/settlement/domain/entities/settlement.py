import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base, TimestampMixin

SCHEMA = "settlement"
PAYMENTS_SCHEMA = "payments"


class LegType(str, enum.Enum):
    USD_DEBIT = "USD_DEBIT"
    USDC_BRIDGE = "USDC_BRIDGE"
    INR_PAYOUT = "INR_PAYOUT"


class LegStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SettlementLeg(TimestampMixin, Base):
    __tablename__ = "settlement_legs"
    __table_args__ = ({"schema": SCHEMA},)

    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    leg_type: Mapped[LegType] = mapped_column(
        Enum(LegType, name="leg_type_enum", schema=SCHEMA), nullable=False
    )
    status: Mapped[LegStatus] = mapped_column(
        Enum(LegStatus, name="leg_status_enum", schema=SCHEMA),
        nullable=False,
        default=LegStatus.PENDING,
    )
    # Blockchain tx ID or bank reference
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Rule 1: integer minor units, scaled by the currency's registry precision.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
