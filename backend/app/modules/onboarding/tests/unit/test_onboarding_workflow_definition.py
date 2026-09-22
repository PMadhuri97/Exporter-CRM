"""
Onboarding workflow definition checks that need no Temporal server or database:
vocabulary kept in step with the onboarding enums, retry classification, input
validation, activity registration, and the placeholder dependency set.
"""
from __future__ import annotations

import pytest

from app.modules.onboarding.application.activities import OnboardingActivities
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingScreeningResult,
)
from app.modules.onboarding.exceptions import (
    OnboardingDependencyUnavailableError,
    OnboardingRequestNotFoundError,
    OnboardingStatusConflictError,
    OnboardingTransitionNotPermittedError,
)
from app.modules.onboarding.infrastructure.adapters.unavailable_workflow_dependencies import (
    unavailable_onboarding_dependencies,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import stub_dependencies
from app.modules.onboarding.workflows import onboarding_workflow as wf
from app.shared.enums.kyb import NormalisedResult


def _values(cls: type) -> set[str]:
    return {v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str)}


def test_status_strings_match_the_onboarding_request_enum():
    assert _values(wf._Status) == {s.value for s in OnboardingRequestStatus}


def test_terminal_statuses_match_the_lifecycle_table():
    from app.modules.onboarding.domain.policies.onboarding_request_transitions import (
        TERMINAL_STATUSES,
    )

    assert wf.TERMINAL_STATUSES == {s.value for s in TERMINAL_STATUSES}


def test_rejection_categories_and_outcomes_are_existing_enum_values():
    assert _values(wf._RejectionCategory) <= {c.value for c in OnboardingRejectionCategory}
    kyb = wf._KYB_VERIFIED | wf._KYB_REJECTED | wf._KYB_NEEDS_REVIEW | {wf._KYB_PENDING}
    assert kyb == {r.value for r in NormalisedResult}
    assert wf._SCREENING_HARD_BLOCK in {r.value for r in OnboardingScreeningResult}
    assert {wf._COMPLIANCE_APPROVED, wf._COMPLIANCE_REJECTED} == {
        d.value for d in OnboardingComplianceDecision
    }


def test_non_retryable_errors_are_the_deterministic_domain_errors():
    assert set(wf.NON_RETRYABLE_ERROR_TYPES) == {
        OnboardingTransitionNotPermittedError.__name__,
        OnboardingStatusConflictError.__name__,
        OnboardingRequestNotFoundError.__name__,
        OnboardingDependencyUnavailableError.__name__,
    }


def test_default_inactivity_timeout_is_thirty_days():
    assert wf.DEFAULT_INACTIVITY_TIMEOUT_SECONDS == 30 * 24 * 60 * 60
    assert wf.OnboardingWorkflowInput("r").inactivity_timeout_seconds == 30 * 24 * 60 * 60


def test_default_inactivity_setting_is_thirty_days():
    from app.platform.configuration.config import Settings

    assert Settings.model_fields["ONBOARDING_INACTIVITY_TIMEOUT_DAYS"].default == 30


@pytest.mark.parametrize(
    "overrides",
    [
        {"inactivity_timeout_seconds": 0},
        {"retry_max_attempts": 0},
        {"retry_initial_interval_seconds": 0},
    ],
)
def test_workflow_input_rejects_invalid_settings(overrides):
    with pytest.raises(ValueError):
        wf.OnboardingWorkflowInput("request", **overrides)


def test_workflow_id_is_derived_from_the_request():
    assert wf.workflow_id_for("abc") == "onboarding-abc"


def test_resume_step_is_defined_for_exactly_the_non_terminal_statuses():
    non_terminal = {s.value for s in OnboardingRequestStatus} - wf.TERMINAL_STATUSES
    assert set(wf.RESUME_STEP_BY_STATUS) == non_terminal


def test_resume_step_never_goes_backwards_along_the_lifecycle():
    """A later status never resumes at an earlier step than a status before it, so a
    resumed execution cannot repeat a step the request has already moved past."""
    from itertools import pairwise

    from app.modules.onboarding.domain.policies.onboarding_request_transitions import (
        PERMITTED_TRANSITIONS,
    )

    for from_status, targets in PERMITTED_TRANSITIONS.items():
        for to_status in targets:
            if to_status.value in wf.TERMINAL_STATUSES:
                continue
            assert (
                wf.RESUME_STEP_BY_STATUS[to_status.value]
                >= wf.RESUME_STEP_BY_STATUS[from_status.value]
            ), (from_status.value, to_status.value)

    steps = [wf.RESUME_STEP_BY_STATUS[s] for s in sorted(wf.RESUME_STEP_BY_STATUS)]
    assert min(steps) == 0 and max(steps) == 6
    assert all(b - a <= 1 for a, b in pairwise(sorted(set(steps))))


def test_compliance_decision_signal_carries_no_free_text():
    from dataclasses import fields

    from app.modules.onboarding.application.activities import TransitionOnboardingRequestInput
    from app.modules.onboarding.domain.workflow_dependencies import ComplianceDecisionReceived

    assert {f.name for f in fields(ComplianceDecisionReceived)} == {
        "onboarding_request_id",
        "approval_request_id",
        "decision",
    }
    assert "rejection_reason" not in {f.name for f in fields(TransitionOnboardingRequestInput)}


def test_every_activity_is_registered_once_under_a_distinct_name():
    methods = OnboardingActivities(stub_dependencies()).activity_methods()
    names = [m.__temporal_activity_definition.name for m in methods]  # type: ignore[attr-defined]

    assert len(names) == len(set(names)) == 13
    declared = {
        name
        for name, member in vars(OnboardingActivities).items()
        if hasattr(member, "__temporal_activity_definition")
    }
    assert {m.__name__ for m in methods} == declared


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("submit", ("r",)),
        ("identify_owners", ("r",)),
        ("map_owner", ("r", "owner")),
        ("check", ("r",)),
        ("screen", ("r",)),
        ("rate", ("r",)),
        ("request_approval", ("r",)),
        ("create_accounts", ("r",)),
        ("provision_initial_user", ("r",)),
        ("notify_completed", ("r",)),
    ],
)
async def test_unavailable_dependencies_refuse_with_a_non_retryable_error(method, args):
    deps = unavailable_onboarding_dependencies()
    placeholder = deps.entity_verifier

    with pytest.raises(OnboardingDependencyUnavailableError) as exc:
        await getattr(placeholder, method)(*args)
    assert type(exc.value).__name__ in wf.NON_RETRYABLE_ERROR_TYPES
