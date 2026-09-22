import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.entities.orchestration_enums import KybNormalisedResult
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest

SCHEMA = "onboarding"

class KybVendorResult(AnerModel):
    __tablename__ = "kyb_vendor_result"
    __table_args__ = (
        Index("ix_kyb_vendor_result_onboarding_request_id", "onboarding_request_id"),
        {"schema": SCHEMA},
    )

    onboarding_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.onboarding_request.id", ondelete="CASCADE"), nullable=False
    )
    vendor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor_reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalised_result: Mapped[KybNormalisedResult] = mapped_column(
        Enum(KybNormalisedResult, name="kyb_normalised_result_enum", schema=SCHEMA), nullable=False
    )

    # Encrypted at rest. Store as Text for ciphertext capacity.
    raw_vendor_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped["OnboardingRequest"] = relationship("OnboardingRequest", back_populates="vendor_results")
