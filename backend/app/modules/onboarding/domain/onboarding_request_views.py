"""Read-model view types for the S7 onboarding service API and query interface.

Pure data structures — no I/O, no session, no platform import — mirroring
`domain/kyb_vendor_selection.py`'s `KybVendorLookupResult` pattern: the
application services in this Story (`OnboardingRequestService`,
`OnboardingQueryService`) assemble these from ORM rows; nothing here reaches
for a database or a role.

**Field-level redaction** (S7T1's "sensitive fields restricted to the
compliance officer role" requirement) is a decision the *service* makes before
constructing `OnboardingDetailView` / `EvidencePackage` — this module only
provides the `sensitive_fields_redacted` flag and accepts `None` for a
redacted field. See `application/onboarding_request_service.py` for why this
is a new pattern in this codebase, not an existing one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingEntityType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingRiskRating,
    OnboardingScreeningResult,
    UboControlType,
    UboIdentificationType,
    UboKycResult,
    UboPepStatus,
)

# ── Sub-resource views ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class UboRecordView:
    id: uuid.UUID
    onboarding_request_id: uuid.UUID
    first_name: str
    last_name: str
    nationality: str | None
    residence_country: str | None
    control_type: UboControlType
    ownership_percentage: Decimal | None
    identification_type: UboIdentificationType | None
    identification_number: str | None
    """`None` either because it was never set, or because it was redacted —
    see `sensitive_fields_redacted` on the containing view."""
    kyc_result: UboKycResult
    pep_status: UboPepStatus | None
    screening_reference_id: uuid.UUID | None


@dataclass(frozen=True)
class OnboardingDocumentView:
    id: uuid.UUID
    onboarding_request_id: uuid.UUID
    document_type: str
    file_name: str
    validation_status: str
    rejection_reason: str | None
    submitted_at: datetime | None


@dataclass(frozen=True)
class OnboardingEventView:
    id: uuid.UUID
    onboarding_request_id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_id: str | None
    event_metadata: dict | None
    created_at: datetime


@dataclass(frozen=True)
class KybVendorResultView:
    id: uuid.UUID
    onboarding_request_id: uuid.UUID
    vendor_name: str
    vendor_reference_id: str | None
    normalised_result: str
    retrieved_at: datetime | None


# ── S7T1 views ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DocumentProgress:
    """Documents required vs. received, for `get_onboarding_status`."""

    required_document_types: tuple[str, ...]
    received: tuple[OnboardingDocumentView, ...]

    @property
    def outstanding_document_types(self) -> tuple[str, ...]:
        """Required types with no VALID document received yet."""
        satisfied = {
            d.document_type
            for d in self.received
            if d.validation_status == "VALID"
        }
        return tuple(t for t in self.required_document_types if t not in satisfied)


@dataclass(frozen=True)
class UboMappingProgress:
    """UBO identification/verification progress, for `get_onboarding_status`."""

    total_ubos: int
    verified_count: int
    pending_count: int
    failed_count: int
    not_started_count: int

    @property
    def complete(self) -> bool:
        return self.total_ubos > 0 and self.verified_count == self.total_ubos


@dataclass(frozen=True)
class OnboardingStatusView:
    """Result of `get_onboarding_status` (S7T1)."""

    onboarding_id: uuid.UUID
    customer_id: uuid.UUID
    status: OnboardingRequestStatus
    next_required_action: str
    documents: DocumentProgress
    ubo_progress: UboMappingProgress
    pending_review_reason: str | None
    """Populated when `status` is REJECTED or UNDER_REVIEW, from
    `rejection_reason`. Both REJECTED and UNDER_REVIEW are entered from the
    S5T1 screening-result transition (see `screening_result_service.py`), not
    from an EDD determination, so `rejection_reason` — not `edd_reason` — is
    the right source here even though `onboarding_request.edd_reason` now
    exists as a real column. See `onboarding_query_service._edd_reason` for
    the place that *does* read `edd_reason` (the pending-approvals/under-review
    query views, S7T2)."""


@dataclass(frozen=True)
class OnboardingDetailView:
    """Result of `get_onboarding_detail` (S7T1)."""

    onboarding_id: uuid.UUID
    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    status: OnboardingRequestStatus
    entity_type: OnboardingEntityType
    legal_name: str
    trading_name: str | None
    # Nullable since onboarding_0007_reg_optional — a bare Lead's
    # OnboardingRequest may not have either yet. `None` here is a genuine
    # "not known yet", never a redaction (unlike tax_identification_number
    # below).
    registration_number: str | None
    tax_identification_number: str | None
    """`None` either because it was never set, or because it was redacted —
    see `sensitive_fields_redacted`."""
    incorporation_country: str
    incorporation_date: object | None
    registered_address: dict | None
    trading_address: dict | None
    industry_code: str | None
    declared_monthly_volume_usd: int | None
    corridor_intent: list | None
    screening_result: OnboardingScreeningResult | None
    ubo_mapping: list | dict | None
    screening_reference_id: uuid.UUID | None
    risk_rating: OnboardingRiskRating | None
    risk_rating_factors: dict | None
    compliance_approval_request_id: uuid.UUID | None
    compliance_decision: OnboardingComplianceDecision | None
    rejection_category: OnboardingRejectionCategory | None
    rejection_reason: str | None
    account_ids: list | None
    initial_user_id: str
    initial_user_roles: list | None
    correlation_id: str | None
    initiated_at: datetime | None
    completed_at: datetime | None
    last_activity_at: datetime | None
    ubo_records: tuple[UboRecordView, ...]
    documents: tuple[OnboardingDocumentView, ...]
    events: tuple[OnboardingEventView, ...]
    vendor_results: tuple[KybVendorResultView, ...]
    sensitive_fields_redacted: bool
    """True when the caller lacked the compliance officer role and
    `tax_identification_number` / each UBO's `identification_number` were
    withheld rather than returned."""


@dataclass(frozen=True)
class OnboardingHistoryEntry:
    onboarding_id: uuid.UUID
    status: OnboardingRequestStatus
    legal_name: str
    initiated_at: datetime | None
    completed_at: datetime | None
    rejection_category: OnboardingRejectionCategory | None


# ── S7T2 views ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PendingApprovalEntry:
    """One row of `get_pending_approvals` (S7T2)."""

    onboarding_id: uuid.UUID
    customer_id: uuid.UUID
    legal_name: str
    risk_rating: OnboardingRiskRating | None
    edd_reason: str | None
    """Approximated from `risk_rating_factors['edd_reason']` when present,
    else `rejection_reason`. The S1 schema has no dedicated `edd_reason`
    column — see `OnboardingStatusView.pending_review_reason` docstring."""
    time_waiting_seconds: float


@dataclass(frozen=True)
class UnderReviewEntry:
    """One row of `get_under_review_onboardings` (S7T2)."""

    onboarding_id: uuid.UUID
    customer_id: uuid.UUID
    legal_name: str
    reason: str | None
    time_in_review_seconds: float


@dataclass(frozen=True)
class EvidencePackage:
    """Result of `get_onboarding_evidence_package` (S7T2)."""

    detail: OnboardingDetailView
    screening_evidence: dict | None
    """Would be fetched from Epic 3.2's get-screening-result API
    (docx: 'the Epic 3.2 screening evidence package (fetched from Epic 3.2's
    get screening result API)'). Epic 3.2 does not exist in this codebase and
    the isolation constraint forbids importing any `app.modules.*` outside
    `onboarding`/`kyb` — always `None` here. See the S7 build report."""


@dataclass(frozen=True)
class OnboardingStatistics:
    """Result of `get_onboarding_statistics` (S7T2)."""

    date_from: datetime
    date_to: datetime
    total: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_risk_rating: dict[str, int] = field(default_factory=dict)
    by_sector: dict[str, int] = field(default_factory=dict)
    by_country: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeInStateMetric:
    """One status's timing distribution, for `get_time_in_state_metrics` (S7T2)."""

    status: OnboardingRequestStatus
    sample_count: int
    average_seconds: float | None
    p95_seconds: float | None


__all__ = [
    "DocumentProgress",
    "EvidencePackage",
    "KybVendorResultView",
    "OnboardingDetailView",
    "OnboardingDocumentView",
    "OnboardingEventView",
    "OnboardingHistoryEntry",
    "OnboardingStatistics",
    "OnboardingStatusView",
    "PendingApprovalEntry",
    "TimeInStateMetric",
    "UboMappingProgress",
    "UboRecordView",
    "UnderReviewEntry",
]
