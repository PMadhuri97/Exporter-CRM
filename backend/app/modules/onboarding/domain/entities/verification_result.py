"""`VerificationResult` — EXP-2's generalized verification-results table.

One row per check ever run — KYC on a director, a bank-account check on an
exporter, a shipment/vessel check, or anything not yet anticipated — through
the `VerificationAdapter` protocol (`workflow_dependencies.py`). This is the
new, broader table the EXP-2 plan calls for; it is *inspired by*
`kyb_vendor_result.py`'s shape (a vendor name, a vendor reference, a
normalised result, a raw response) but is not built on it and does not
replace it.

`KybVendorResult` is left exactly as it is — unmigrated, still written by
`kyb`'s existing path. This table is additive, for everything
`KybVendorResult` doesn't cover (confirmed in the EXP-2 plan as an
implementation-time call: don't touch `KybVendorResult` in this ticket).

No foreign keys on the subject
-------------------------------
`entity_reference` is a bare, undecorated UUID: `entity_type` determines which
table it actually points at (exporter_profile, a buyer, a director/UBO record,
an invoice, a vessel, a shipment — several of which don't exist as tables yet
in this checkout). This is the same bare-reference convention
`ComplianceCase.customer_id` / `.settlement_id` / `.onboarding_id` already
uses for exactly this situation — a record that can point at more than one
kind of subject, with no cross-module or not-yet-existent-table referential
integrity mechanism to enforce it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class VerificationResult(AnerModel):
    """One verification check's request and outcome.

    `reviewed_by` / `review_status` are immutable once set (migration
    `onboarding_0006_verif_result`'s `trg_verification_result_field_
    immutability` trigger, reusing the exact `onboarding.
    prevent_field_mutation_when_set()` function `onboarding_0002` already
    created for `onboarding_request` / `ubo_record` / `onboarding_document` /
    `kyb_vendor_result`) — the same "who decided this, once, on the record"
    guarantee `ComplianceCase.resolved_by` carries. See
    `application/verification_service.py::VerificationService.record_review`'s
    docstring for the reasoning and the documented risk of that choice.
    """

    __tablename__ = "verification_result"
    __table_args__ = (
        Index("ix_verification_result_entity", "entity_type", "entity_reference"),
        Index("ix_verification_result_provider_reference", "provider_reference"),
        {"schema": SCHEMA},
    )

    verification_type: Mapped[VerificationType] = mapped_column(
        Enum(VerificationType, name="verification_type_enum", schema=SCHEMA), nullable=False
    )
    entity_type: Mapped[VerificationEntityType] = mapped_column(
        Enum(VerificationEntityType, name="verification_entity_type_enum", schema=SCHEMA),
        nullable=False,
    )
    entity_reference: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[VerificationResultStatus] = mapped_column(
        Enum(VerificationResultStatus, name="verification_result_status_enum", schema=SCHEMA),
        nullable=False,
    )
    risk_level: Mapped[VerificationRiskLevel | None] = mapped_column(
        Enum(VerificationRiskLevel, name="verification_risk_level_enum", schema=SCHEMA),
        nullable=True,
    )

    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # PII / encrypted-at-rest documentation gap — same convention as
    # `onboarding_request.tax_identification_number` and
    # `kyb_vendor_result.raw_vendor_response`. `raw_result` is genuinely
    # sensitive for some verification_types (AML/SANCTIONS/ADVERSE_MEDIA
    # results can contain PII on the subject or related parties): it is
    # flagged here as needing encryption-at-rest via the platform KMS key, not
    # actually enforced yet. No field-level encryption layer or KMS provider
    # exists anywhere in this platform yet — this is the same already-accepted
    # gap, not a new one invented for this table. Stays JSONB rather than a
    # ciphertext string for the same reason `case_evidence_item.evidence_data`
    # does: nothing in this codebase encrypts structured JSON today, and the
    # encrypted form (once a KMS provider exists) is unlikely to still fit
    # JSONB, so this column's type is expected to change together with that
    # work rather than being pre-emptively narrowed now.
    raw_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized_result: Mapped[dict] = mapped_column(JSONB, nullable=False)

    evidence_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Immutable once set — see class docstring.
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_status: Mapped[VerificationReviewStatus | None] = mapped_column(
        Enum(VerificationReviewStatus, name="verification_review_status_enum", schema=SCHEMA),
        nullable=True,
    )
