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
# Area blocks
#
# This index is shared (architecture §8.1), and several areas add entities and enums
# to it; appending to the single `__all__` list above would put every change in the
# same hunk. So the tail is cut into one block per area: each area's import **and**
# its `__all__` entry go inside its own block, so two changes to different areas
# never touch the same line.
#
# `__all__ += [...]` rather than more entries in the list above is what makes that
# possible.
#
# Imports below the list are deliberate and are not a style slip — they are what lets
# each area's import and export sit in one block. Ruff's E402 ("module level import
# not at top of file") does not know that, and flags every such import after the
# first, so each one carries an explicit `# noqa: E402` naming this comment.
# ══════════════════════════════════════════════════════════════════════════════

# ── Conversation and follow-ups ──

# ── Conversation gauge ──
from app.modules.onboarding.domain.entities.engagement_enums import (  # noqa: E402
    ExporterConversation,
)

__all__ += ["ExporterConversation"]

# ── Follow-ups ──
from app.modules.onboarding.domain.entities.follow_up_completion import (  # noqa: E402
    FollowUpCompletion,
    FollowUpOutcome,
)

__all__ += ["FollowUpCompletion", "FollowUpOutcome"]

# ── Deals, buyers, storage and documents ──
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
# Which paperwork a deal must have before handover.
from app.modules.onboarding.domain.entities.deal_required_document import (  # noqa: E402
    ANY_DOCUMENT_TYPE,
    DealRequiredDocument,
)

__all__ += ["ANY_DOCUMENT_TYPE", "DealRequiredDocument"]


# ══════════════════════════════════════════════════════════════════════════════
# Compliance blocks
#
# The same cut as the area blocks above. Imports here need `# noqa: E402` for the
# reason given in that header.
# ══════════════════════════════════════════════════════════════════════════════

# ── Background check ──
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

# ── Verification and screening ──
from app.modules.onboarding.domain.entities.verification_review import (  # noqa: E402
    VerificationReview,
)

__all__ += ["VerificationReview"]

# ── Compliance engine: check cycles and maker-checker ──
from app.modules.onboarding.domain.entities.check_cycle import (  # noqa: E402
    CheckCycle,
    CheckCycleKind,
)

__all__ += ["CheckCycle", "CheckCycleKind"]

from app.modules.onboarding.domain.entities.background_check_proposal import (  # noqa: E402
    APPROVAL_MOVES,
    BackgroundCheckProposal,
    BackgroundCheckProposalResolution,
    ProposalOutcome,
)

__all__ += [
    "APPROVAL_MOVES",
    "BackgroundCheckProposal",
    "BackgroundCheckProposalResolution",
    "ProposalOutcome",
]

# Trade history. Imported here so
# the metadata carries the three tables — the ORM drift test and Alembic's autogenerate
# both read this barrel.
from app.modules.onboarding.domain.entities.trade_enums import (  # noqa: E402
    TradePaymentStatus,
    TradeProofStatus,
)
from app.modules.onboarding.domain.entities.trade_invoice import (  # noqa: E402
    TradeInvoice,
    TradeInvoiceOutcome,
)
from app.modules.onboarding.domain.entities.trade_relationship import (  # noqa: E402
    TradeRelationship,
)

__all__ += [
    "TradeInvoice",
    "TradeInvoiceOutcome",
    "TradePaymentStatus",
    "TradeProofStatus",
    "TradeRelationship",
]


# The buyer migration's mapping table.
from app.modules.onboarding.domain.entities.deal_buyer_company_map import (  # noqa: E402
    BuyerMatchRule,
    DealBuyerCompanyMap,
)

__all__ += ["BuyerMatchRule", "DealBuyerCompanyMap"]
