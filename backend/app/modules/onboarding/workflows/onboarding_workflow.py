"""
OnboardingWorkflow — durable orchestration of one onboarding request, DRAFT to ACTIVE.

The workflow decides *what happens next*; it does nothing itself. Every status change
goes through the ``transition_onboarding_request`` activity (and so through
``OnboardingTransitionService``), and every business capability is an activity
calling an onboarding workflow dependency. The workflow holds only references and
outcomes — never the onboarding record, personal data or ORM objects.

Steps, in order:

1. **Entity verification.** Submit; a verified entity continues, a rejected or
   not-found entity is rejected (``KYB_FAILURE``). ``PENDING`` waits on the
   verification provider for a ``kyb_result_received`` signal. An outcome needing
   manual review, or one the provider cannot support, moves the request to
   ``UNDER_REVIEW`` and waits for the reviewed result on the same signal.
2. **UBO mapping.** Identify the owners, then map each one in turn.
3. **Document collection.** Ask whether the required documents are present; if not,
   wait on the customer for ``document_submitted`` signals and ask again after each
   new document. This is the only step that waits on the customer, and the only one
   the inactivity timeout applies to: no customer action for the configured period
   abandons the request.
4. **Screening.** A hard block rejects (``SCREENING_BLOCK``). A clear result or a
   result requiring review both continue: review is what compliance approval is for,
   and the screening result travels on the transition event for it to see.
5. **Risk rating.**
6. **Compliance approval.** Raise the approval request; take its immediate decision,
   or wait for a ``compliance_decision_received`` signal. A rejection rejects
   (``COMPLIANCE_REJECTION``).
7. **Account creation**, 8. **user provisioning** — both inside
   ``ACCOUNT_CREATION_IN_PROGRESS`` — then ``ACTIVE``.
9. **Completion notification**, once the request is active.

Determinism: no clock but ``workflow.now()``, no configuration reads (retry and
timeout settings arrive in :class:`OnboardingWorkflowInput`), no I/O, no random ids.

Failures: a business outcome (rejection, hard block, declined approval) is data and
is never retried. An activity that raises is retried with the input's retry policy,
except for the error types in :data:`NON_RETRYABLE_ERROR_TYPES`, which are
deterministic. An activity that exhausts its retries fails the workflow with the
request left in the status it had reached.

Resuming: every execution starts by reading the request's persisted status and
continues from there (see :data:`RESUME_STEP_BY_STATUS`), so starting the workflow
again after a failure picks up where the request stands instead of conflicting at
``DRAFT``. Completed steps are not repeated; the step the request was in is re-run,
relying on idempotent dependencies and on transitions never being applied twice. A
request that has already ended is returned as it is. The transitions earlier
executions recorded are loaded too, so ``onboarding_detail`` always lists every
event of the request.

Compliance text: decisions travel as structured values only. No free-text
rejection reason enters workflow state, signals, activity inputs or results.

Signals are correlated before they are believed: an answer is accepted only if it
names this request and the reference the workflow is waiting on. An answer that
arrives before the workflow knows that reference is held and checked once it does.
Duplicates are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.modules.onboarding.application.activities import (
        MapUboOwnerInput,
        OnboardingActivities,
        OnboardingProgress,
        OnboardingRequestRef,
        RecordCustomerActivityInput,
        TransitionOnboardingRequestInput,
    )
    from app.modules.onboarding.domain.workflow_dependencies import (
        ComplianceApprovalRequested,
        ComplianceDecisionReceived,
        DocumentSubmitted,
        EntityVerificationSubmission,
        KybResultReceived,
    )
    from app.modules.onboarding.exceptions import (
        OnboardingDependencyUnavailableError,
        OnboardingRequestNotFoundError,
        OnboardingStatusConflictError,
        OnboardingTransitionNotPermittedError,
    )

WORKFLOW_NAME = "OnboardingWorkflow"
DEFAULT_INACTIVITY_TIMEOUT_SECONDS = int(timedelta(days=30).total_seconds())


def workflow_id_for(onboarding_request_id: str) -> str:
    """The one workflow id an onboarding request runs under."""
    return f"onboarding-{onboarding_request_id}"


# ── statuses and outcomes, as plain strings ───────────────────────────────────
# Mirrored from OnboardingRequestStatus and the other onboarding enums so workflow
# state and history hold plain values. A unit test keeps them in step with the enums.


class _Status:
    DRAFT = "DRAFT"
    ENTITY_VERIFICATION_IN_PROGRESS = "ENTITY_VERIFICATION_IN_PROGRESS"
    ENTITY_VERIFIED = "ENTITY_VERIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UBO_MAPPING_IN_PROGRESS = "UBO_MAPPING_IN_PROGRESS"
    UBO_MAPPING_COMPLETE = "UBO_MAPPING_COMPLETE"
    DOCUMENT_COLLECTION_IN_PROGRESS = "DOCUMENT_COLLECTION_IN_PROGRESS"
    DOCUMENT_COLLECTION_COMPLETE = "DOCUMENT_COLLECTION_COMPLETE"
    SCREENING_IN_PROGRESS = "SCREENING_IN_PROGRESS"
    SCREENING_COMPLETE = "SCREENING_COMPLETE"
    RISK_RATING_IN_PROGRESS = "RISK_RATING_IN_PROGRESS"
    RISK_RATED = "RISK_RATED"
    PENDING_COMPLIANCE_APPROVAL = "PENDING_COMPLIANCE_APPROVAL"
    APPROVED = "APPROVED"
    ACCOUNT_CREATION_IN_PROGRESS = "ACCOUNT_CREATION_IN_PROGRESS"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


TERMINAL_STATUSES = frozenset({_Status.ACTIVE, _Status.REJECTED, _Status.ABANDONED})

#: For every non-terminal status, the step an execution starts at when it finds the
#: request already there — an index into the step order in ``run``. A completed
#: status (``ENTITY_VERIFIED``) starts at the next step; an in-progress status
#: (``UBO_MAPPING_IN_PROGRESS``) starts at its own step, which is re-run because a
#: persisted in-progress status does not prove the step's work finished. Every
#: dependency call is idempotent per request, and a step does not re-apply the
#: transition into a status the request already holds, so re-running the current
#: step repeats no event. A unit test keeps this covering every non-terminal status.
RESUME_STEP_BY_STATUS: dict[str, int] = {
    _Status.DRAFT: 0,
    _Status.ENTITY_VERIFICATION_IN_PROGRESS: 0,
    _Status.UNDER_REVIEW: 0,
    _Status.ENTITY_VERIFIED: 1,
    _Status.UBO_MAPPING_IN_PROGRESS: 1,
    _Status.UBO_MAPPING_COMPLETE: 2,
    _Status.DOCUMENT_COLLECTION_IN_PROGRESS: 2,
    _Status.DOCUMENT_COLLECTION_COMPLETE: 3,
    _Status.SCREENING_IN_PROGRESS: 3,
    _Status.SCREENING_COMPLETE: 4,
    _Status.RISK_RATING_IN_PROGRESS: 4,
    _Status.RISK_RATED: 5,
    _Status.PENDING_COMPLIANCE_APPROVAL: 5,
    _Status.APPROVED: 6,
    _Status.ACCOUNT_CREATION_IN_PROGRESS: 6,
}


class _RejectionCategory:
    KYB_FAILURE = "KYB_FAILURE"
    SCREENING_BLOCK = "SCREENING_BLOCK"
    COMPLIANCE_REJECTION = "COMPLIANCE_REJECTION"


#: Entity verification outcomes (``NormalisedResult`` values) by what they mean here.
_KYB_VERIFIED = frozenset({"VERIFIED"})
_KYB_REJECTED = frozenset({"REJECTED", "NOT_FOUND"})
_KYB_NEEDS_REVIEW = frozenset({"REQUIRES_MANUAL_REVIEW", "NOT_SUPPORTED"})
_KYB_PENDING = "PENDING"

_SCREENING_HARD_BLOCK = "HARD_BLOCK"
_COMPLIANCE_APPROVED = "APPROVED"
_COMPLIANCE_REJECTED = "REJECTED"


class WaitingOn:
    """Who the onboarding is waiting on, as reported by ``current_status``."""

    PLATFORM = "platform"
    ENTITY_VERIFICATION_PROVIDER = "entity_verification_provider"
    MANUAL_REVIEW = "manual_review"
    CUSTOMER = "customer"
    COMPLIANCE = "compliance"


class CustomerAction:
    SUBMIT_DOCUMENTS = "submit_documents"


#: Error types (exception class names) retrying cannot fix. Derived from the classes
#: so a rename cannot silently empty the list.
NON_RETRYABLE_ERROR_TYPES: list[str] = [
    OnboardingTransitionNotPermittedError.__name__,
    OnboardingStatusConflictError.__name__,
    OnboardingRequestNotFoundError.__name__,
    OnboardingDependencyUnavailableError.__name__,
]

_TRANSITION_TIMEOUT = timedelta(seconds=30)
_DEPENDENCY_TIMEOUT = timedelta(seconds=60)


# ── input, result and query views ─────────────────────────────────────────────


@dataclass
class OnboardingWorkflowInput:
    onboarding_request_id: str
    inactivity_timeout_seconds: int = DEFAULT_INACTIVITY_TIMEOUT_SECONDS
    retry_max_attempts: int = 3
    retry_initial_interval_seconds: int = 1

    def __post_init__(self) -> None:
        if self.inactivity_timeout_seconds <= 0:
            raise ValueError("inactivity_timeout_seconds must be > 0")
        if self.retry_max_attempts < 1:
            raise ValueError("retry_max_attempts must be >= 1")
        if self.retry_initial_interval_seconds < 1:
            raise ValueError("retry_initial_interval_seconds must be >= 1")


@dataclass
class OnboardingWorkflowResult:
    onboarding_request_id: str
    final_status: str
    rejection_category: str | None = None


@dataclass
class OnboardingStatusView:
    status: str
    #: A :class:`WaitingOn` value, or None once the onboarding has ended.
    waiting_on: str | None
    #: A :class:`CustomerAction` value when the customer must act, else None.
    next_customer_action: str | None
    missing_document_types: list[str] = field(default_factory=list)


@dataclass
class OnboardingTransitionView:
    """One recorded status change. ``occurred_at`` is the workflow's clock for a
    transition this execution applied, and the event's recorded time for one an
    earlier execution applied."""

    from_status: str
    to_status: str
    occurred_at: str
    event_id: str


@dataclass
class OnboardingDetailView:
    """References and outcomes only. The onboarding record itself — names,
    addresses, identifiers — stays in PostgreSQL and is never held here."""

    onboarding_request_id: str
    status: str
    waiting_on: str | None
    rejection_category: str | None
    entity_verification_vendor_id: str | None
    entity_verification_reference: str | None
    entity_verification_outcome: str | None
    ubo_owner_references: list[str]
    ubo_owners_mapped: int
    received_document_ids: list[str]
    missing_document_types: list[str]
    last_customer_activity_at: str | None
    inactivity_deadline: str | None
    screening_reference: str | None
    screening_result: str | None
    risk_rating_reference: str | None
    risk_rating: str | None
    compliance_approval_request_id: str | None
    compliance_decision: str | None
    account_ids: list[str]
    user_reference: str | None
    completion_notification_reference: str | None
    transitions: list[OnboardingTransitionView]


class _OnboardingEndedError(Exception):
    """Internal: the onboarding reached a terminal status before the final step."""


@workflow.defn(name=WORKFLOW_NAME)
class OnboardingWorkflow:
    # Built from the input, not in run(): a signal delivered in the same activation
    # as the start is handled before run() begins, and must already know which
    # request this workflow is for.
    @workflow.init
    def __init__(self, inp: OnboardingWorkflowInput) -> None:
        self._request_id: str = inp.onboarding_request_id
        self._status: str = _Status.DRAFT
        self._waiting_on: str | None = WaitingOn.PLATFORM
        self._rejection_category: str | None = None
        self._transitions: list[OnboardingTransitionView] = []
        self._inactivity_timeout = timedelta(seconds=inp.inactivity_timeout_seconds)
        self._retry = RetryPolicy(
            maximum_attempts=inp.retry_max_attempts,
            initial_interval=timedelta(seconds=inp.retry_initial_interval_seconds),
            backoff_coefficient=2.0,
            non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
        )

        # Entity verification
        self._kyb_submission: EntityVerificationSubmission | None = None
        self._kyb_outcome: str | None = None
        self._kyb_resolved = False
        self._kyb_early: list[KybResultReceived] = []
        self._kyb_answers: list[str] = []

        # UBO mapping
        self._ubo_owner_references: list[str] = []
        self._ubo_owners_mapped = 0

        # Document collection
        self._documents_seen: set[str] = set()
        self._received_document_ids: list[str] = []
        self._unprocessed_document_ids: list[str] = []
        self._missing_document_types: list[str] = []
        self._collecting_since: datetime | None = None
        self._last_customer_activity_at: datetime | None = None

        # Screening and risk
        self._screening_reference: str | None = None
        self._screening_result: str | None = None
        self._risk_rating_reference: str | None = None
        self._risk_rating: str | None = None

        # Compliance approval
        self._approval: ComplianceApprovalRequested | None = None
        self._compliance_resolved = False
        self._compliance_early: list[ComplianceDecisionReceived] = []
        self._compliance_answers: list[ComplianceDecisionReceived] = []
        self._compliance_decision: str | None = None

        # Activation
        self._account_ids: list[str] = []
        self._user_reference: str | None = None
        self._notification_reference: str | None = None

    # ── queries ──────────────────────────────────────────────────────────────

    @workflow.query(name="current_status")
    def current_status(self) -> OnboardingStatusView:
        waiting_on_customer = self._waiting_on == WaitingOn.CUSTOMER
        return OnboardingStatusView(
            status=self._status,
            waiting_on=self._waiting_on,
            next_customer_action=CustomerAction.SUBMIT_DOCUMENTS if waiting_on_customer else None,
            missing_document_types=list(self._missing_document_types) if waiting_on_customer else [],
        )

    @workflow.query(name="onboarding_detail")
    def onboarding_detail(self) -> OnboardingDetailView:
        deadline = self._inactivity_deadline()
        return OnboardingDetailView(
            onboarding_request_id=self._request_id,
            status=self._status,
            waiting_on=self._waiting_on,
            rejection_category=self._rejection_category,
            entity_verification_vendor_id=(
                self._kyb_submission.vendor_id if self._kyb_submission else None
            ),
            entity_verification_reference=(
                self._kyb_submission.vendor_reference if self._kyb_submission else None
            ),
            entity_verification_outcome=self._kyb_outcome,
            ubo_owner_references=list(self._ubo_owner_references),
            ubo_owners_mapped=self._ubo_owners_mapped,
            received_document_ids=list(self._received_document_ids),
            missing_document_types=list(self._missing_document_types),
            last_customer_activity_at=_iso(self._last_customer_activity_at),
            inactivity_deadline=(
                _iso(deadline) if self._waiting_on == WaitingOn.CUSTOMER else None
            ),
            screening_reference=self._screening_reference,
            screening_result=self._screening_result,
            risk_rating_reference=self._risk_rating_reference,
            risk_rating=self._risk_rating,
            compliance_approval_request_id=(
                self._approval.approval_request_id if self._approval else None
            ),
            compliance_decision=self._compliance_decision,
            account_ids=list(self._account_ids),
            user_reference=self._user_reference,
            completion_notification_reference=self._notification_reference,
            transitions=list(self._transitions),
        )

    # ── signals ──────────────────────────────────────────────────────────────

    @workflow.signal(name="document_submitted")
    def document_submitted(self, payload: DocumentSubmitted) -> None:
        if not payload.is_for(self._request_id):
            workflow.logger.warning("document_submitted ignored: another onboarding request")
            return
        if self._status in TERMINAL_STATUSES:
            workflow.logger.info("document_submitted ignored: onboarding has ended")
            return
        if payload.document_id in self._documents_seen:
            workflow.logger.info("document_submitted ignored: duplicate document")
            return
        # Accepted at any point before the onboarding ends. Documents sent before
        # collection starts are held and taken into account when it does.
        self._documents_seen.add(payload.document_id)
        self._received_document_ids.append(payload.document_id)
        self._unprocessed_document_ids.append(payload.document_id)
        self._last_customer_activity_at = workflow.now()

    @workflow.signal(name="kyb_result_received")
    def kyb_result_received(self, payload: KybResultReceived) -> None:
        if payload.onboarding_request_id != self._request_id:
            workflow.logger.warning("kyb_result_received ignored: another onboarding request")
            return
        if self._kyb_resolved:
            workflow.logger.info("kyb_result_received ignored: verification already resolved")
            return
        if self._kyb_submission is None:
            self._kyb_early.append(payload)
            return
        self._accept_kyb_result(payload)

    @workflow.signal(name="compliance_decision_received")
    def compliance_decision_received(self, payload: ComplianceDecisionReceived) -> None:
        if payload.onboarding_request_id != self._request_id:
            workflow.logger.warning(
                "compliance_decision_received ignored: another onboarding request"
            )
            return
        if self._compliance_resolved:
            workflow.logger.info("compliance_decision_received ignored: already decided")
            return
        if self._approval is None:
            self._compliance_early.append(payload)
            return
        self._accept_compliance_decision(payload)

    def _accept_kyb_result(self, payload: KybResultReceived) -> None:
        assert self._kyb_submission is not None
        if not payload.answers(self._request_id, self._kyb_submission):
            workflow.logger.warning(
                "kyb_result_received ignored: not for the active verification",
                extra={"vendor_reference": payload.vendor_reference},
            )
            return
        if payload.outcome == _KYB_PENDING:
            return
        self._kyb_answers.append(payload.outcome)

    def _accept_compliance_decision(self, payload: ComplianceDecisionReceived) -> None:
        assert self._approval is not None
        if not payload.answers(self._request_id, self._approval):
            workflow.logger.warning(
                "compliance_decision_received ignored: not for the active approval request",
                extra={"approval_request_id": payload.approval_request_id},
            )
            return
        self._compliance_answers.append(payload)

    # ── run ──────────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, inp: OnboardingWorkflowInput) -> OnboardingWorkflowResult:
        # Start from the request's persisted status, not from DRAFT: an earlier
        # execution may have progressed it and then failed. A request that has
        # already ended is reported as it is and nothing is run.
        progress: OnboardingProgress = await self._call(
            OnboardingActivities.load_onboarding_progress,
            OnboardingRequestRef(self._request_id),
            timeout=_TRANSITION_TIMEOUT,
        )
        self._status = progress.status
        self._rejection_category = progress.rejection_category
        self._transitions = [
            OnboardingTransitionView(
                from_status=t.from_status,
                to_status=t.to_status,
                occurred_at=t.occurred_at.isoformat(),
                event_id=t.event_id,
            )
            for t in progress.transitions
        ]

        steps = [
            self._verify_entity,
            self._map_ubo_owners,
            self._collect_documents,
            self._screen,
            self._rate_risk,
            self._obtain_compliance_approval,
            self._activate,
        ]
        try:
            if self._status not in TERMINAL_STATUSES:
                for step in steps[RESUME_STEP_BY_STATUS[self._status]:]:
                    await step()
        except _OnboardingEndedError:
            pass
        finally:
            if self._status in TERMINAL_STATUSES:
                self._waiting_on = None

        return OnboardingWorkflowResult(
            onboarding_request_id=self._request_id,
            final_status=self._status,
            rejection_category=self._rejection_category,
        )

    # ── steps ────────────────────────────────────────────────────────────────

    async def _verify_entity(self) -> None:
        # Resuming in verification or under review: the submission is repeated
        # (idempotent, so the same vendor reference) to re-establish correlation.
        if self._status == _Status.DRAFT:
            await self._transition(_Status.ENTITY_VERIFICATION_IN_PROGRESS)

        submission: EntityVerificationSubmission = await self._call(
            OnboardingActivities.verify_entity, OnboardingRequestRef(self._request_id)
        )
        self._kyb_submission = submission
        early, self._kyb_early = self._kyb_early, []
        for payload in early:
            self._accept_kyb_result(payload)

        outcome = submission.outcome
        while True:
            self._kyb_outcome = outcome
            if outcome in _KYB_VERIFIED:
                self._kyb_resolved = True
                await self._transition(
                    _Status.ENTITY_VERIFIED, metadata=self._kyb_metadata(outcome)
                )
                return
            if outcome in _KYB_REJECTED:
                self._kyb_resolved = True
                await self._reject(
                    _RejectionCategory.KYB_FAILURE, metadata=self._kyb_metadata(outcome)
                )
            if outcome in _KYB_NEEDS_REVIEW and self._status != _Status.UNDER_REVIEW:
                await self._transition(_Status.UNDER_REVIEW, metadata=self._kyb_metadata(outcome))

            # PENDING, or a review outcome while already under review: wait for the
            # next correlated answer. Not customer inactivity — no timeout here.
            self._waiting_on = (
                WaitingOn.MANUAL_REVIEW
                if self._status == _Status.UNDER_REVIEW
                else WaitingOn.ENTITY_VERIFICATION_PROVIDER
            )
            await workflow.wait_condition(lambda: bool(self._kyb_answers))
            self._waiting_on = WaitingOn.PLATFORM
            outcome = self._kyb_answers.pop(0)

    async def _map_ubo_owners(self) -> None:
        await self._enter(_Status.UBO_MAPPING_IN_PROGRESS)
        owners = await self._call(
            OnboardingActivities.identify_ubo_owners, OnboardingRequestRef(self._request_id)
        )
        self._ubo_owner_references = list(owners.owner_references)
        for owner_reference in owners.owner_references:
            await self._call(
                OnboardingActivities.map_ubo_owner,
                MapUboOwnerInput(self._request_id, owner_reference),
            )
            self._ubo_owners_mapped += 1
        await self._transition(
            _Status.UBO_MAPPING_COMPLETE,
            metadata={"ubo_owners_mapped": self._ubo_owners_mapped},
        )

    async def _collect_documents(self) -> None:
        # On resume the customer is waited on from now: time the workflow spent not
        # running was not time the customer was being asked to act.
        self._collecting_since = await self._enter(_Status.DOCUMENT_COLLECTION_IN_PROGRESS)

        while True:
            if self._unprocessed_document_ids:
                self._unprocessed_document_ids = []
                assert self._last_customer_activity_at is not None
                await self._call(
                    OnboardingActivities.record_customer_activity,
                    RecordCustomerActivityInput(
                        onboarding_request_id=self._request_id,
                        expected_status=_Status.DOCUMENT_COLLECTION_IN_PROGRESS,
                        occurred_at=self._last_customer_activity_at,
                    ),
                    timeout=_TRANSITION_TIMEOUT,
                )

            completeness = await self._call(
                OnboardingActivities.check_documents, OnboardingRequestRef(self._request_id)
            )
            self._missing_document_types = list(completeness.missing_document_types)
            if completeness.complete:
                await self._transition(
                    _Status.DOCUMENT_COLLECTION_COMPLETE,
                    metadata={"document_ids": list(self._received_document_ids)},
                )
                return
            if self._unprocessed_document_ids:
                continue  # arrived while the check ran

            self._waiting_on = WaitingOn.CUSTOMER
            deadline = self._inactivity_deadline()
            assert deadline is not None  # collection has started
            remaining = deadline - workflow.now()
            arrived = remaining > timedelta(0) and await self._wait(
                lambda: bool(self._unprocessed_document_ids), remaining
            )
            self._waiting_on = WaitingOn.PLATFORM
            if not arrived and not self._unprocessed_document_ids:
                await self._transition(
                    _Status.ABANDONED,
                    metadata={
                        "reason": "customer_inactivity",
                        "inactivity_timeout_seconds": int(
                            self._inactivity_timeout.total_seconds()
                        ),
                    },
                )
                raise _OnboardingEndedError

    async def _screen(self) -> None:
        await self._enter(_Status.SCREENING_IN_PROGRESS)
        outcome = await self._call(
            OnboardingActivities.screen, OnboardingRequestRef(self._request_id)
        )
        self._screening_reference = outcome.screening_reference
        self._screening_result = outcome.result
        metadata = {
            "screening_reference": outcome.screening_reference,
            "screening_result": outcome.result,
        }
        if outcome.result == _SCREENING_HARD_BLOCK:
            await self._reject(_RejectionCategory.SCREENING_BLOCK, metadata=metadata)
        await self._transition(_Status.SCREENING_COMPLETE, metadata=metadata)

    async def _rate_risk(self) -> None:
        await self._enter(_Status.RISK_RATING_IN_PROGRESS)
        outcome = await self._call(
            OnboardingActivities.rate_risk, OnboardingRequestRef(self._request_id)
        )
        self._risk_rating_reference = outcome.rating_reference
        self._risk_rating = outcome.rating
        await self._transition(
            _Status.RISK_RATED,
            metadata={"rating_reference": outcome.rating_reference, "risk_rating": outcome.rating},
        )

    async def _obtain_compliance_approval(self) -> None:
        await self._enter(_Status.PENDING_COMPLIANCE_APPROVAL)
        approval: ComplianceApprovalRequested = await self._call(
            OnboardingActivities.request_compliance_approval,
            OnboardingRequestRef(self._request_id),
        )
        self._approval = approval
        early, self._compliance_early = self._compliance_early, []
        for payload in early:
            self._accept_compliance_decision(payload)

        decision = approval.decision
        while decision not in (_COMPLIANCE_APPROVED, _COMPLIANCE_REJECTED):
            self._waiting_on = WaitingOn.COMPLIANCE
            await workflow.wait_condition(lambda: bool(self._compliance_answers))
            self._waiting_on = WaitingOn.PLATFORM
            decision = self._compliance_answers.pop(0).decision

        self._compliance_resolved = True
        self._compliance_decision = decision
        # The approval request id is how compliance's own record of the decision —
        # including any reason — is found. The reason itself never enters here.
        metadata = {"approval_request_id": approval.approval_request_id}
        if decision == _COMPLIANCE_REJECTED:
            await self._reject(_RejectionCategory.COMPLIANCE_REJECTION, metadata=metadata)
        await self._transition(_Status.APPROVED, metadata=metadata)

    async def _activate(self) -> None:
        await self._enter(_Status.ACCOUNT_CREATION_IN_PROGRESS)
        accounts = await self._call(
            OnboardingActivities.create_accounts, OnboardingRequestRef(self._request_id)
        )
        self._account_ids = list(accounts.account_ids)
        user = await self._call(
            OnboardingActivities.provision_initial_user, OnboardingRequestRef(self._request_id)
        )
        self._user_reference = user.user_reference
        await self._transition(
            _Status.ACTIVE,
            metadata={"account_ids": list(accounts.account_ids), "user_reference": user.user_reference},
        )
        notification = await self._call(
            OnboardingActivities.notify_completion, OnboardingRequestRef(self._request_id)
        )
        self._notification_reference = notification.notification_reference

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _call(self, activity_method: Any, arg: Any, *, timeout: timedelta = _DEPENDENCY_TIMEOUT) -> Any:
        return await workflow.execute_activity_method(
            activity_method,
            arg,
            start_to_close_timeout=timeout,
            retry_policy=self._retry,
        )

    async def _transition(
        self,
        to_status: str,
        *,
        rejection_category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> datetime:
        """Apply the transition through its activity; return the time it was stamped with."""
        occurred_at = workflow.now()
        output = await self._call(
            OnboardingActivities.transition_onboarding_request,
            TransitionOnboardingRequestInput(
                onboarding_request_id=self._request_id,
                expected_status=self._status,
                to_status=to_status,
                occurred_at=occurred_at,
                rejection_category=rejection_category,
                metadata=metadata,
            ),
            timeout=_TRANSITION_TIMEOUT,
        )
        self._transitions.append(
            OnboardingTransitionView(
                from_status=self._status,
                to_status=to_status,
                occurred_at=occurred_at.isoformat(),
                event_id=output.event_id,
            )
        )
        self._status = to_status
        return occurred_at

    async def _enter(self, in_progress: str) -> datetime:
        """Move into a step's in-progress status, unless the request is already there
        from an earlier execution. Returns when the step began for this execution."""
        if self._status == in_progress:
            return workflow.now()
        return await self._transition(in_progress)

    async def _reject(
        self,
        category: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._transition(_Status.REJECTED, rejection_category=category, metadata=metadata)
        self._rejection_category = category
        raise _OnboardingEndedError

    def _kyb_metadata(self, outcome: str) -> dict[str, Any]:
        assert self._kyb_submission is not None
        return {
            "vendor_id": self._kyb_submission.vendor_id,
            "vendor_reference": self._kyb_submission.vendor_reference,
            "entity_verification_outcome": outcome,
        }

    def _inactivity_deadline(self) -> datetime | None:
        if self._collecting_since is None:
            return None
        last_action = self._collecting_since
        if self._last_customer_activity_at is not None:
            last_action = max(last_action, self._last_customer_activity_at)
        return last_action + self._inactivity_timeout

    @staticmethod
    async def _wait(predicate: Any, timeout: timedelta) -> bool:
        """True if ``predicate`` became true within ``timeout``."""
        try:
            await workflow.wait_condition(predicate, timeout=timeout)
        except TimeoutError:
            return False
        return True


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
