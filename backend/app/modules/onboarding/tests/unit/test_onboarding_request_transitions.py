"""
Onboarding request lifecycle table and transition validation.

Pure tests: no database. The service's persistence behaviour is covered by
``tests/integration/test_onboarding_transition_service.py``.
"""
from itertools import pairwise

import pytest

from app.modules.onboarding.application.onboarding_transition_service import (
    OnboardingTransitionService,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.modules.onboarding.domain.policies.onboarding_request_transitions import (
    PERMITTED_TRANSITIONS,
    REJECTION_CATEGORIES_BY_STATUS,
    TERMINAL_STATUSES,
    is_permitted,
    is_permitted_rejection_category,
)
from app.modules.onboarding.exceptions import OnboardingTransitionNotPermittedError

S = OnboardingRequestStatus
C = OnboardingRejectionCategory

FORWARD_PATH = [
    S.DRAFT,
    S.ENTITY_VERIFICATION_IN_PROGRESS,
    S.ENTITY_VERIFIED,
    S.UBO_MAPPING_IN_PROGRESS,
    S.UBO_MAPPING_COMPLETE,
    S.DOCUMENT_COLLECTION_IN_PROGRESS,
    S.DOCUMENT_COLLECTION_COMPLETE,
    S.SCREENING_IN_PROGRESS,
    S.SCREENING_COMPLETE,
    S.RISK_RATING_IN_PROGRESS,
    S.RISK_RATED,
    S.PENDING_COMPLIANCE_APPROVAL,
    S.APPROVED,
    S.ACCOUNT_CREATION_IN_PROGRESS,
    S.ACTIVE,
]


def test_every_status_has_an_entry():
    assert set(PERMITTED_TRANSITIONS) == set(OnboardingRequestStatus)


def test_every_target_is_a_known_status():
    for targets in PERMITTED_TRANSITIONS.values():
        assert targets <= set(OnboardingRequestStatus)


@pytest.mark.parametrize(("from_status", "to_status"), list(pairwise(FORWARD_PATH)))
def test_forward_path_is_permitted(from_status, to_status):
    assert is_permitted(from_status, to_status)


def test_terminal_statuses():
    assert TERMINAL_STATUSES == {S.ACTIVE, S.REJECTED, S.ABANDONED}


def test_lifecycle_is_acyclic():
    """Transition idempotency identifies an event by its from → to edge, which is
    only sound if no request can cross the same edge twice."""
    visiting: set[OnboardingRequestStatus] = set()
    done: set[OnboardingRequestStatus] = set()

    def visit(status: OnboardingRequestStatus) -> None:
        assert status not in visiting, f"cycle through {status.value}"
        if status in done:
            return
        visiting.add(status)
        for target in PERMITTED_TRANSITIONS[status]:
            visit(target)
        visiting.remove(status)
        done.add(status)

    for status in OnboardingRequestStatus:
        visit(status)


def test_every_status_is_reachable_from_draft():
    reached = {S.DRAFT}
    frontier = [S.DRAFT]
    while frontier:
        for target in PERMITTED_TRANSITIONS[frontier.pop()]:
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(OnboardingRequestStatus)


def test_rejection_is_permitted_only_from_statuses_with_a_rejection_category():
    rejectable = {s for s, targets in PERMITTED_TRANSITIONS.items() if S.REJECTED in targets}
    assert rejectable == set(REJECTION_CATEGORIES_BY_STATUS)
    assert rejectable == {
        S.ENTITY_VERIFICATION_IN_PROGRESS,
        S.UNDER_REVIEW,
        S.DOCUMENT_COLLECTION_IN_PROGRESS,
        S.SCREENING_IN_PROGRESS,
        S.PENDING_COMPLIANCE_APPROVAL,
    }


def test_abandonment_only_while_waiting_on_the_customer():
    abandonable = {s for s, targets in PERMITTED_TRANSITIONS.items() if S.ABANDONED in targets}
    assert abandonable == {S.DOCUMENT_COLLECTION_IN_PROGRESS}


def test_manual_review_is_entered_only_from_entity_verification():
    entering = {s for s, targets in PERMITTED_TRANSITIONS.items() if S.UNDER_REVIEW in targets}
    assert entering == {S.ENTITY_VERIFICATION_IN_PROGRESS}
    assert PERMITTED_TRANSITIONS[S.UNDER_REVIEW] == {S.ENTITY_VERIFIED, S.REJECTED}


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (S.DRAFT, S.ACTIVE),
        (S.DRAFT, S.ENTITY_VERIFIED),
        (S.ENTITY_VERIFIED, S.ENTITY_VERIFICATION_IN_PROGRESS),
        (S.RISK_RATING_IN_PROGRESS, S.REJECTED),
        (S.SCREENING_IN_PROGRESS, S.ABANDONED),
        (S.ACTIVE, S.REJECTED),
        (S.REJECTED, S.DRAFT),
        (S.DRAFT, S.DRAFT),
    ],
)
def test_illegal_transitions_are_not_permitted(from_status, to_status):
    assert not is_permitted(from_status, to_status)


def test_rejection_category_matches_the_step_that_rejects():
    assert is_permitted_rejection_category(S.SCREENING_IN_PROGRESS, C.SCREENING_BLOCK)
    assert not is_permitted_rejection_category(S.SCREENING_IN_PROGRESS, C.KYB_FAILURE)
    assert not is_permitted_rejection_category(S.RISK_RATED, C.COMPLIANCE_REJECTION)


# ── Validation performed before any write ─────────────────────────────────────


def test_validation_rejects_an_unconnected_move():
    with pytest.raises(OnboardingTransitionNotPermittedError) as exc:
        OnboardingTransitionService._validate(S.DRAFT, S.ACTIVE, None, None)
    assert exc.value.status_code == 409
    assert exc.value.error_code == "ONBOARDING_TRANSITION_NOT_PERMITTED"


def test_validation_requires_a_rejection_category():
    with pytest.raises(OnboardingTransitionNotPermittedError):
        OnboardingTransitionService._validate(S.SCREENING_IN_PROGRESS, S.REJECTED, None, None)


def test_validation_rejects_a_category_from_another_step():
    with pytest.raises(OnboardingTransitionNotPermittedError):
        OnboardingTransitionService._validate(
            S.SCREENING_IN_PROGRESS, S.REJECTED, C.COMPLIANCE_REJECTION, None
        )


def test_validation_rejects_rejection_details_on_a_non_rejection():
    with pytest.raises(OnboardingTransitionNotPermittedError):
        OnboardingTransitionService._validate(
            S.SCREENING_IN_PROGRESS, S.SCREENING_COMPLETE, C.SCREENING_BLOCK, None
        )
    with pytest.raises(OnboardingTransitionNotPermittedError):
        OnboardingTransitionService._validate(
            S.SCREENING_IN_PROGRESS, S.SCREENING_COMPLETE, None, "a reason"
        )


def test_validation_accepts_a_valid_rejection():
    OnboardingTransitionService._validate(
        S.PENDING_COMPLIANCE_APPROVAL, S.REJECTED, C.COMPLIANCE_REJECTION, "declined"
    )
