"""Onboarding — public facade.

Exports the legacy identity-provider port so that the Sumsub vendor client in
integrations/ can implement it without reaching into this module's internals.
See MIGRATION_REPORT.md finding F9.

Also exports the document requirements policy service so a cross-module consumer
(Story S4) imports it from ``app.modules.onboarding`` rather than reaching into
``app.modules.onboarding.domain.policies``.

Also exports the risk rating calculation policy (S5T2) for the same reason —
``RiskRatingService`` and ``RiskRatingResult`` are pure (no filesystem, no
database, no other Epic), so they belong on the facade alongside
``DocumentRequirementsService``.

Also exports the KYB vendor registry's domain types (S1T4): the persisted
registration entity, the lookup result, and the manual-review normalised-result
constant. The ``KybVendorRegistryService`` itself is imported directly from
``app.modules.onboarding.application.kyb_vendor_registry_service`` — the package
facade deliberately imports nothing from ``application`` to stay clear of the
``application`` → ``api`` import chain that a bare ``import`` of any onboarding
submodule would otherwise pull in.

Also exports the Epic 4.1 Story S7 orchestration vocabulary and read-model view
types: the ``OnboardingRequestStatus`` state enum and the other
``orchestration_enums`` members, plus the ``onboarding_request_views`` dataclasses
returned by ``OnboardingRequestService`` (S7T1) and ``OnboardingQueryService``
(S7T2). Epic 4.3 and Epic 5.6 are S7T2's documented consumers and need these
types to interpret what the query interface returns (a status, a risk rating, a
document type, an ``OnboardingStatusView``, ...) without reaching into
``domain.entities`` or ``domain.onboarding_request_views`` directly. Per the same
rule as ``KybVendorRegistryService`` above, ``OnboardingRequestService`` and
``OnboardingQueryService`` themselves are imported directly from
``app.modules.onboarding.application.onboarding_request_service`` /
``.onboarding_query_service`` — not from this facade.
"""
from app.modules.onboarding.domain.entities.kyb_vendor_registration import KybVendorRegistration
from app.modules.onboarding.domain.entities.orchestration_enums import (
    KybNormalisedResult,
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingEntityType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingRiskRating,
    OnboardingScreeningResult,
    OnboardingValidationStatus,
    UboControlType,
    UboIdentificationType,
    UboKycResult,
    UboPepStatus,
)
from app.modules.onboarding.domain.kyb_vendor_selection import (
    MANUAL_REVIEW_NORMALISED_RESULT,
    KybVendorLookupResult,
)
from app.modules.onboarding.domain.onboarding_request_views import (
    DocumentProgress,
    EvidencePackage,
    KybVendorResultView,
    OnboardingDetailView,
    OnboardingDocumentView,
    OnboardingEventView,
    OnboardingHistoryEntry,
    OnboardingStatistics,
    OnboardingStatusView,
    PendingApprovalEntry,
    TimeInStateMetric,
    UboMappingProgress,
    UboRecordView,
    UnderReviewEntry,
)
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.domain.policies.risk_rating_service import (
    RiskRatingResult,
    RiskRatingService,
)
from app.modules.onboarding.domain.ports_legacy import (
    ApplicantResult,
    BaseIdentityProvider,
    SdkTokenResult,
    WebhookParseResult,
)

__all__ = [
    "MANUAL_REVIEW_NORMALISED_RESULT",
    "ApplicantResult",
    "BaseIdentityProvider",
    "DocumentProgress",
    "DocumentRequirementsService",
    "EvidencePackage",
    "KybNormalisedResult",
    "KybVendorLookupResult",
    "KybVendorRegistration",
    "KybVendorResultView",
    "OnboardingComplianceDecision",
    "OnboardingDetailView",
    "OnboardingDocumentType",
    "OnboardingDocumentView",
    "OnboardingEntityType",
    "OnboardingEventView",
    "OnboardingHistoryEntry",
    "OnboardingRejectionCategory",
    "OnboardingRequestStatus",
    "OnboardingRiskRating",
    "OnboardingScreeningResult",
    "OnboardingStatistics",
    "OnboardingStatusView",
    "OnboardingValidationStatus",
    "PendingApprovalEntry",
    "RiskRatingResult",
    "RiskRatingService",
    "SdkTokenResult",
    "TimeInStateMetric",
    "UboControlType",
    "UboIdentificationType",
    "UboKycResult",
    "UboMappingProgress",
    "UboPepStatus",
    "UboRecordView",
    "UnderReviewEntry",
    "WebhookParseResult",
]
