import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingEntityType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingRiskRating,
    OnboardingScreeningResult,
)
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.kyb_vendor_result import KybVendorResult
    from app.modules.onboarding.domain.entities.onboarding_document import OnboardingDocument
    from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
    from app.modules.onboarding.domain.entities.ubo_record import UboRecord

SCHEMA = "onboarding"

class OnboardingRequest(AnerModel):
    __tablename__ = "onboarding_request"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_onboarding_request_tenant_idem_key"),
        Index("ix_onboarding_request_tenant_id", "tenant_id"),
        Index("ix_onboarding_request_customer_id", "customer_id"),
        Index(
            "uq_onboarding_request_active_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'")
        ),
        {"schema": SCHEMA},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[OnboardingRequestStatus] = mapped_column(
        Enum(OnboardingRequestStatus, name="onboarding_request_status_enum", schema=SCHEMA), nullable=False
    )
    entity_type: Mapped[OnboardingEntityType] = mapped_column(
        Enum(OnboardingEntityType, name="onboarding_entity_type_enum", schema=SCHEMA), nullable=False
    )
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable since onboarding_0007_reg_optional: a Sales-sourced Lead is
    # created with only legal_name + incorporation_country known, and fills
    # this in later via OnboardingRequestService.submit_entity_details.
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Encrypted at rest. Store as String(512) for ciphertext capacity.
    tax_identification_number: Mapped[str | None] = mapped_column(String(512), nullable=True)

    incorporation_country: Mapped[str] = mapped_column(String(2), nullable=False)
    incorporation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Nullable since onboarding_0007_reg_optional — see registration_number.
    registered_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trading_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    industry_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    declared_monthly_volume_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    corridor_intent: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    account_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    initial_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    initial_user_roles: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    screening_result: Mapped[OnboardingScreeningResult | None] = mapped_column(
        Enum(OnboardingScreeningResult, name="onboarding_screening_result_enum", schema=SCHEMA), nullable=True
    )
    ubo_mapping: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    screening_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    risk_rating: Mapped[OnboardingRiskRating | None] = mapped_column(
        Enum(OnboardingRiskRating, name="onboarding_risk_rating_enum", schema=SCHEMA), nullable=True
    )
    risk_rating_factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    edd_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    edd_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    compliance_approval_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    compliance_decision: Mapped[OnboardingComplianceDecision | None] = mapped_column(
        Enum(OnboardingComplianceDecision, name="onboarding_compliance_decision_enum", schema=SCHEMA), nullable=True
    )
    rejection_category: Mapped[OnboardingRejectionCategory | None] = mapped_column(
        Enum(OnboardingRejectionCategory, name="onboarding_rejection_category_enum", schema=SCHEMA), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ubo_records: Mapped[list["UboRecord"]] = relationship(
        "UboRecord", back_populates="request", cascade="all, delete-orphan"
    )
    documents: Mapped[list["OnboardingDocument"]] = relationship(
        "OnboardingDocument", back_populates="request", cascade="all, delete-orphan"
    )
    events: Mapped[list["OnboardingEvent"]] = relationship(
        "OnboardingEvent", back_populates="request"
    )
    vendor_results: Mapped[list["KybVendorResult"]] = relationship(
        "KybVendorResult", back_populates="request", cascade="all, delete-orphan"
    )
