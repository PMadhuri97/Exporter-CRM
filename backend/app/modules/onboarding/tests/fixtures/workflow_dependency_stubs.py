"""
Deterministic stand-ins for the onboarding workflow's dependencies.

Test-only. Each stub returns exactly what the test configured it to return, and
nothing about any answer is decided here: a stub screener does not screen, it
reports the result it was told to report. There is no network access, no clock and
no random identifier. Every reference is derived from the onboarding request id, so
the same call always yields the same reference — which is also how a retried
activity sees the idempotent behaviour the contracts require.

Every stub records its calls in ``calls`` and can be told to raise on its next
call(s) with :meth:`fail_next`, to exercise a failing call as distinct from a
business outcome.

Build a full set with :func:`stub_dependencies`, overriding only what a test cares
about::

    deps = stub_dependencies(screener=StubScreener(result=OnboardingScreeningResult.HARD_BLOCK))
"""
from __future__ import annotations

from collections import deque
from typing import Any

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRiskRating,
    OnboardingScreeningResult,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    AccountsCreated,
    CompletionNotificationSent,
    ComplianceApprovalRequested,
    ComplianceDecisionReceived,
    CustomerUserProvisioned,
    DocumentCompleteness,
    DocumentSubmitted,
    EntityVerificationSubmission,
    KybResultReceived,
    OnboardingWorkflowDependencies,
    RiskRatingOutcome,
    ScreeningOutcome,
    UboOwnerMapped,
    UboOwnersIdentified,
)
from app.shared.enums.kyb import NormalisedResult


class StubDependencyUnavailableError(RuntimeError):
    """The fault a stub raises when told to fail, standing in for an outage."""


class _Recorder:
    """Call log and scripted failures shared by every stub."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._failures: deque[BaseException] = deque()

    def fail_next(self, error: BaseException | None = None, *, times: int = 1) -> None:
        """Raise ``error`` (default: :class:`StubDependencyUnavailableError`) on the
        next ``times`` calls, then behave normally again."""
        for _ in range(times):
            self._failures.append(
                error or StubDependencyUnavailableError(f"{type(self).__name__} unavailable")
            )

    def _record(self, *call: Any) -> None:
        self.calls.append(call)
        if self._failures:
            raise self._failures.popleft()


class StubEntityVerifier(_Recorder):
    """Reports ``outcome`` for every submission.

    Configure ``NormalisedResult.PENDING`` to model a vendor that answers later, and
    build the later answer with :meth:`result_for`.
    """

    def __init__(
        self,
        outcome: NormalisedResult = NormalisedResult.VERIFIED,
        vendor_id: str = "stub-kyb-vendor",
    ) -> None:
        super().__init__()
        self.outcome = outcome
        self.vendor_id = vendor_id

    def reference_for(self, onboarding_request_id: str) -> str:
        return f"{self.vendor_id}:{onboarding_request_id}"

    async def submit(self, onboarding_request_id: str) -> EntityVerificationSubmission:
        self._record("submit", onboarding_request_id)
        return EntityVerificationSubmission(
            vendor_id=self.vendor_id,
            vendor_reference=self.reference_for(onboarding_request_id),
            outcome=self.outcome.value,
        )

    def result_for(
        self,
        onboarding_request_id: str,
        outcome: NormalisedResult,
        *,
        vendor_reference: str | None = None,
    ) -> KybResultReceived:
        """The asynchronous answer to this stub's submission — or, with an explicit
        ``vendor_reference``, an answer to some other submission."""
        return KybResultReceived(
            onboarding_request_id=onboarding_request_id,
            vendor_id=self.vendor_id,
            vendor_reference=vendor_reference or self.reference_for(onboarding_request_id),
            outcome=outcome.value,
        )


class StubUboMapper(_Recorder):
    """Identifies ``owner_count`` owners per request and acknowledges each mapping."""

    def __init__(self, owner_count: int = 2) -> None:
        super().__init__()
        if owner_count < 0:
            raise ValueError("owner_count must be >= 0")
        self.owner_count = owner_count

    async def identify_owners(self, onboarding_request_id: str) -> UboOwnersIdentified:
        self._record("identify_owners", onboarding_request_id)
        return UboOwnersIdentified(
            owner_references=tuple(
                f"{onboarding_request_id}:owner:{n}" for n in range(1, self.owner_count + 1)
            )
        )

    async def map_owner(self, onboarding_request_id: str, owner_reference: str) -> UboOwnerMapped:
        self._record("map_owner", onboarding_request_id, owner_reference)
        return UboOwnerMapped(owner_reference=owner_reference)


class StubDocumentChecklist(_Recorder):
    """Complete once every type in ``required`` has been recorded as submitted.

    The required set is whatever the test passes in; the stub does not work out
    what a request requires. Record a submission with :meth:`record`, and build the
    matching signal payload with :meth:`submission`.
    """

    def __init__(
        self,
        required: tuple[OnboardingDocumentType, ...] = (
            OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
        ),
    ) -> None:
        super().__init__()
        self.required = tuple(required)
        self._submitted: dict[str, set[OnboardingDocumentType]] = {}

    def submission(
        self,
        onboarding_request_id: str,
        document_type: OnboardingDocumentType,
        sequence: int = 1,
    ) -> DocumentSubmitted:
        return DocumentSubmitted(
            onboarding_request_id=onboarding_request_id,
            document_id=f"{onboarding_request_id}:document:{sequence}",
            document_type=document_type.value,
        )

    def record(self, submitted: DocumentSubmitted) -> None:
        self._submitted.setdefault(submitted.onboarding_request_id, set()).add(
            submitted.onboarding_document_type
        )

    async def check(self, onboarding_request_id: str) -> DocumentCompleteness:
        self._record("check", onboarding_request_id)
        present = self._submitted.get(onboarding_request_id, set())
        missing = tuple(t.value for t in self.required if t not in present)
        return DocumentCompleteness(complete=not missing, missing_document_types=missing)


class StubScreener(_Recorder):
    def __init__(self, result: OnboardingScreeningResult = OnboardingScreeningResult.CLEAR) -> None:
        super().__init__()
        self.result = result

    async def screen(self, onboarding_request_id: str) -> ScreeningOutcome:
        self._record("screen", onboarding_request_id)
        return ScreeningOutcome(
            screening_reference=f"stub-screening:{onboarding_request_id}",
            result=self.result.value,
        )


class StubRiskRater(_Recorder):
    def __init__(self, rating: OnboardingRiskRating = OnboardingRiskRating.LOW) -> None:
        super().__init__()
        self.rating = rating

    async def rate(self, onboarding_request_id: str) -> RiskRatingOutcome:
        self._record("rate", onboarding_request_id)
        return RiskRatingOutcome(
            rating_reference=f"stub-risk-rating:{onboarding_request_id}",
            rating=self.rating.value,
        )


class StubComplianceApprover(_Recorder):
    """Returns ``decision`` immediately, or — with ``decision=None`` — leaves the
    decision to arrive later, built with :meth:`decision_for`."""

    def __init__(
        self,
        decision: OnboardingComplianceDecision | None = OnboardingComplianceDecision.APPROVED,
        reason: str | None = None,
    ) -> None:
        super().__init__()
        if decision is None and reason is not None:
            raise ValueError("a reason is only given with a decision")
        self.decision = decision
        self.reason = reason

    def approval_request_id_for(self, onboarding_request_id: str) -> str:
        return f"stub-approval:{onboarding_request_id}"

    async def request_approval(self, onboarding_request_id: str) -> ComplianceApprovalRequested:
        self._record("request_approval", onboarding_request_id)
        return ComplianceApprovalRequested(
            approval_request_id=self.approval_request_id_for(onboarding_request_id),
            decision=None if self.decision is None else self.decision.value,
            reason=self.reason,
        )

    def decision_for(
        self,
        onboarding_request_id: str,
        decision: OnboardingComplianceDecision,
        *,
        approval_request_id: str | None = None,
    ) -> ComplianceDecisionReceived:
        """The asynchronous decision on this stub's approval request — or, with an
        explicit ``approval_request_id``, on some other one."""
        return ComplianceDecisionReceived(
            onboarding_request_id=onboarding_request_id,
            approval_request_id=approval_request_id
            or self.approval_request_id_for(onboarding_request_id),
            decision=decision.value,
        )


class StubAccountCreator(_Recorder):
    def __init__(self, account_count: int = 1) -> None:
        super().__init__()
        if account_count < 1:
            raise ValueError("account_count must be >= 1")
        self.account_count = account_count

    async def create_accounts(self, onboarding_request_id: str) -> AccountsCreated:
        self._record("create_accounts", onboarding_request_id)
        return AccountsCreated(
            account_ids=tuple(
                f"{onboarding_request_id}:account:{n}" for n in range(1, self.account_count + 1)
            )
        )


class StubCustomerUserProvisioner(_Recorder):
    async def provision_initial_user(self, onboarding_request_id: str) -> CustomerUserProvisioned:
        self._record("provision_initial_user", onboarding_request_id)
        return CustomerUserProvisioned(user_reference=f"{onboarding_request_id}:initial-user")


class StubCompletionNotifier(_Recorder):
    async def notify_completed(self, onboarding_request_id: str) -> CompletionNotificationSent:
        self._record("notify_completed", onboarding_request_id)
        return CompletionNotificationSent(
            notification_reference=f"{onboarding_request_id}:completion-notification"
        )


def stub_dependencies(**overrides: Any) -> OnboardingWorkflowDependencies:
    """A full dependency set on the successful path, with any field replaced."""
    defaults: dict[str, Any] = {
        "entity_verifier": StubEntityVerifier(),
        "ubo_mapper": StubUboMapper(),
        "document_checklist": StubDocumentChecklist(),
        "screener": StubScreener(),
        "risk_rater": StubRiskRater(),
        "compliance_approver": StubComplianceApprover(),
        "account_creator": StubAccountCreator(),
        "customer_user_provisioner": StubCustomerUserProvisioner(),
        "completion_notifier": StubCompletionNotifier(),
    }
    unknown = set(overrides) - set(defaults)
    if unknown:
        raise TypeError(f"unknown dependencies: {sorted(unknown)}")
    return OnboardingWorkflowDependencies(**{**defaults, **overrides})
