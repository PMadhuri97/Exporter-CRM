from app.modules.onboarding.domain.entities.applicant_mapping import ApplicantMapping
from app.modules.onboarding.domain.entities.case import Case
from app.modules.onboarding.domain.entities.case_state_transition import CaseStateTransition
from app.modules.onboarding.domain.entities.customer import Customer
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.enums import (
    CaseState,
    CaseType,
    OnboardingStatus,
    TransitionSource,
    VerificationStatus,
)
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.qualification import (
    QualificationCriterion,
    QualificationOutcome,
    QualificationReasonCode,
    QualificationResult,
)
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.kyb_vendor_registration import KybVendorRegistration
from app.modules.onboarding.domain.entities.kyb_vendor_result import KybVendorResult
from app.modules.onboarding.domain.entities.kyc_case import KycCase
from app.modules.onboarding.domain.entities.onboarding_document import OnboardingDocument
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent

# S1T1 Orchestration entities
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
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
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.entities.person_profile import PersonProfile
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.domain.entities.verification import Verification
from app.modules.onboarding.domain.entities.screening_review import (
    BankActivityFinding,
    ScreeningReviewItem,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.entities.webhook_event import WebhookEvent

__all__ = [
    "ApplicantMapping",
    "Case",
    "CaseState",
    "CaseStateTransition",
    "CaseType",
    "Customer",
    "KycCase",
    "OnboardingStatus",
    "PersonProfile",
    "TransitionSource",
    "Verification",
    "VerificationStatus",
    "WebhookEvent",
    "OnboardingRequest",
    "UboRecord",
    "OnboardingDocument",
    "OnboardingEvent",
    "KybVendorRegistration",
    "KybVendorResult",
    "OnboardingRequestStatus",
    "OnboardingEntityType",
    "OnboardingRiskRating",
    "OnboardingScreeningResult",
    "OnboardingComplianceDecision",
    "OnboardingRejectionCategory",
    "UboControlType",
    "UboIdentificationType",
    "UboKycResult",
    "UboPepStatus",
    "OnboardingDocumentType",
    "OnboardingValidationStatus",
    "KybNormalisedResult",
    "ExporterProfile",
    "ExporterGstin",
    "ExporterMarker",
    "QualificationCriterion",
    "QualificationOutcome",
    "QualificationReasonCode",
    "QualificationResult",
    "ExporterContact",
    "ExporterActivity",
    "ExporterLifecycleHistory",
    "ExporterSource",
    "ExporterActivityType",
    "VerificationResult",
    "VerificationType",
    "VerificationEntityType",
    "VerificationResultStatus",
    "VerificationRiskLevel",
    "VerificationReviewStatus",
    "ScreeningReviewItem",
    "BankActivityFinding",
]


# ══════════════════════════════════════════════════════════════════════════════
# Section 9.3 — anchor blocks for Developers 3A and 3B
#
# This index is Developer 1's (architecture §8.1). Three people add entities and enums to it —
# 3A in each of its two phases, and 3B — and appending to the single `__all__`
# list above puts all three in the same hunk, every time. So the seam commit cuts
# the tail into owned blocks: each owner's import **and** its `__all__` entry go
# inside its own block, so no two owners ever touch the same line.
#
# `__all__ += [...]` rather than more entries in the list above is what makes that
# possible, and the empty list in each block is the block's real content, so the
# blocks are separated even before anyone has added anything.
#
# Imports below the list are deliberate and are not a style slip — they are what lets
# each owner's import and export sit in one block nobody else touches. Ruff's E402
# ("module level import not at top of file") does not know that, and flags every such
# import after the first, so each one carries an explicit `# noqa: E402` naming this
# comment. **3B: yours needs one too.**
# ══════════════════════════════════════════════════════════════════════════════

# ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ──
# (3A appends here; 3B does not.)
# Cut into the two phase sub-anchors below — phase agreement §6.3.

# ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──
from app.modules.onboarding.domain.entities.engagement_enums import (  # noqa: E402
    ExporterConversation,
)

__all__ += ["ExporterConversation"]

# ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
from app.modules.onboarding.domain.entities.follow_up_completion import (  # noqa: E402
    FollowUpCompletion,
    FollowUpOutcome,
)

__all__ += ["FollowUpCompletion", "FollowUpOutcome"]

# ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
# (3B appends here; 3A does not.)
from app.modules.onboarding.domain.entities.deal import Deal  # noqa: E402
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer  # noqa: E402
from app.modules.onboarding.domain.entities.deal_enums import DealStage  # noqa: E402

__all__ += ["Deal", "DealBuyer", "DealStage"]
from app.modules.onboarding.domain.entities.crm_document import CrmDocument  # noqa: E402
from app.modules.onboarding.domain.entities.document_enums import (  # noqa: E402
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)

__all__ += ["CrmDocument", "DocumentCategory", "DocumentOwnerKind", "DocumentSource"]


# ══════════════════════════════════════════════════════════════════════════════
# Dev4 seam — anchor blocks for Developers 4A and 4B (4B-0; 4a/4b-task.md §9)
#
# The same cut as the §9.3 blocks above, for the two Dev4 pull requests that run
# in parallel: each owner's import **and** its `__all__` entry go inside its own
# block, so the 4A and 4B branches never touch the same line. The empty list in
# each block is the block's real content until its owner adds to it. Imports here
# need `# noqa: E402` for the reason given in the §9.3 header.
# ══════════════════════════════════════════════════════════════════════════════

# ── Background check — owner: Developer 4A ──
# (4A appends here; 4B does not.)
from app.modules.onboarding.domain.entities.background_check_decision import (  # noqa: E402
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.modules.onboarding.domain.entities.background_check_enums import (  # noqa: E402
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)

__all__ += [
    "BackgroundCheckDecidedByKind",
    "BackgroundCheckDecision",
    "BackgroundCheckDecisionSource",
    "BackgroundCheckEvidence",
    "BackgroundCheckEvidenceKind",
    "BackgroundCheckRisk",
    "BackgroundCheckState",
]

# ── Verification and screening — owner: Developer 4B ──
# (4B appends here; 4A does not.)
__all__ += []
