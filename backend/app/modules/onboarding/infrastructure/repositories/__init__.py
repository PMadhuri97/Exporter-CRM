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
# Section 9.3 — anchor blocks for Developers 3A and 3B
#
# This index is Developer 1's (architecture §8.1). Three people add repositories to it —
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
__all__ += []

# ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
from app.modules.onboarding.infrastructure.repositories.follow_up_completion_repository import (  # noqa: E402
    FollowUpCompletionRepository,
)

__all__ += ["FollowUpCompletionRepository"]

# ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
# (3B appends here; 3A does not.)
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
