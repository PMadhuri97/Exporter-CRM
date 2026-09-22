"""Multi-asset ledger — Epic 2.1 canonical data model.

Four tables (all names are singular, matching the data model specification):
  ledger_account       — the account record, scoped to exactly one asset.
  ledger_transaction   — the atomicity unit; a balanced set of entries.
  ledger_entry         — the individual debit/credit line. Append-only.
  account_balance      — materialised current balance, for read performance.

Invariants enforced at the database level (see the ledger migrations):
  Rule 1  amount, balance_before, balance_after are BIGINT integer minor units.
  Rule 2  ledger_entry is append-only — prevent_mutation() blocks UPDATE/DELETE.
  Rule 3  every (transaction, asset) nets to zero — deferred constraint trigger.
  Rule 4  every monetary event posts a ledger_transaction (enforced by review, and
          by reconciliation checks that assert clearing accounts return to zero).

Mutability boundaries (enforced at the DB level by column-guard triggers):
  ledger_entry        — fully append-only: prevent_mutation() blocks all UPDATE/DELETE.
  ledger_transaction  — only status and posted_at may change; all other fields are
                        DB-guarded. DELETE is blocked (ANER3/ANER5).
  ledger_account      — only status and account_metadata may change; precision,
                        asset_code, entity_id, etc. are DB-guarded. DELETE is
                        blocked (ANER4/ANER5).
  account_balance     — fully mutable: updated atomically on every entry insert
                        by the post_entry_balance() trigger. No immutability guard.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base

# Asset codes are registry codes (USD, INR, USDC, ...). 16 leaves headroom for
# longer token symbols without another widening migration.
ASSET_CODE_LEN = 16

# Every object in this module lives in the `ledger` schema. The enum types live
# there too, so `schema` has to be threaded through `_enum` as well — a bare
# Enum(name=...) would resolve against the search_path and not be found.
SCHEMA = "ledger"


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Postgres enum that stores the member VALUE, not the member NAME.

    The data model specifies lowercase values ('customer', 'debit', ...). SQLAlchemy
    defaults to persisting `.name` (uppercase), so values_callable is required or the
    stored labels would silently diverge from the spec.
    """
    return Enum(
        py_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda e: [m.value for m in e],
    )


# ── Enums ─────────────────────────────────────────────────────────────────────

class AccountType(str, enum.Enum):
    """Chart of accounts. A role, never an asset — the asset is asset_code."""

    CUSTOMER = "customer"
    TREASURY = "treasury"
    FEE = "fee"
    RESERVE = "reserve"
    CLEARING = "clearing"


class EntityType(str, enum.Enum):
    CUSTOMER = "customer"
    PLATFORM = "platform"
    FEE_POOL = "fee_pool"
    CLEARING_POOL = "clearing_pool"


class AccountStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TransactionType(str, enum.Enum):
    SETTLEMENT_DEBIT = "settlement_debit"
    SETTLEMENT_CREDIT = "settlement_credit"
    FEE_DEBIT = "fee_debit"
    COMPENSATION = "compensation"
    PREFUND_MOVEMENT = "prefund_movement"
    FX_CONVERSION = "fx_conversion"


class LedgerTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"


class Direction(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


# ── Tables ────────────────────────────────────────────────────────────────────

class LedgerAccount(Base):
    """One account, scoped to exactly one asset and one precision."""

    __tablename__ = "ledger_account"
    __table_args__ = (
        # Target of the composite FK on ledger_entry: guarantees an entry's
        # asset_code always matches its account's asset_code.
        UniqueConstraint("id", "asset_code", name="uq_ledger_account_id_asset"),
        # Spec: precision accepts only 2 (fiat), 6 (USDC), or 18 (ERC-20 tokens).
        CheckConstraint("precision IN (2, 6, 18)", name="ck_ledger_account_precision_allowed_values"),
        Index("ix_ledger_account_entity", "entity_id", "asset_code"),
        Index("ix_ledger_account_type_asset", "account_type", "asset_code"),
        Index(
            "uq_ledger_account_one_active",
            "entity_id",
            "account_type",
            "asset_code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_type: Mapped[AccountType] = mapped_column(
        _enum(AccountType, "ledger_account_type_enum"), nullable=False
    )
    asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)
    # Denormalised from CURRENCY_REGISTRY and immutable once set. bootstrap.py
    # asserts it still matches the registry at startup — a stale copy of a
    # versioned reference value is silent money corruption.
    precision: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(
        _enum(EntityType, "ledger_entity_type_enum"), nullable=False
    )
    status: Mapped[AccountStatus] = mapped_column(
        _enum(AccountStatus, "ledger_account_status_enum"),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 'metadata' is reserved on SQLAlchemy declarative classes, so the attribute is
    # renamed while the DB column keeps the name the data model specifies.
    account_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class LedgerTransaction(Base):
    """The atomicity unit: a balanced set of entries for one monetary event.

    MUTABLE by design — status and posted_at are written as the transaction posts.
    No append-only trigger (contrast LedgerEntry).
    """

    __tablename__ = "ledger_transaction"
    __table_args__ = (
        Index("ix_ledger_transaction_settlement", "settlement_id"),
        Index("ix_ledger_transaction_correlation", "correlation_id"),
        Index("uq_ledger_txn_idem", "idempotency_key", unique=True),
        Index(
            "uq_txn_single_compensation",
            "compensates_transaction_id",
            unique=True,
            postgresql_where=text("compensates_transaction_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(transaction_type = 'compensation') = (compensates_transaction_id IS NOT NULL)",
            name="ck_compensation_link",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Supplied by the caller; minted by Epic 2.3. Uniqueness is the idempotency
    # guarantee — a replayed activity collides here rather than double-posting.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        _enum(TransactionType, "ledger_transaction_type_enum"), nullable=False
    )
    status: Mapped[LedgerTransactionStatus] = mapped_column(
        _enum(LedgerTransactionStatus, "ledger_transaction_status_enum"),
        nullable=False,
        default=LedgerTransactionStatus.PENDING,
    )
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Deliberately NO foreign key, for two independent reasons.
    #
    # 1. The value is not a settlement.settlement id. The executing settlement path
    #    keys off the payments transaction, so settlement/application/ledger_postings.py
    #    stores that transaction id here (and _post() resolves it through
    #    payments.TransactionRepository). A constraint against the canonical
    #    settlement aggregate would not resolve for any row written today.
    # 2. Even once the aggregate drives execution, a ledger -> settlement FK would
    #    invert the dependency direction the architecture rests on: settlement
    #    depends on the ledger, never the reverse. The ledger stays independent of
    #    settlement, so this correlation is application-level by design.
    #
    # Treat it as an opaque grouping key: "which money movement produced this
    # transaction". Indexed for lookup; not referentially enforced.
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    compensates_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.ledger_transaction.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class LedgerEntry(Base):
    """One debit or credit line. Append-only — never updated, never deleted.

    balance_before and balance_after are populated by the post_entry_balance()
    BEFORE INSERT trigger, not by application code: doing it in the database makes
    an incorrect balance chain structurally impossible regardless of caller, and
    gives atomicity with account_balances for free.
    """

    __tablename__ = "ledger_entry"
    __table_args__ = (
        # Rule 1: amounts are positive integers; direction carries the sign.
        CheckConstraint("amount > 0", name="ck_ledger_entry_amount_positive"),
        # An entry's asset must match its account's asset — structural, not a
        # service-layer check. The composite FK references ledger_account (singular).
        ForeignKeyConstraint(
            ["account_id", "asset_code"],
            [f"{SCHEMA}.ledger_account.id", f"{SCHEMA}.ledger_account.asset_code"],
            name="fk_ledger_entry_account_asset",
            ondelete="RESTRICT",
        ),
        # Required, not cosmetic: the balance trigger re-aggregates this group
        # once per inserted row.
        Index("ix_ledger_entry_tx_asset", "transaction_id", "asset_code"),
        Index("ix_ledger_entry_account", "account_id", "created_at"),
        Index("uq_ledger_entry_seq", "entry_seq", unique=True),
        Index("ix_ledger_entry_account_seq", "account_id", "entry_seq"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entry_seq: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
        comment=(
            "Monotonic post-order sequence. The ONLY valid sort key for replay, "
            "history, and integrity checks. Gaps are expected and permitted. "
            "created_at is NOT a valid sort key - entries within a transaction "
            "share an identical timestamp."
        ),
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.ledger_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[Direction] = mapped_column(
        _enum(Direction, "ledger_direction_enum"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)
    # Populated by post_entry_balance() BEFORE INSERT. NOT NULL is safe: constraint
    # checks run after BEFORE triggers have modified NEW.
    balance_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    entry_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class AccountBalance(Base):
    """Materialised current balance. Derived from ledger_entries, updated atomically
    with each posting by the post_entry_balance() trigger. Exists for read
    performance — ledger_entries remains the source of truth.
    """

    __tablename__ = "account_balance"
    __table_args__ = ({"schema": SCHEMA},)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.ledger_account.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)
    # The entry that last moved this balance; set by post_entry_balance(). NULL
    # only for a freshly created account that has not yet been posted to.
    last_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.ledger_entry.id", ondelete="RESTRICT", name="fk_account_balance_last_entry", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
