from app.modules.onboarding.application.case_service import CaseService
from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.onboarding_query_service import OnboardingQueryService
from app.modules.onboarding.application.onboarding_request_service import (
    OnboardingRequestService,
)
from app.modules.onboarding.application.onboarding_service import OnboardingService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.application.screening_review_service import ScreeningReviewService
from app.modules.onboarding.application.webhook_service import WebhookService

# `OnboardingRequestService` (S7T1) and `OnboardingQueryService` (S7T2) are the
# Epic 4.1 Story S7 services, built against the `OnboardingRequest` aggregate
# (S1 schema). `OnboardingService` above is pre-existing, unrelated
# pre-Epic-4.1 code built against a different case/KYC design (`Customer` /
# the legacy `OnboardingStatus`) — deliberately left untouched. The S7
# services are named distinctly (`OnboardingRequestService`,
# `OnboardingQueryService`) specifically to avoid colliding with
# `OnboardingService`'s name while both remain exported here.
__all__ = [
    "CaseService",
    "ExporterContactActivityService",
    "ExporterProfileService",
    "OnboardingQueryService",
    "OnboardingRequestService",
    "OnboardingService",
    "VerificationService",
    "ScreeningReviewService",
    "WebhookService",
]


# ══════════════════════════════════════════════════════════════════════════════
# Section 9.3 — anchor blocks for Developers 3A and 3B
#
# This index is Developer 1's (architecture §8.1). Three people add services to it —
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
from app.modules.onboarding.application.conversation_service import (  # noqa: E402
    ConversationService,
)

__all__ += ["ConversationService"]

# ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
from app.modules.onboarding.application.follow_up_service import (  # noqa: E402
    FollowUpService,
)

__all__ += ["FollowUpService"]

# ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
# (3B appends here; 3A does not.)
from app.modules.onboarding.application.deal_service import DealService  # noqa: E402

__all__ += ["DealService"]
from app.modules.onboarding.application.document_service import DocumentService  # noqa: E402

__all__ += ["DocumentService"]
