"""
The "next required action" vocabulary for `OnboardingRequestStatus` (Epic 4.1, S7).

**Reconciliation note (combining Epic 4.1 S5/S7/S3-AL-672).** This module was
originally `onboarding_state_machine.py` and also owned the legal-transition
table for `OnboardingRequestStatus` (`LEGAL_TRANSITIONS`, `assert_legal`,
`is_legal`, `IllegalOnboardingTransitionError`). It was built as part of Story
S7, at a time when no Temporal workflow and no transition-validating service
existed anywhere in the codebase for this aggregate.

AL-672 (PR #112, merged to `develop` while S7 was in flight) independently
built the real thing: `domain/policies/onboarding_request_transitions.py`
(`PERMITTED_TRANSITIONS`, `is_permitted`) plus `OnboardingTransitionService`,
a transactional, idempotent, DB-compare-and-set gateway that is now the single
place `onboarding_request.status` is written. That table and this module's
former `LEGAL_TRANSITIONS` were checked edge-by-edge during reconciliation and
found to genuinely disagree in several places (e.g. this module allowed
`SCREENING_COMPLETE -> UNDER_REVIEW` and `UBO_MAPPING_IN_PROGRESS ->
UNDER_REVIEW`, which `onboarding_request_transitions.py` does not; see the
Epic 4.1 combined-branch reconciliation report for the full edge-by-edge diff).
Per this reconciliation's decision, AL-672's table and service are canonical.
This module's transition-legality code was deleted rather than kept
side-by-side, and `OnboardingRequestService.submit_entity_details` — the one
call site that used `assert_legal` — now delegates its status change to
`OnboardingTransitionService` instead.

**What's left here** is `NEXT_REQUIRED_ACTION` / `next_required_action`: a
"what should the customer or the platform do next" vocabulary for the status
API surface (`OnboardingRequestService.get_onboarding_status`). AL-672 has no
equivalent — it is a Temporal workflow, not a REST status endpoint, and has no
need to describe "the next required action" as a string. This mapping is this
Story's own, closed vocabulary (the Epic 4.1 spec names the requirement but
does not enumerate the actions), kept as pure, table-driven data with no
model, repository or session import, same as before.
"""

from __future__ import annotations

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRequestStatus as S,
)

# ── Next-required-action mapping ──────────────────────────────────────────────
#
# S7T1's "get onboarding status" operation must report "the next required
# action" for the current state. The doc names this requirement but does not
# enumerate the action vocabulary, so this table is this Story's own, closed
# vocabulary — one entry per status, covering both customer-facing next steps
# and system/vendor-driven waiting states (the doc's transition table makes
# clear that not every state waits on the customer).
NEXT_REQUIRED_ACTION: dict[S, str] = {
    S.DRAFT: "submit_entity_details",
    S.ENTITY_VERIFICATION_IN_PROGRESS: "await_kyb_vendor_result",
    S.ENTITY_VERIFIED: "await_ubo_mapping_initiation",
    S.UBO_MAPPING_IN_PROGRESS: "submit_ubo_declaration",
    S.UBO_MAPPING_COMPLETE: "await_document_request",
    S.DOCUMENT_COLLECTION_IN_PROGRESS: "submit_required_documents",
    S.DOCUMENT_COLLECTION_COMPLETE: "await_screening",
    S.SCREENING_IN_PROGRESS: "await_screening_result",
    S.SCREENING_COMPLETE: "await_risk_rating",
    S.RISK_RATING_IN_PROGRESS: "await_risk_rating_result",
    S.RISK_RATED: "await_compliance_routing_decision",
    S.PENDING_COMPLIANCE_APPROVAL: "await_compliance_officer_decision",
    S.APPROVED: "await_account_creation",
    S.ACCOUNT_CREATION_IN_PROGRESS: "await_account_creation_completion",
    S.ACTIVE: "none",
    S.REJECTED: "none",
    S.ABANDONED: "restart_onboarding",
    S.UNDER_REVIEW: "await_manual_review_resolution",
}

assert set(NEXT_REQUIRED_ACTION) == set(S), (
    "NEXT_REQUIRED_ACTION must cover every OnboardingRequestStatus member"
)


def next_required_action(status: S) -> str:
    """The next required action for an onboarding currently in `status`."""
    return NEXT_REQUIRED_ACTION[status]


__all__ = [
    "NEXT_REQUIRED_ACTION",
    "next_required_action",
]
