import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "reconciliation"
PAYMENTS_SCHEMA = "payments"


class ReconciliationStatus(str, enum.Enum):
    """Overall outcome of a three-way match."""

    MATCHED = "MATCHED"  # all checks passed — Ledger, Settlement, Bank agree
    BREAK = "BREAK"      # one or more checks failed — investigation required


class ReconciliationCheckType(str, enum.Enum):
    """The individual comparisons that make up the three-way match."""

    # Ledger internal integrity
    LEDGER_DOUBLE_ENTRY_BALANCED = "LEDGER_DOUBLE_ENTRY_BALANCED"
    # Ledger ↔ Settlement
    LEDGER_VS_SETTLEMENT_USD_AMOUNT = "LEDGER_VS_SETTLEMENT_USD_AMOUNT"
    # Settlement ↔ Bank confirmation (USDC bridge partner)
    SETTLEMENT_VS_BANK_USDC_REFERENCE = "SETTLEMENT_VS_BANK_USDC_REFERENCE"
    SETTLEMENT_VS_BANK_USDC_AMOUNT = "SETTLEMENT_VS_BANK_USDC_AMOUNT"
    # Settlement ↔ Bank confirmation (INR banking partner)
    SETTLEMENT_VS_BANK_INR_REFERENCE = "SETTLEMENT_VS_BANK_INR_REFERENCE"
    SETTLEMENT_VS_BANK_INR_AMOUNT = "SETTLEMENT_VS_BANK_INR_AMOUNT"


class Reconciliation(AppendOnlyModel):
    """
    Append-only reconciliation snapshot. Each run is an immutable point-in-time
    record — a transaction may be reconciled multiple times (e.g. on a schedule),
    and every run is preserved for audit.
    """

    __tablename__ = "reconciliations"
    __table_args__ = (
        Index("ix_reconciliations_transaction_id", "transaction_id"),
        {"schema": SCHEMA},
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReconciliationStatus] = mapped_column(
        Enum(ReconciliationStatus, name="reconciliation_status_enum", schema=SCHEMA), nullable=False
    )
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    break_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full structured report (source views + every check) for audit / replay.
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Set when a BREAK opens a RECONCILIATION_BREAK compliance case.
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ReconciliationCheck(AppendOnlyModel):
    """One row per individual comparison performed during a reconciliation run."""

    __tablename__ = "reconciliation_checks"
    __table_args__ = (
        Index("ix_reconciliation_checks_reconciliation_id", "reconciliation_id"),
        {"schema": SCHEMA},
    )

    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.reconciliations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    check_type: Mapped[ReconciliationCheckType] = mapped_column(
        Enum(ReconciliationCheckType, name="reconciliation_check_type_enum", schema=SCHEMA),
        nullable=False,
    )
    source_a: Mapped[str] = mapped_column(String(30), nullable=False)
    source_b: Mapped[str] = mapped_column(String(30), nullable=False)
    value_a: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value_b: Mapped[str | None] = mapped_column(String(255), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
