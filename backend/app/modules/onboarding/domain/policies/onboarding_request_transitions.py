"""
The onboarding request lifecycle: which status changes are permitted.

This module is the permitted-transition table for ``OnboardingRequest.status`` and
nothing else. It imports no model, repository or session — it is a pure function of
``(from_status, to_status)``, consulted by ``OnboardingTransitionService`` before any
write. It is deliberately separate from ``state_machine.py``, which governs the KYC
``Case`` lifecycle, a different aggregate with a different vocabulary.

The forward path is one status after another::

    DRAFT → ENTITY_VERIFICATION_IN_PROGRESS → ENTITY_VERIFIED
          → UBO_MAPPING_IN_PROGRESS → UBO_MAPPING_COMPLETE
          → DOCUMENT_COLLECTION_IN_PROGRESS → DOCUMENT_COLLECTION_COMPLETE
          → SCREENING_IN_PROGRESS → SCREENING_COMPLETE
          → RISK_RATING_IN_PROGRESS → RISK_RATED
          → PENDING_COMPLIANCE_APPROVAL → APPROVED
          → ACCOUNT_CREATION_IN_PROGRESS → ACTIVE

Off the forward path, only moves the existing rejection categories give a reason for:

* **Rejection** from the processing status whose outcome can reject the request,
  one per ``OnboardingRejectionCategory`` that names such an outcome — entity
  verification (``KYB_FAILURE``), document collection (``DOCUMENT_FRAUD``),
  screening (``SCREENING_BLOCK``) and compliance approval
  (``COMPLIANCE_REJECTION``).
* **Manual review** of entity verification: a verification that cannot be decided
  automatically parks the request in ``UNDER_REVIEW``, which resolves to verified or
  rejected. No other status enters review.
* **Abandonment** from document collection, the one status in which the request
  waits on the customer rather than on the platform or a vendor.

``ACTIVE``, ``REJECTED`` and ``ABANDONED`` are terminal.

The graph is acyclic, and that is load-bearing: a request passes through each
``(from_status, to_status)`` edge at most once, so the pair identifies the one
transition event it produced. ``OnboardingTransitionService`` relies on this to make
a repeated transition idempotent. A unit test asserts the graph stays acyclic.
"""
from __future__ import annotations

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)

_S = OnboardingRequestStatus

#: from_status → every status the request may move to next. Every status is a key,
#: including the terminal ones, so a missing key is a programming error rather than
#: a silently empty transition set.
PERMITTED_TRANSITIONS: dict[OnboardingRequestStatus, frozenset[OnboardingRequestStatus]] = {
    _S.DRAFT: frozenset({_S.ENTITY_VERIFICATION_IN_PROGRESS}),
    _S.ENTITY_VERIFICATION_IN_PROGRESS: frozenset(
        {_S.ENTITY_VERIFIED, _S.UNDER_REVIEW, _S.REJECTED}
    ),
    _S.UNDER_REVIEW: frozenset({_S.ENTITY_VERIFIED, _S.REJECTED}),
    _S.ENTITY_VERIFIED: frozenset({_S.UBO_MAPPING_IN_PROGRESS}),
    _S.UBO_MAPPING_IN_PROGRESS: frozenset({_S.UBO_MAPPING_COMPLETE}),
    _S.UBO_MAPPING_COMPLETE: frozenset({_S.DOCUMENT_COLLECTION_IN_PROGRESS}),
    _S.DOCUMENT_COLLECTION_IN_PROGRESS: frozenset(
        {_S.DOCUMENT_COLLECTION_COMPLETE, _S.REJECTED, _S.ABANDONED}
    ),
    _S.DOCUMENT_COLLECTION_COMPLETE: frozenset({_S.SCREENING_IN_PROGRESS}),
    _S.SCREENING_IN_PROGRESS: frozenset({_S.SCREENING_COMPLETE, _S.REJECTED}),
    _S.SCREENING_COMPLETE: frozenset({_S.RISK_RATING_IN_PROGRESS}),
    _S.RISK_RATING_IN_PROGRESS: frozenset({_S.RISK_RATED}),
    _S.RISK_RATED: frozenset({_S.PENDING_COMPLIANCE_APPROVAL}),
    _S.PENDING_COMPLIANCE_APPROVAL: frozenset({_S.APPROVED, _S.REJECTED}),
    _S.APPROVED: frozenset({_S.ACCOUNT_CREATION_IN_PROGRESS}),
    _S.ACCOUNT_CREATION_IN_PROGRESS: frozenset({_S.ACTIVE}),
    _S.ACTIVE: frozenset(),
    _S.REJECTED: frozenset(),
    _S.ABANDONED: frozenset(),
}

#: Statuses with no way out.
TERMINAL_STATUSES: frozenset[OnboardingRequestStatus] = frozenset(
    status for status, targets in PERMITTED_TRANSITIONS.items() if not targets
)

#: For each status a request can be rejected from, the rejection categories that
#: describe a rejection there. A rejection must carry one of them, so the persisted
#: category always names the step that actually rejected the request.
REJECTION_CATEGORIES_BY_STATUS: dict[
    OnboardingRequestStatus, frozenset[OnboardingRejectionCategory]
] = {
    _S.ENTITY_VERIFICATION_IN_PROGRESS: frozenset({OnboardingRejectionCategory.KYB_FAILURE}),
    _S.UNDER_REVIEW: frozenset({OnboardingRejectionCategory.KYB_FAILURE}),
    _S.DOCUMENT_COLLECTION_IN_PROGRESS: frozenset(
        {OnboardingRejectionCategory.DOCUMENT_FRAUD}
    ),
    _S.SCREENING_IN_PROGRESS: frozenset({OnboardingRejectionCategory.SCREENING_BLOCK}),
    _S.PENDING_COMPLIANCE_APPROVAL: frozenset(
        {OnboardingRejectionCategory.COMPLIANCE_REJECTION}
    ),
}


def is_permitted(
    from_status: OnboardingRequestStatus, to_status: OnboardingRequestStatus
) -> bool:
    """True when the table allows a request in ``from_status`` to move to ``to_status``."""
    return to_status in PERMITTED_TRANSITIONS[from_status]


def is_permitted_rejection_category(
    from_status: OnboardingRequestStatus, category: OnboardingRejectionCategory
) -> bool:
    """True when ``category`` describes a rejection from ``from_status``."""
    return category in REJECTION_CATEGORIES_BY_STATUS.get(from_status, frozenset())
