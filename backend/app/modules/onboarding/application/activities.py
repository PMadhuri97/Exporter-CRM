"""
Temporal activities for the onboarding workflow.

Every piece of work the onboarding workflow does outside its own state happens here:
lifecycle transitions and customer-activity stamps against PostgreSQL, and one
activity per call to an onboarding dependency. The workflow never touches the
database or a dependency directly.

:class:`OnboardingActivities` is built with an
:class:`~app.modules.onboarding.domain.workflow_dependencies.OnboardingWorkflowDependencies`
set, so the composition root chooses the implementations and tests inject stubs.

Database activities open their own session per attempt, following the settlement
activities: a retried attempt starts from a clean session. Both database writes are
idempotent — the transition service returns the original event for a transition
that already happened, and the activity stamp never moves ``last_activity_at``
backwards — so retries are safe.

Errors are not translated. A domain exception reaches Temporal as an application
error whose type is the exception class name, which is what the workflow's
non-retryable list matches on.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from temporalio import activity

from app.modules.onboarding.application.onboarding_transition_service import (
    STATUS_CHANGED_EVENT_TYPE,
    OnboardingTransitionService,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
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
from app.modules.onboarding.exceptions import OnboardingRequestNotFoundError
from app.modules.onboarding.infrastructure.repositories.onboarding_event_repository import (
    OnboardingEventRepository,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_request_repository import (
    OnboardingRequestRepository,
)
from app.platform.database import services as database
from app.temporal._actor import SYSTEM_ACTOR_ID

#: ``onboarding_event.actor_id`` for transitions the workflow applies.
WORKFLOW_ACTOR_ID = str(SYSTEM_ACTOR_ID)


# ── activity inputs and outputs ───────────────────────────────────────────────


@dataclass(frozen=True)
class OnboardingRequestRef:
    onboarding_request_id: str


@dataclass(frozen=True)
class MapUboOwnerInput:
    onboarding_request_id: str
    owner_reference: str


@dataclass(frozen=True)
class TransitionOnboardingRequestInput:
    onboarding_request_id: str
    expected_status: str
    to_status: str
    #: The workflow's clock at the moment it decided on the transition, so every
    #: attempt stamps the same time.
    occurred_at: datetime
    rejection_category: str | None = None
    # No free-text rejection reason: activity inputs are recorded in workflow
    # history. The category is the orchestration-level outcome; the detail stays
    # with the capability that decided it.
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TransitionOnboardingRequestOutput:
    event_id: str
    already_applied: bool


@dataclass(frozen=True)
class RecordCustomerActivityInput:
    onboarding_request_id: str
    expected_status: str
    occurred_at: datetime


@dataclass(frozen=True)
class PersistedTransition:
    """One ``onboarding_event`` status change, as the workflow reports it. Event
    metadata is left out: it is the event's own record, not orchestration state."""

    event_id: str
    from_status: str
    to_status: str
    occurred_at: datetime


@dataclass(frozen=True)
class OnboardingProgress:
    """Where a request's persisted lifecycle stands. Status values and transition
    references only — nothing from the onboarding record itself."""

    status: str
    rejection_category: str | None = None
    #: Every status change recorded so far, oldest first, so an execution that
    #: resumes still reports the request's whole lifecycle.
    transitions: list[PersistedTransition] = field(default_factory=list)


class OnboardingActivities:
    """The onboarding workflow's activities, bound to one dependency set."""

    def __init__(self, dependencies: OnboardingWorkflowDependencies) -> None:
        self._deps = dependencies

    def activity_methods(self) -> list[Callable[..., Any]]:
        """Every activity, bound to this instance, ready for ``Worker(activities=...)``."""
        return [
            self.load_onboarding_progress,
            self.transition_onboarding_request,
            self.record_customer_activity,
            self.verify_entity,
            self.identify_ubo_owners,
            self.map_ubo_owner,
            self.check_documents,
            self.screen,
            self.rate_risk,
            self.request_compliance_approval,
            self.create_accounts,
            self.provision_initial_user,
            self.notify_completion,
        ]

    # ── lifecycle ────────────────────────────────────────────────────────────

    @activity.defn(name="load_onboarding_progress")
    async def load_onboarding_progress(self, inp: OnboardingRequestRef) -> OnboardingProgress:
        """The request's persisted status and transitions, so an execution continues
        from them."""
        request_id = uuid.UUID(inp.onboarding_request_id)
        async with database.AsyncSessionLocal() as session:
            request = await OnboardingRequestRepository(session).get(request_id)
            if request is None:
                raise OnboardingRequestNotFoundError(inp.onboarding_request_id)
            events = await OnboardingEventRepository(session).list_by_request(request_id)
            return OnboardingProgress(
                transitions=[
                    PersistedTransition(
                        event_id=str(event.id),
                        from_status=event.from_status,
                        to_status=event.to_status,
                        occurred_at=event.created_at,
                    )
                    for event in events
                    if event.event_type == STATUS_CHANGED_EVENT_TYPE
                    and event.from_status is not None
                    and event.to_status is not None
                ],
                status=request.status.value,
                rejection_category=(
                    request.rejection_category.value
                    if request.rejection_category is not None
                    else None
                ),
            )

    @activity.defn(name="transition_onboarding_request")
    async def transition_onboarding_request(
        self, inp: TransitionOnboardingRequestInput
    ) -> TransitionOnboardingRequestOutput:
        async with database.AsyncSessionLocal() as session:
            result = await OnboardingTransitionService(session).transition(
                uuid.UUID(inp.onboarding_request_id),
                expected_status=OnboardingRequestStatus(inp.expected_status),
                to_status=OnboardingRequestStatus(inp.to_status),
                actor_id=WORKFLOW_ACTOR_ID,
                occurred_at=inp.occurred_at,
                rejection_category=(
                    OnboardingRejectionCategory(inp.rejection_category)
                    if inp.rejection_category is not None
                    else None
                ),
                metadata=inp.metadata,
            )
        return TransitionOnboardingRequestOutput(
            event_id=str(result.event_id), already_applied=result.already_applied
        )

    @activity.defn(name="record_onboarding_customer_activity")
    async def record_customer_activity(self, inp: RecordCustomerActivityInput) -> bool:
        async with database.AsyncSessionLocal() as session:
            try:
                recorded = await OnboardingRequestRepository(session).record_activity(
                    uuid.UUID(inp.onboarding_request_id),
                    expected_status=OnboardingRequestStatus(inp.expected_status),
                    occurred_at=inp.occurred_at,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return recorded

    # ── dependencies ─────────────────────────────────────────────────────────

    @activity.defn(name="verify_onboarding_entity")
    async def verify_entity(self, inp: OnboardingRequestRef) -> EntityVerificationSubmission:
        return await self._deps.entity_verifier.submit(inp.onboarding_request_id)

    @activity.defn(name="identify_onboarding_ubo_owners")
    async def identify_ubo_owners(self, inp: OnboardingRequestRef) -> UboOwnersIdentified:
        return await self._deps.ubo_mapper.identify_owners(inp.onboarding_request_id)

    @activity.defn(name="map_onboarding_ubo_owner")
    async def map_ubo_owner(self, inp: MapUboOwnerInput) -> UboOwnerMapped:
        return await self._deps.ubo_mapper.map_owner(
            inp.onboarding_request_id, inp.owner_reference
        )

    @activity.defn(name="check_onboarding_documents")
    async def check_documents(self, inp: OnboardingRequestRef) -> DocumentCompleteness:
        return await self._deps.document_checklist.check(inp.onboarding_request_id)

    @activity.defn(name="screen_onboarding_request")
    async def screen(self, inp: OnboardingRequestRef) -> ScreeningOutcome:
        return await self._deps.screener.screen(inp.onboarding_request_id)

    @activity.defn(name="rate_onboarding_risk")
    async def rate_risk(self, inp: OnboardingRequestRef) -> RiskRatingOutcome:
        return await self._deps.risk_rater.rate(inp.onboarding_request_id)

    @activity.defn(name="request_onboarding_compliance_approval")
    async def request_compliance_approval(
        self, inp: OnboardingRequestRef
    ) -> ComplianceApprovalRequested:
        requested = await self._deps.compliance_approver.request_approval(
            inp.onboarding_request_id
        )
        # The result becomes workflow history. Orchestration needs the approval
        # request id and the decision; compliance's free-text reason stays with it.
        return replace(requested, reason=None)

    @activity.defn(name="create_onboarding_accounts")
    async def create_accounts(self, inp: OnboardingRequestRef) -> AccountsCreated:
        return await self._deps.account_creator.create_accounts(inp.onboarding_request_id)

    @activity.defn(name="provision_onboarding_initial_user")
    async def provision_initial_user(self, inp: OnboardingRequestRef) -> CustomerUserProvisioned:
        return await self._deps.customer_user_provisioner.provision_initial_user(
            inp.onboarding_request_id
        )

    @activity.defn(name="notify_onboarding_completed")
    async def notify_completion(self, inp: OnboardingRequestRef) -> CompletionNotificationSent:
        return await self._deps.completion_notifier.notify_completed(inp.onboarding_request_id)
