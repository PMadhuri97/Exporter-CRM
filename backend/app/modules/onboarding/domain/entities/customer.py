
from sqlalchemy import Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.enums import OnboardingStatus
from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class Customer(AnerModel):
    """
    Onboarding identity record.

    This is the *onboarding foundation* customer — the entity being taken through
    KYC/KYB verification with an identity provider (Sumsub). It is intentionally
    decoupled from the settlement `customers` registry (`app.modules.customers`);
    a link between the two is a later phase and is not part of this foundation.

    Backed by its own table (`onboarding_customers`) so the two concepts never
    collide.
    """

    __tablename__ = "onboarding_customers"
    __table_args__ = (
        Index("ix_onboarding_customers_email", "email", unique=True),
        Index("ix_onboarding_customers_external_user_id", "external_user_id", unique=True),
        {"schema": SCHEMA},
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # The stable id we hand to the identity provider as `externalUserId`.
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    level_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[OnboardingStatus] = mapped_column(
        Enum(OnboardingStatus, name="onboarding_status_enum", schema=SCHEMA),
        nullable=False,
        default=OnboardingStatus.PENDING,
    )
