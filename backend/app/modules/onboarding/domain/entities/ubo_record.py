import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.entities.orchestration_enums import (
    UboControlType,
    UboIdentificationType,
    UboKycResult,
    UboPepStatus,
)
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest

SCHEMA = "onboarding"

class UboRecord(AnerModel):
    __tablename__ = "ubo_record"
    __table_args__ = (
        Index("ix_ubo_record_onboarding_request_id", "onboarding_request_id"),
        {"schema": SCHEMA},
    )

    onboarding_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.onboarding_request.id", ondelete="CASCADE"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Encrypted at rest. Store as String(512) for ciphertext capacity.
    date_of_birth: Mapped[str | None] = mapped_column(String(512), nullable=True)

    nationality: Mapped[str | None] = mapped_column(String(2), nullable=True)
    residence_country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    identification_type: Mapped[UboIdentificationType | None] = mapped_column(
        Enum(UboIdentificationType, name="ubo_identification_type_enum", schema=SCHEMA), nullable=True
    )

    # Encrypted at rest. Store as String(512) for ciphertext capacity.
    identification_number: Mapped[str | None] = mapped_column(String(512), nullable=True)

    control_type: Mapped[UboControlType] = mapped_column(
        Enum(UboControlType, name="ubo_control_type_enum", schema=SCHEMA), nullable=False
    )
    ownership_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    kyc_result: Mapped[UboKycResult] = mapped_column(
        Enum(UboKycResult, name="ubo_kyc_result_enum", schema=SCHEMA), nullable=False
    )
    screening_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    pep_status: Mapped[UboPepStatus | None] = mapped_column(
        Enum(UboPepStatus, name="ubo_pep_status_enum", schema=SCHEMA), nullable=True
    )

    request: Mapped["OnboardingRequest"] = relationship("OnboardingRequest", back_populates="ubo_records")

    def __repr__(self) -> str:
        return f"<UboRecord id={self.id} onboarding_request_id={self.onboarding_request_id}>"
