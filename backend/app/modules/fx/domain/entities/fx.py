import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base, TimestampMixin

SCHEMA = "fx"
PAYMENTS_SCHEMA = "payments"


class FxQuote(TimestampMixin, Base):
    __tablename__ = "fx_quotes"
    __table_args__ = ({"schema": SCHEMA},)

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=True,
    )
    from_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    # Rates are ratios, not money: they stay NUMERIC and are explicitly outside
    # Rule 1. mid_rate is the pre-spread market rate; it is an input to a money
    # multiplication so it carries more scale than the applied rate.
    mid_rate: Mapped[object] = mapped_column(Numeric(18, 10), nullable=False)
    rate: Mapped[object] = mapped_column(Numeric(12, 6), nullable=False)
    # Widened from NUMERIC(6,4): the service quantizes the spread to 6dp, so the
    # 5th and 6th digits were being silently truncated on every quote.
    spread: Mapped[object] = mapped_column(Numeric(9, 6), nullable=False)
    # Rule 1: integer minor units, scaled by the asset's registry precision. The
    # previous NUMERIC(18,2) silently truncated any 6dp USDC amount.
    source_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
