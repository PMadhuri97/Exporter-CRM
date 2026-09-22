import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.cases.domain.entities.enums import EvidenceType
from app.platform.database.models import Base, UUIDPrimaryKeyMixin

SCHEMA = "cases"


class CaseEvidenceItem(UUIDPrimaryKeyMixin, Base):
    """One piece of evidence attached to a case.

    Not built on `AppendOnlyModel`: unlike `case_timeline_event`, this table is
    not wholesale append-only (an analyst may later toggle `is_key_evidence`
    while triaging), so only `added_at` is guarded — by the same column-level
    `prevent_field_mutation_when_set()` trigger that guards
    `compliance_case.created_at` / `.resolved_at` / `.resolved_by`, not by a
    whole-table `prevent_mutation()` trigger.

    `evidence_data` is documented as encrypted-at-rest for the PII-bearing
    evidence types (`PII_BEARING_EVIDENCE_TYPES` in `enums.py`: screening
    results, KYB results, onboarding evidence, travel-rule data, Reactor
    investigations, RXIL buyer ratings, and RXIL insurance certificates). No
    field-level encryption layer or KMS provider exists in
    the platform yet — this is the same gap
    `onboarding_request.tax_identification_number` and
    `kyb_vendor_result.raw_vendor_response` already carry, documented rather
    than silently assumed. The column stays JSONB rather than a ciphertext
    string because nothing in this codebase encrypts it yet; the day a KMS
    provider exists, the encrypted form of structured evidence is unlikely to
    still fit JSONB and this column's type is expected to change with it.
    """

    __tablename__ = "case_evidence_item"
    __table_args__ = (
        Index("ix_case_evidence_item_case_id", "case_id"),
        Index("ix_case_evidence_item_case_type", "case_id", "evidence_type"),
        {"schema": SCHEMA},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.compliance_case.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type_enum", schema=SCHEMA), nullable=False
    )
    source_epic: Mapped[str] = mapped_column(String(100), nullable=False)
    source_reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Encrypted at rest for PII-bearing evidence types. See class docstring.
    evidence_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Immutable once set — see class docstring.
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    is_key_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
