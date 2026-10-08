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
from app.modules.onboarding.application.screening_review_service import ScreeningReviewService
from app.modules.onboarding.application.verification_service import VerificationService
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
# Area blocks
#
# This index is shared (architecture §8.1), and several areas add services to it;
# appending to the single `__all__` list above would put every change in the same
# hunk. So the tail is cut into one block per area: each area's import **and** its
# `__all__` entry go inside its own block, so two changes to different areas never
# touch the same line.
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
from app.modules.onboarding.application.conversation_service import (  # noqa: E402
    ConversationService,
)

__all__ += ["ConversationService"]

# ── Follow-ups ──
from app.modules.onboarding.application.follow_up_service import (  # noqa: E402
    FollowUpService,
)

__all__ += ["FollowUpService"]

# ── Deals, buyers, storage and documents ──
from app.modules.onboarding.application.deal_service import DealService  # noqa: E402

__all__ += ["DealService"]
from app.modules.onboarding.application.document_service import DocumentService  # noqa: E402

__all__ += ["DocumentService"]


# ══════════════════════════════════════════════════════════════════════════════
# Compliance blocks
#
# The same cut as the area blocks above. Imports here need `# noqa: E402` for the
# reason given in that header.
# ══════════════════════════════════════════════════════════════════════════════

# ── Background check ──
from app.modules.onboarding.application.background_check_service import (  # noqa: E402
    BackgroundCheckService,
)

__all__ += ["BackgroundCheckService"]

# ── Verification and screening ──
from app.modules.onboarding.application.compliance_inputs import (  # noqa: E402
    ComplianceInputsService,
)

__all__ += ["ComplianceInputsService"]
