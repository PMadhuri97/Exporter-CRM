import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingDocumentType,
    OnboardingValidationStatus,
)
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest

SCHEMA = "onboarding"

class OnboardingDocument(AnerModel):
    __tablename__ = "onboarding_document"
    __table_args__ = (
        Index("ix_onboarding_document_onboarding_request_id", "onboarding_request_id"),
        {"schema": SCHEMA},
    )

    onboarding_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.onboarding_request.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[OnboardingDocumentType] = mapped_column(
        Enum(OnboardingDocumentType, name="onboarding_document_type_enum", schema=SCHEMA), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    validation_status: Mapped[OnboardingValidationStatus] = mapped_column(
        Enum(OnboardingValidationStatus, name="onboarding_validation_status_enum", schema=SCHEMA), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped["OnboardingRequest"] = relationship("OnboardingRequest", back_populates="documents")
