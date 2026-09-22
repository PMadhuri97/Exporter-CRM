import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class ApplicantMapping(AnerModel):
    """
    Maps an onboarding Customer to its provider-side applicant.

    Keeps the provider's opaque identifiers (applicant id, externalUserId) out of
    the Customer row so a customer could, in future, be re-onboarded or mapped to
    more than one provider without schema churn.
    """

    __tablename__ = "onboarding_applicant_mappings"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.onboarding_customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable: the applicant may be created asynchronously in some providers.
    applicant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level_name: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        # One applicant mapping per customer per provider.
        UniqueConstraint("customer_id", "provider", name="uq_onboarding_mapping_customer_provider"),
        # A provider applicant id is unique within a provider.
        UniqueConstraint("provider", "applicant_id", name="uq_onboarding_mapping_provider_applicant"),
        Index("ix_onboarding_applicant_mappings_customer_id", "customer_id"),
        {"schema": SCHEMA},
    )
