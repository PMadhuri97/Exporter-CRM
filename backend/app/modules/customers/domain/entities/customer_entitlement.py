import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    EntitlementSource,
    EntitlementType,
    LimitPeriod,
)
from app.platform.database.models import AnerModel

SCHEMA = "customers"


class CustomerEntitlement(AnerModel):
    """What a customer is permitted to do — corridors, limits, products, assets.

    This module sets a customer's entitled limits; the real-time limits engine
    enforces them per transaction. The two must not disagree, so the limit
    amount and its currency travel together and neither is meaningful alone.

    `approval_request_id` is NOT NULL rather than conditionally required: no
    entitlement exists without a recorded approval behind it, including the ones
    granted at onboarding.
    """

    __tablename__ = "customer_entitlement"
    __table_args__ = (
        # The enforcement path reads a customer's live entitlements by type.
        Index(
            "ix_customer_entitlement_lookup",
            "customer_id",
            "entitlement_type",
            "active",
        ),
        # Money is an integer amount in minor units beside its currency. An
        # amount with no currency is not an amount.
        CheckConstraint(
            "(limit_value_minor IS NULL) = (limit_currency IS NULL)",
            name="ck_customer_entitlement_limit_paired",
        ),
        # A limit with no period is not a limit either — 500000 of what, per what?
        CheckConstraint(
            "(limit_value_minor IS NULL) = (limit_period IS NULL)",
            name="ck_customer_entitlement_limit_period_paired",
        ),
        # Zero is a meaningful cap — permitted, but for nothing — so the floor is
        # non-negative rather than positive.
        CheckConstraint(
            "limit_value_minor IS NULL OR limit_value_minor >= 0",
            name="ck_customer_entitlement_limit_non_negative",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_customer_entitlement_period_ordered",
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_type: Mapped[EntitlementType] = mapped_column(
        Enum(EntitlementType, name="entitlement_type_enum", schema=SCHEMA), nullable=False
    )
    # Which corridor, product or asset. Null for aggregate limits, which apply
    # across all of them.
    entitlement_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    permitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    limit_value_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # String(8), not String(3): wide enough for registry asset codes such as
    # USDC alongside ISO-4217 currencies.
    limit_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    limit_period: Mapped[LimitPeriod | None] = mapped_column(
        Enum(LimitPeriod, name="entitlement_limit_period_enum", schema=SCHEMA), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[EntitlementSource] = mapped_column(
        Enum(EntitlementSource, name="entitlement_source_enum", schema=SCHEMA), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
