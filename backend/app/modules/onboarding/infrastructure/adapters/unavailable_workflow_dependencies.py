"""
The onboarding workflow dependency set used where no implementation is configured.

The worker registers the onboarding workflow's activities in every environment, and
activities cannot be built without their dependencies. Until real implementations
of entity verification, screening, risk rating, compliance approval, account
creation, customer-user provisioning and completion notification are wired in, this
is what they are built with: every call raises
:class:`~app.modules.onboarding.exceptions.OnboardingDependencyUnavailableError`,
which the workflow does not retry.

It deliberately does not pretend to succeed. An onboarding that reaches an
unimplemented step fails at that step, visibly, with the request left in the status
it had reached — it is never approved, screened or activated by default.
"""
from __future__ import annotations

from app.modules.onboarding.domain.workflow_dependencies import (
    AccountsCreated,
    CompletionNotificationSent,
    ComplianceApprovalRequested,
    CustomerUserProvisioned,
    DocumentCompleteness,
    EntityVerificationSubmission,
    OnboardingWorkflowDependencies,
    RiskRatingOutcome,
    ScreeningOutcome,
    UboOwnerMapped,
    UboOwnersIdentified,
)
from app.modules.onboarding.exceptions import OnboardingDependencyUnavailableError


class UnavailableOnboardingDependency:
    """Satisfies every onboarding workflow dependency contract; implements none."""

    async def submit(self, onboarding_request_id: str) -> EntityVerificationSubmission:
        raise OnboardingDependencyUnavailableError("entity_verification")

    async def identify_owners(self, onboarding_request_id: str) -> UboOwnersIdentified:
        raise OnboardingDependencyUnavailableError("ubo_mapping")

    async def map_owner(self, onboarding_request_id: str, owner_reference: str) -> UboOwnerMapped:
        raise OnboardingDependencyUnavailableError("ubo_mapping")

    async def check(self, onboarding_request_id: str) -> DocumentCompleteness:
        raise OnboardingDependencyUnavailableError("document_collection")

    async def screen(self, onboarding_request_id: str) -> ScreeningOutcome:
        raise OnboardingDependencyUnavailableError("screening")

    async def rate(self, onboarding_request_id: str) -> RiskRatingOutcome:
        raise OnboardingDependencyUnavailableError("risk_rating")

    async def request_approval(self, onboarding_request_id: str) -> ComplianceApprovalRequested:
        raise OnboardingDependencyUnavailableError("compliance_approval")

    async def create_accounts(self, onboarding_request_id: str) -> AccountsCreated:
        raise OnboardingDependencyUnavailableError("account_creation")

    async def provision_initial_user(self, onboarding_request_id: str) -> CustomerUserProvisioned:
        raise OnboardingDependencyUnavailableError("customer_user_provisioning")

    async def notify_completed(self, onboarding_request_id: str) -> CompletionNotificationSent:
        raise OnboardingDependencyUnavailableError("completion_notification")


def unavailable_onboarding_dependencies() -> OnboardingWorkflowDependencies:
    placeholder = UnavailableOnboardingDependency()
    return OnboardingWorkflowDependencies(
        entity_verifier=placeholder,
        ubo_mapper=placeholder,
        document_checklist=placeholder,
        screener=placeholder,
        risk_rater=placeholder,
        compliance_approver=placeholder,
        account_creator=placeholder,
        customer_user_provisioner=placeholder,
        completion_notifier=placeholder,
    )
