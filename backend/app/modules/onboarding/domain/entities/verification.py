import uuid

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.enums import VerificationStatus
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class Verification(AppendOnlyModel):
    """
    Immutable record of a single verification outcome for a customer.

    One row is written each time the provider reports a result (typically via
    webhook). Append-only — a customer's verification history is never rewritten,
    only added to. Enforced by the `prevent_mutation()` DB trigger.
    """

    __tablename__ = "onboarding_verifications"
    __table_args__ = (
        Index("ix_onboarding_verifications_customer_id", "customer_id"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.onboarding_customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # Provider reference — applicantId / inspectionId.
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Raw provider fields, preserved verbatim for audit.
    review_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    review_answer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="onboarding_verification_status_enum", schema=SCHEMA),
        nullable=False,
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
