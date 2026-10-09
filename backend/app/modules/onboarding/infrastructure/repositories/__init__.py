from app.modules.onboarding.infrastructure.repositories.applicant_mapping_repository import (
    ApplicantMappingRepository,
)
from app.modules.onboarding.infrastructure.repositories.case_repository import (
    CaseRepository,
    DirectStateMutationError,
)
from app.modules.onboarding.infrastructure.repositories.case_state_transition_repository import (
    CaseStateTransitionRepository,
)
from app.modules.onboarding.infrastructure.repositories.customer_repository import (
    OnboardingCustomerRepository,
)
from app.modules.onboarding.infrastructure.repositories.exporter_activity_repository import (
    ExporterActivityRepository,
)
from app.modules.onboarding.infrastructure.repositories.exporter_contact_repository import (
    ExporterContactRepository,
)
from app.modules.onboarding.infrastructure.repositories.exporter_lifecycle_history_repository import (
    ExporterLifecycleHistoryRepository,
)
from app.modules.onboarding.infrastructure.repositories.exporter_profile_repository import (
    ExporterProfileRepository,
    companies_with_active_primary_contact,
)
from app.modules.onboarding.infrastructure.repositories.kyb_vendor_result_repository import (
    KybVendorResultRepository,
)
from app.modules.onboarding.infrastructure.repositories.kyc_case_repository import KycCaseRepository
from app.modules.onboarding.infrastructure.repositories.onboarding_document_repository import (
    OnboardingDocumentRepository,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_event_repository import (
    OnboardingEventRepository,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_request_repository import (
    OnboardingRequestRepository,
)
from app.modules.onboarding.infrastructure.repositories.person_profile_repository import (
    PersonProfileRepository,
)
from app.modules.onboarding.infrastructure.repositories.ubo_record_repository import (
    UboRecordRepository,
)
from app.modules.onboarding.infrastructure.repositories.verification_repository import (
    VerificationRepository,
)
from app.modules.onboarding.infrastructure.repositories.webhook_event_repository import (
    WebhookEventRepository,
)

__all__ = [
    "ApplicantMappingRepository",
    "CaseRepository",
    "CaseStateTransitionRepository",
    "DirectStateMutationError",
    "ExporterActivityRepository",
    "ExporterContactRepository",
    "ExporterLifecycleHistoryRepository",
    "ExporterProfileRepository",
    "companies_with_active_primary_contact",
    "KybVendorResultRepository",
    "KycCaseRepository",
    "OnboardingCustomerRepository",
    "OnboardingDocumentRepository",
    "OnboardingEventRepository",
    "OnboardingRequestRepository",
    "PersonProfileRepository",
    "UboRecordRepository",
    "VerificationRepository",
    "WebhookEventRepository",
]


# ══════════════════════════════════════════════════════════════════════════════
# Area blocks
#
# This index is shared (architecture §8.1), and several areas add repositories to
# it; appending to the single `__all__` list above would put every change in the
# same hunk. So the tail is cut into one block per area: each area's import **and**
# its `__all__` entry go inside its own block, so two changes to different areas
# never touch the same line.
#
# `__all__ += [...]` rather than more entries in the list above is what makes that
# possible, and an empty list in a block is that block's real content.
#
# Imports below the list are deliberate and are not a style slip — they are what lets
# each area's import and export sit in one block. Ruff's E402 ("module level import
# not at top of file") does not know that, and flags every such import after the
# first, so each one carries an explicit `# noqa: E402` naming this comment.
# ══════════════════════════════════════════════════════════════════════════════

# ── Conversation and follow-ups ──

# ── Conversation gauge ──
__all__ += []

# ── Follow-ups ──
from app.modules.onboarding.infrastructure.repositories.follow_up_completion_repository import (  # noqa: E402
    FollowUpCompletionRepository,
)

__all__ += ["FollowUpCompletionRepository"]

# ── Deals, buyers, storage and documents ──
from app.modules.onboarding.infrastructure.repositories.deal_buyer_repository import (  # noqa: E402
    DealBuyerRepository,
)
from app.modules.onboarding.infrastructure.repositories.deal_repository import (  # noqa: E402
    DealRepository,
)

__all__ += ["DealBuyerRepository", "DealRepository"]
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (  # noqa: E402
    CrmDocumentRepository,
)

__all__ += ["CrmDocumentRepository"]


# ══════════════════════════════════════════════════════════════════════════════
# Compliance blocks
#
# The same cut as the area blocks above. Imports here need `# noqa: E402` for the
# reason given in that header.
# ══════════════════════════════════════════════════════════════════════════════

# ── Background check ──
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E402
    BackgroundCheckDecisionRepository,
)

__all__ += ["BackgroundCheckDecisionRepository"]

# ── Verification and screening ──
from app.modules.onboarding.infrastructure.repositories.verification_review_repository import (  # noqa: E402, E501
    VerificationReviewRepository,
)

__all__ += ["VerificationReviewRepository"]
