"""`VerificationResult` — the generalized verification-results table.

One row per check ever run — KYC on a director, a bank-account check on an
exporter, a shipment/vessel check, or anything not yet anticipated — through
the `VerificationAdapter` protocol (`workflow_dependencies.py`). This is the
new, broader table the CRM calls for; it is *inspired by*
`kyb_vendor_result.py`'s shape (a vendor name, a vendor reference, a
normalised result, a raw response) but is not built on it and does not
replace it.

`KybVendorResult` is left exactly as it is — unmigrated, still written by
`kyb`'s existing path. This table is additive, for everything
`KybVendorResult` doesn't cover (`KybVendorResult` itself is left untouched).

No foreign keys on the subject
-------------------------------
`entity_reference` is a bare, undecorated UUID: `entity_type` determines which
table it actually points at (exporter_profile, a buyer, a director/UBO record,
an invoice, a vessel, a shipment — several of which don't exist as tables yet
in this checkout). This is the same bare-reference convention
`ComplianceCase.customer_id` / `.settlement_id` / `.onboarding_id` already
uses for exactly this situation — a record that can point at more than one
kind of subject, with no cross-module or not-yet-existent-table referential
integrity mechanism to enforce it. The service validates the subjects that do
exist as tables: an ``EXPORTER`` reference must be a company,
a ``BUYER`` reference must be a ``deal_buyer.id``.

Provenance
----------
``provider`` is stored exactly as the adapter reported it and never rewritten.
``provenance_of`` turns it into an honest label: ``manual`` is a person; the RXIL
stub (``rxil_stub``, and the upper-case ``RXIL`` it reported before that name) is a
**stub**, not RXIL, until the RXIL results contract exists.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    and_,
    or_,
    text,
)
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

#: Stored providers that are a stub, not the provider they are named after. The
#: RXIL stub once reported ``"RXIL"`` and ``"rxil_stub"`` since; both are
#: kept here because stored values are never rewritten.
STUB_PROVIDERS: frozenset[str] = frozenset({"rxil_stub", "RXIL"})
#: Stored providers that mean "a person recorded this".
MANUAL_PROVIDERS: frozenset[str] = frozenset({"manual"})

Provenance = Literal["MANUAL", "STUB", "PROVIDER"]


def provenance_of(provider: str) -> Provenance:
    """An honest label for a stored ``provider`` (verification-and-screening.md §4)."""
    if provider in MANUAL_PROVIDERS:
        return "MANUAL"
    if provider in STUB_PROVIDERS:
        return "STUB"
    return "PROVIDER"


def is_placeholder_result(normalized_result: Any, provider_reference: str | None) -> bool:
    """A placeholder row: ``normalized_result.stub`` is ``true`` and no provider
    reference — what the retired dev generator created. Flagged, never deleted
    (verification-and-screening.md §8); whether it counts as pending is the Clear
    policy's question."""
    return (
        isinstance(normalized_result, dict)
        and normalized_result.get("stub") is True
        and not provider_reference
    )


def subject_company_of(
    entity_type: VerificationEntityType,
    entity_reference: uuid.UUID,
    subject_company_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """The company a result is about: its ``subject_company_id``, or — for a row
    recorded before checks were company-keyed — the ``entity_reference`` of an
    ``EXPORTER`` result. ``None`` for a subject with no company (a legacy deal buyer
    not yet mapped, a director, an invoice …)."""
    if subject_company_id is not None:
        return subject_company_id
    if entity_type == VerificationEntityType.EXPORTER:
        return entity_reference
    return None


class VerificationResult(AnerModel):
    """One verification check's request and outcome.

    Reviews
    -------
    Reviews live in ``verification_review`` (``verification_review.py``), as
    superseding records. **The legacy ``reviewed_by`` / ``review_status``
    columns here are no longer written** by any code path: migration
    ``onboarding_0021_verif_review`` copied each one into the review table as
    that result's first review, so the review table is the one source of "the
    current review". The columns and their immutability trigger
    (``trg_verification_result_field_immutability``, migration 0006) are kept
    — protection is never dropped — and read only as a fallback for a row
    written outside the service.

    Frozen once reviewed
    --------------------
    Once a result has any review, ``status``, ``risk_level``,
    ``normalized_result`` and ``valid_until`` never change:
    ``VerificationService.get_verification_status`` ignores (and logs) a later
    provider answer, and ``trg_verification_result_outcome_freeze`` refuses the
    ``UPDATE`` at the database.

    Evidence and subject snapshot
    -----------------------------
    ``evidence_note`` / ``evidence_refs`` hold what a result rests on, in the
    qualification contract's shape (``{type, ref}``, ``type`` ``document`` —
    a ``crm_document.id`` — or ``url``). ``evidence_reference`` is **retired**:
    no code path ever wrote it and none does now; it stays only so the column
    is not dropped under existing rows. ``subject_snapshot`` is a BUYER's
    identity at record time. Evidence and snapshot are frozen once set
    (``trg_verification_result_input_immutability``).

    Subject company and cycle
    -------------------------
    ``subject_company_id`` is the company a result is *about*, whatever role it plays
    in a deal (``docs/contracts/background-check.md`` §12). Nullable and
    set once, then frozen — ``NULL`` → value is allowed, any later change is refused
    by ``trg_verification_result_input_immutability`` (migration
    ``onboarding_0023_compliance_core``) — so the buyer migration can fill it
    on rows recorded before it existed without being able to re-point a result
    afterwards.

    **Company-keyed checks.** ``VerificationService`` sets it
    on every new company-subject (``EXPORTER``) result — any company, seller or buyer
    alike — to the company itself. A legacy ``BUYER`` result (keyed by
    ``deal_buyer.id``) gets it only when the deal-buyer migration maps its
    buyer to a company. Which company a result is about is read by one rule,
    :func:`subject_company_of` / :func:`about_company`: the stored
    ``subject_company_id``, else — for a legacy row — ``entity_reference`` of an
    ``EXPORTER`` result. No existing row is rewritten to apply it.

    ``cycle_id`` is the check cycle a company-subject result belongs to,
    stamped by ``VerificationService`` when the result is recorded and frozen by the
    same trigger. ``NULL`` on rows recorded before cycles existed reads as the
    company's cycle 1; ``NULL`` on a legacy ``BUYER`` result means "no cycle" (legacy
    deal buyers have no background check).
    """

    __tablename__ = "verification_result"
    __table_args__ = (
        Index("ix_verification_result_entity", "entity_type", "entity_reference"),
        Index("ix_verification_result_provider_reference", "provider_reference"),
        Index(
            "ix_verification_result_entity_recent",
            "entity_type",
            "entity_reference",
            text("performed_at DESC"),
            text("created_at DESC"),
            text("id DESC"),
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_refs) = 'array'",
            name="ck_verification_result_evidence_refs_array",
        ),
        Index(  # 0023
            "ix_verification_result_subject_company_id",
            "subject_company_id",
            postgresql_where=text("subject_company_id IS NOT NULL"),
        ),
        Index(  # 0025
            "ix_verification_result_cycle_id",
            "cycle_id",
            postgresql_where=text("cycle_id IS NOT NULL"),
        ),
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

    #: Retired — never written. See the class docstring.
    evidence_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{"type": "document" | "url", "ref": str}, ...]``
    evidence_refs: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: BUYER subjects only: ``{deal_buyer_id, deal_id, name, country,
    #: registration_number, tax_id}`` as they were when the check was recorded.
    subject_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: The company this result is about. Set once, then frozen. See the
    #: class docstring.
    subject_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_verification_result_subject_company_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    #: The check cycle this result belongs to. Set once, then frozen.
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.check_cycle.id",
            name="fk_verification_result_cycle_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    # Legacy, no longer written — see class docstring. Immutable once set.
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_status: Mapped[VerificationReviewStatus | None] = mapped_column(
        Enum(VerificationReviewStatus, name="verification_review_status_enum", schema=SCHEMA),
        nullable=True,
    )

    @property
    def is_placeholder(self) -> bool:
        return is_placeholder_result(self.normalized_result, self.provider_reference)

    @property
    def provenance(self) -> Provenance:
        return provenance_of(self.provider)

    @property
    def subject_company(self) -> uuid.UUID | None:
        """The company this result is about — :func:`subject_company_of`."""
        return subject_company_of(self.entity_type, self.entity_reference, self.subject_company_id)


def about_company(company_id: uuid.UUID) -> ColumnElement[bool]:
    """SQL for "results about this company" — :func:`subject_company_of` as a query.

    ``subject_company_id = company_id``, or a legacy row (``subject_company_id IS
    NULL``) whose subject is the company itself (``EXPORTER`` / ``entity_reference``).
    Served by ``ix_verification_result_subject_company_id`` and
    ``ix_verification_result_entity``.
    """
    return or_(
        VerificationResult.subject_company_id == company_id,
        and_(
            VerificationResult.subject_company_id.is_(None),
            VerificationResult.entity_type == VerificationEntityType.EXPORTER,
            VerificationResult.entity_reference == company_id,
        ),
    )
