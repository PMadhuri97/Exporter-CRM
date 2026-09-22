"""
Onboarding workflow dependency contracts and their deterministic stubs.

Covers the contract data (validation, Temporal serialisation, correlation of
asynchronous answers), each stub's configured outcomes, and injection of a stub
set into an activity running under Temporal's activity test environment.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from temporalio import activity
from temporalio.converter import DataConverter
from temporalio.testing import ActivityEnvironment

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRiskRating,
    OnboardingScreeningResult,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    AccountCreator,
    AccountsCreated,
    CompletionNotificationSent,
    CompletionNotifier,
    ComplianceApprovalRequested,
    ComplianceApprover,
    ComplianceDecisionReceived,
    CustomerUserProvisioned,
    CustomerUserProvisioner,
    DocumentChecklist,
    DocumentCompleteness,
    DocumentSubmitted,
    EntityVerificationSubmission,
    EntityVerifier,
    KybResultReceived,
    OnboardingWorkflowDependencies,
    RiskRater,
    RiskRatingOutcome,
    Screener,
    ScreeningOutcome,
    UboMapper,
    UboOwnerMapped,
    UboOwnersIdentified,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubAccountCreator,
    StubCompletionNotifier,
    StubComplianceApprover,
    StubCustomerUserProvisioner,
    StubDependencyUnavailableError,
    StubDocumentChecklist,
    StubEntityVerifier,
    StubRiskRater,
    StubScreener,
    StubUboMapper,
    stub_dependencies,
)
from app.shared.enums.kyb import NormalisedResult

REQUEST = "5b6f0c7e-1d7a-4c1e-9d0e-3f2f4b8a9c11"
OTHER_REQUEST = "0e1d2c3b-4a59-4687-8f9e-a0b1c2d3e4f5"


# ── contract data ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "build",
    [
        lambda: EntityVerificationSubmission("vendor", "ref", "APPROVED_ISH"),
        lambda: EntityVerificationSubmission("vendor", "", "VERIFIED"),
        lambda: KybResultReceived(REQUEST, "vendor", "ref", "verified"),
        lambda: DocumentSubmitted(REQUEST, "doc-1", "PASSPORT"),
        lambda: DocumentCompleteness(complete=True, missing_document_types=("LICENCE",)),
        lambda: DocumentCompleteness(complete=False),
        lambda: ScreeningOutcome("ref", "BLOCKED"),
        lambda: RiskRatingOutcome("ref", "SEVERE"),
        lambda: ComplianceApprovalRequested("approval", decision="MAYBE"),
        lambda: ComplianceApprovalRequested("approval", reason="no decision yet"),
        lambda: ComplianceDecisionReceived(REQUEST, "", "APPROVED"),
        lambda: UboOwnersIdentified(("owner-1", "owner-1")),
        lambda: AccountsCreated(()),
        lambda: CustomerUserProvisioned(" "),
    ],
)
def test_contract_data_rejects_invalid_values(build):
    with pytest.raises(ValueError):
        build()


def test_contract_data_exposes_existing_enums():
    assert EntityVerificationSubmission("v", "r", "REJECTED").normalised_result is NormalisedResult.REJECTED
    assert ScreeningOutcome("r", "HARD_BLOCK").screening_result is OnboardingScreeningResult.HARD_BLOCK
    assert RiskRatingOutcome("r", "HIGH").risk_rating is OnboardingRiskRating.HIGH
    assert (
        ComplianceApprovalRequested("a").compliance_decision is None
        and ComplianceDecisionReceived(REQUEST, "a", "REJECTED").compliance_decision
        is OnboardingComplianceDecision.REJECTED
    )
    assert (
        DocumentSubmitted(REQUEST, "d", "LICENCE").onboarding_document_type
        is OnboardingDocumentType.LICENCE
    )
    assert DocumentCompleteness(False, ("LICENCE",)).missing == (OnboardingDocumentType.LICENCE,)


@pytest.mark.parametrize(
    "value",
    [
        EntityVerificationSubmission("vendor", "vendor:ref", "PENDING"),
        KybResultReceived(REQUEST, "vendor", "vendor:ref", "VERIFIED"),
        UboOwnersIdentified(("owner-1", "owner-2")),
        UboOwnerMapped("owner-1"),
        DocumentSubmitted(REQUEST, "doc-1", "CERTIFICATE_OF_INCORPORATION"),
        DocumentCompleteness(False, ("LICENCE", "BANK_STATEMENT")),
        DocumentCompleteness(True),
        ScreeningOutcome("screening-ref", "CLEAR"),
        RiskRatingOutcome("rating-ref", "MEDIUM"),
        ComplianceApprovalRequested("approval-1"),
        ComplianceApprovalRequested("approval-1", "REJECTED", "sanctioned jurisdiction"),
        ComplianceDecisionReceived(REQUEST, "approval-1", "APPROVED"),
        AccountsCreated(("account-1", "account-2")),
        CustomerUserProvisioned("user-1"),
        CompletionNotificationSent("notification-1"),
    ],
    ids=lambda value: type(value).__name__,
)
async def test_contract_data_round_trips_through_the_temporal_converter(value):
    payloads = await DataConverter.default.encode([value])
    [decoded] = await DataConverter.default.decode(payloads, [type(value)])
    assert decoded == value


# ── correlation of asynchronous answers ───────────────────────────────────────


def test_kyb_result_answers_only_its_own_submission():
    submission = EntityVerificationSubmission("vendor", "vendor:ref-1", "PENDING")

    assert KybResultReceived(REQUEST, "vendor", "vendor:ref-1", "VERIFIED").answers(REQUEST, submission)
    assert not KybResultReceived(REQUEST, "vendor", "vendor:stale", "VERIFIED").answers(
        REQUEST, submission
    )
    assert not KybResultReceived(REQUEST, "other-vendor", "vendor:ref-1", "VERIFIED").answers(
        REQUEST, submission
    )
    assert not KybResultReceived(OTHER_REQUEST, "vendor", "vendor:ref-1", "VERIFIED").answers(
        REQUEST, submission
    )


def test_compliance_decision_answers_only_its_own_approval_request():
    requested = ComplianceApprovalRequested("approval-1")

    assert ComplianceDecisionReceived(REQUEST, "approval-1", "APPROVED").answers(REQUEST, requested)
    assert not ComplianceDecisionReceived(REQUEST, "approval-2", "APPROVED").answers(
        REQUEST, requested
    )
    assert not ComplianceDecisionReceived(OTHER_REQUEST, "approval-1", "APPROVED").answers(
        REQUEST, requested
    )


def test_document_submission_is_identified_by_document_id():
    first = DocumentSubmitted(REQUEST, "doc-1", "LICENCE")
    redelivered = DocumentSubmitted(REQUEST, "doc-1", "LICENCE")

    assert first == redelivered
    assert len({first, redelivered}) == 1
    assert first.is_for(REQUEST)
    assert not first.is_for(OTHER_REQUEST)


# ── stubs ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stub", "protocol"),
    [
        (StubEntityVerifier(), EntityVerifier),
        (StubUboMapper(), UboMapper),
        (StubDocumentChecklist(), DocumentChecklist),
        (StubScreener(), Screener),
        (StubRiskRater(), RiskRater),
        (StubComplianceApprover(), ComplianceApprover),
        (StubAccountCreator(), AccountCreator),
        (StubCustomerUserProvisioner(), CustomerUserProvisioner),
        (StubCompletionNotifier(), CompletionNotifier),
    ],
    ids=lambda value: getattr(value, "__name__", type(value).__name__),
)
def test_stub_implements_its_contract(stub, protocol):
    assert isinstance(stub, protocol)


async def test_entity_verifier_success_is_deterministic():
    verifier = StubEntityVerifier()

    first = await verifier.submit(REQUEST)
    second = await verifier.submit(REQUEST)

    assert first == second
    assert first.normalised_result is NormalisedResult.VERIFIED
    assert first.vendor_reference == f"stub-kyb-vendor:{REQUEST}"
    assert (await verifier.submit(OTHER_REQUEST)).vendor_reference != first.vendor_reference
    assert verifier.calls == [("submit", REQUEST), ("submit", REQUEST), ("submit", OTHER_REQUEST)]


async def test_entity_verifier_rejection():
    submission = await StubEntityVerifier(outcome=NormalisedResult.REJECTED).submit(REQUEST)
    assert submission.normalised_result is NormalisedResult.REJECTED


async def test_entity_verifier_pending_then_correlated_result():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    submission = await verifier.submit(REQUEST)

    answer = verifier.result_for(REQUEST, NormalisedResult.VERIFIED)
    stale = verifier.result_for(REQUEST, NormalisedResult.REJECTED, vendor_reference="stale-ref")

    assert submission.normalised_result is NormalisedResult.PENDING
    assert answer.answers(REQUEST, submission)
    assert not stale.answers(REQUEST, submission)


async def test_ubo_mapper_identifies_stable_owner_references():
    mapper = StubUboMapper(owner_count=3)

    owners = await mapper.identify_owners(REQUEST)
    assert owners == await mapper.identify_owners(REQUEST)
    assert owners.owner_references == tuple(f"{REQUEST}:owner:{n}" for n in (1, 2, 3))

    mapped = await mapper.map_owner(REQUEST, owners.owner_references[0])
    assert mapped.owner_reference == owners.owner_references[0]
    assert (await StubUboMapper(owner_count=0).identify_owners(REQUEST)).owner_references == ()


async def test_document_checklist_completes_once_required_types_are_recorded():
    checklist = StubDocumentChecklist(
        required=(OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, OnboardingDocumentType.LICENCE)
    )

    initial = await checklist.check(REQUEST)
    assert not initial.complete
    assert initial.missing == (
        OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
        OnboardingDocumentType.LICENCE,
    )

    certificate = checklist.submission(REQUEST, OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, 1)
    checklist.record(certificate)
    checklist.record(certificate)  # redelivery changes nothing
    assert (await checklist.check(REQUEST)).missing == (OnboardingDocumentType.LICENCE,)

    checklist.record(checklist.submission(REQUEST, OnboardingDocumentType.LICENCE, 2))
    assert (await checklist.check(REQUEST)) == DocumentCompleteness(complete=True)
    assert not (await checklist.check(OTHER_REQUEST)).complete


async def test_screener_clear_and_hard_block():
    clear = await StubScreener().screen(REQUEST)
    blocked = await StubScreener(result=OnboardingScreeningResult.HARD_BLOCK).screen(REQUEST)

    assert clear.screening_result is OnboardingScreeningResult.CLEAR
    assert blocked.screening_result is OnboardingScreeningResult.HARD_BLOCK
    assert clear.screening_reference == blocked.screening_reference == f"stub-screening:{REQUEST}"


async def test_risk_rater_reports_configured_rating():
    outcome = await StubRiskRater(rating=OnboardingRiskRating.HIGH).rate(REQUEST)
    assert outcome.risk_rating is OnboardingRiskRating.HIGH


async def test_compliance_automatic_approval():
    requested = await StubComplianceApprover().request_approval(REQUEST)
    assert requested.compliance_decision is OnboardingComplianceDecision.APPROVED


async def test_compliance_explicit_rejection():
    requested = await StubComplianceApprover(
        decision=OnboardingComplianceDecision.REJECTED, reason="declined by reviewer"
    ).request_approval(REQUEST)

    assert requested.compliance_decision is OnboardingComplianceDecision.REJECTED
    assert requested.reason == "declined by reviewer"


async def test_compliance_decision_arriving_later_is_correlated():
    approver = StubComplianceApprover(decision=None)
    requested = await approver.request_approval(REQUEST)

    decision = approver.decision_for(REQUEST, OnboardingComplianceDecision.REJECTED)
    unrelated = approver.decision_for(
        REQUEST, OnboardingComplianceDecision.APPROVED, approval_request_id="stub-approval:other"
    )

    assert requested.compliance_decision is None
    assert decision.answers(REQUEST, requested)
    assert not unrelated.answers(REQUEST, requested)


async def test_account_creation_user_provisioning_and_notification():
    accounts = await StubAccountCreator(account_count=2).create_accounts(REQUEST)
    user = await StubCustomerUserProvisioner().provision_initial_user(REQUEST)
    notification = await StubCompletionNotifier().notify_completed(REQUEST)

    assert accounts.account_ids == (f"{REQUEST}:account:1", f"{REQUEST}:account:2")
    assert user.user_reference == f"{REQUEST}:initial-user"
    assert notification.notification_reference == f"{REQUEST}:completion-notification"


async def test_fail_next_raises_then_recovers():
    screener = StubScreener()
    screener.fail_next(times=2)

    for _ in range(2):
        with pytest.raises(StubDependencyUnavailableError):
            await screener.screen(REQUEST)
    assert (await screener.screen(REQUEST)).screening_result is OnboardingScreeningResult.CLEAR
    assert len(screener.calls) == 3

    custom = StubAccountCreator()
    custom.fail_next(TimeoutError("ledger timed out"))
    with pytest.raises(TimeoutError, match="ledger timed out"):
        await custom.create_accounts(REQUEST)


# ── dependency set and injection ──────────────────────────────────────────────


def test_stub_dependencies_defaults_and_overrides():
    blocked = StubScreener(result=OnboardingScreeningResult.HARD_BLOCK)
    deps = stub_dependencies(screener=blocked)

    assert isinstance(deps, OnboardingWorkflowDependencies)
    assert deps.screener is blocked
    assert isinstance(deps.entity_verifier, StubEntityVerifier)

    with pytest.raises(TypeError, match="unknown dependencies"):
        stub_dependencies(screening=blocked)


def test_dependency_set_rejects_an_object_missing_its_contract():
    with pytest.raises(TypeError, match="risk_rater does not implement RiskRater"):
        stub_dependencies(risk_rater=object())


@dataclass(frozen=True)
class _ScreeningStepInput:
    onboarding_request_id: str


class _ActivitiesUnderTest:
    """Shaped like the workflow's activities: built with the dependency set, each
    method an activity that calls one dependency and returns contract data."""

    def __init__(self, deps: OnboardingWorkflowDependencies) -> None:
        self._deps = deps

    @activity.defn(name="test_screen_onboarding_request")
    async def screen(self, inp: _ScreeningStepInput) -> ScreeningOutcome:
        return await self._deps.screener.screen(inp.onboarding_request_id)


async def test_stub_dependencies_can_be_injected_into_an_activity():
    deps = stub_dependencies(screener=StubScreener(result=OnboardingScreeningResult.HARD_BLOCK))
    activities = _ActivitiesUnderTest(deps)

    outcome = await ActivityEnvironment().run(activities.screen, _ScreeningStepInput(REQUEST))

    assert outcome.screening_result is OnboardingScreeningResult.HARD_BLOCK
    assert deps.screener.calls == [("screen", REQUEST)]
