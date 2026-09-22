import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import Base, TimestampMixin

SCHEMA = "customers"


class EntityType(str, enum.Enum):
    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"
    BOTH = "BOTH"


class KYBStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RiskRating(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    ENHANCED = "ENHANCED"


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = ({"schema": SCHEMA},)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type_enum", schema=SCHEMA), nullable=False
    )
    jurisdiction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    kyb_status: Mapped[KYBStatus] = mapped_column(
        Enum(KYBStatus, name="kyb_status_enum", schema=SCHEMA),
        nullable=False,
        default=KYBStatus.PENDING,
    )
    risk_rating: Mapped[RiskRating] = mapped_column(
        Enum(RiskRating, name="risk_rating_enum", schema=SCHEMA),
        nullable=False,
        default=RiskRating.LOW,
    )
    sector_classification: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_accounts: Mapped[list["BeneficiaryBankAccount"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class BeneficiaryBankAccount(TimestampMixin, Base):
    __tablename__ = "beneficiary_bank_accounts"
    __table_args__ = ({"schema": SCHEMA},)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="CASCADE"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Stored encrypted at rest — plaintext never persisted
    account_number_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Target class passed explicitly: the onboarding module also defines a
    # `Customer`, so a bare "Customer" string is ambiguous in the shared registry.
    customer: Mapped["Customer"] = relationship(Customer, back_populates="bank_accounts")
