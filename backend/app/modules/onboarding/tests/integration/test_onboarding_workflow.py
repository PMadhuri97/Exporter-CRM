"""
OnboardingWorkflow end to end: a time-skipping Temporal server, the real activities
and PostgreSQL, and deterministic stub dependencies.

Each test runs its own server and task queue and creates its own onboarding request.
Outcomes are asserted on the database (status, rejection, one event per transition)
as well as on the workflow result and queries.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from itertools import pairwise

import pytest
from temporalio.client import WorkflowFailureError

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingScreeningResult,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    EntityVerificationSubmission,
    KybResultReceived,
)
from app.modules.onboarding.exceptions import OnboardingDependencyUnavailableError
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    SEEDED_LEGAL_NAME,
    SEEDED_REGISTRATION_NUMBER,
    SEEDED_TAX_IDENTIFICATION_NUMBER,
    create_onboarding_request,
    read_onboarding_events,
    read_onboarding_request,
)
from app.modules.onboarding.tests.fixtures.onboarding_workflow import (
    FORWARD_PATH,
    assert_transitions,
    current_status,
    no_documents_required,
    onboarding_workflow,
    wait_until_status,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubComplianceApprover,
    StubDocumentChecklist,
    StubEntityVerifier,
    StubScreener,
    stub_dependencies,
)
from app.modules.onboarding.workflows.onboarding_workflow import (
    OnboardingWorkflow,
    workflow_id_for,
)
from app.platform.workflow.tests.fixtures.temporal_env import send_signal_twice, wait_for
from app.shared.enums.kyb import NormalisedResult

S = OnboardingRequestStatus


# ── happy path and query behaviour ────────────────────────────────────────────


async def test_happy_path_runs_from_draft_to_active():
    deps = stub_dependencies(document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()

        assert result.final_status == "ACTIVE"
        assert result.rejection_category is None

        request = await read_onboarding_request(request_id)
        assert request.status == S.ACTIVE
        assert request.initiated_at is not None and request.completed_at is not None
        await assert_transitions(request_id, FORWARD_PATH)

        rid = str(request_id)
        assert deps.ubo_mapper.calls == [
            ("identify_owners", rid),
            ("map_owner", rid, f"{rid}:owner:1"),
            ("map_owner", rid, f"{rid}:owner:2"),
        ]
        assert deps.completion_notifier.calls == [("notify_completed", rid)]

        status = await current_status(handle)
        assert status == {
            "status": "ACTIVE",
            "waiting_on": None,
            "next_customer_action": None,
            "missing_document_types": [],
        }


async def test_onboarding_detail_holds_references_and_outcomes_only():
    deps = stub_dependencies(document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (_, handle, request_id):
        await handle.result()
        detail = await handle.query("onboarding_detail")

    rid = str(request_id)
    assert detail["onboarding_request_id"] == rid
    assert detail["status"] == "ACTIVE"
    assert detail["entity_verification_reference"] == f"stub-kyb-vendor:{rid}"
    assert detail["entity_verification_outcome"] == "VERIFIED"
    assert detail["ubo_owners_mapped"] == 2
    assert detail["screening_result"] == "CLEAR"
    assert detail["risk_rating"] == "LOW"
    assert detail["compliance_decision"] == "APPROVED"
    assert detail["account_ids"] == [f"{rid}:account:1"]
    assert detail["user_reference"] == f"{rid}:initial-user"
    assert detail["completion_notification_reference"] == f"{rid}:completion-notification"
    assert [(t["from_status"], t["to_status"]) for t in detail["transitions"]] == [
        (a.value, b.value) for a, b in pairwise(FORWARD_PATH)
    ]

    # Nothing from the onboarding record itself is held in workflow state.
    serialised = json.dumps(detail)
    for sensitive in (
        SEEDED_LEGAL_NAME,
        SEEDED_REGISTRATION_NUMBER,
        SEEDED_TAX_IDENTIFICATION_NUMBER,
        "Fixture Street",
    ):
        assert sensitive not in serialised


# ── terminal business outcomes ────────────────────────────────────────────────


async def test_kyb_rejection_rejects_without_retrying_or_continuing():
    deps = stub_dependencies(entity_verifier=StubEntityVerifier(outcome=NormalisedResult.REJECTED))

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()

    assert result.final_status == "REJECTED"
    assert result.rejection_category == "KYB_FAILURE"
    assert len(deps.entity_verifier.calls) == 1
    assert deps.ubo_mapper.calls == []

    request = await read_onboarding_request(request_id)
    assert request.status == S.REJECTED
    assert request.rejection_category == OnboardingRejectionCategory.KYB_FAILURE
    await assert_transitions(
        request_id, [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.REJECTED]
    )


async def test_screening_hard_block_rejects():
    deps = stub_dependencies(
        document_checklist=no_documents_required(),
        screener=StubScreener(result=OnboardingScreeningResult.HARD_BLOCK),
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()

    assert (result.final_status, result.rejection_category) == ("REJECTED", "SCREENING_BLOCK")
    assert len(deps.screener.calls) == 1
    assert deps.risk_rater.calls == []
    request = await read_onboarding_request(request_id)
    assert request.rejection_category == OnboardingRejectionCategory.SCREENING_BLOCK
    await assert_transitions(request_id, [*FORWARD_PATH[:8], S.REJECTED])


async def test_compliance_rejection_rejects_without_copying_the_reason():
    deps = stub_dependencies(
        document_checklist=no_documents_required(),
        compliance_approver=StubComplianceApprover(
            decision=OnboardingComplianceDecision.REJECTED, reason="declined by reviewer"
        ),
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()

    assert (result.final_status, result.rejection_category) == ("REJECTED", "COMPLIANCE_REJECTION")
    assert deps.account_creator.calls == []
    request = await read_onboarding_request(request_id)
    assert request.rejection_category == OnboardingRejectionCategory.COMPLIANCE_REJECTION
    # The reviewer's text stays with compliance; the rejection points at it by id.
    assert request.rejection_reason is None
    await assert_transitions(request_id, [*FORWARD_PATH[:12], S.REJECTED])
    rejection = (await read_onboarding_events(request_id))[-1]
    assert rejection.event_metadata == {
        "approval_request_id": f"stub-approval:{request_id}",
        "rejection_category": "COMPLIANCE_REJECTION",
    }


# ── signals ───────────────────────────────────────────────────────────────────


async def test_document_signals_complete_collection_once_all_documents_are_present():
    checklist = StubDocumentChecklist(
        required=(
            OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
            OnboardingDocumentType.PROOF_OF_ADDRESS,
        )
    )
    deps = stub_dependencies(document_checklist=checklist)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        status = await wait_until_status(
            handle, "waiting on the customer", lambda s: s["waiting_on"] == "customer"
        )
        assert status["status"] == "DOCUMENT_COLLECTION_IN_PROGRESS"
        assert status["next_customer_action"] == "submit_documents"
        assert status["missing_document_types"] == [
            "CERTIFICATE_OF_INCORPORATION",
            "PROOF_OF_ADDRESS",
        ]

        first = checklist.submission(rid, OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, 1)
        checklist.record(first)
        await handle.signal(OnboardingWorkflow.document_submitted, first)
        status = await wait_until_status(
            handle,
            "one document still missing",
            lambda s: s["waiting_on"] == "customer" and s["missing_document_types"] == ["PROOF_OF_ADDRESS"],
        )

        second = checklist.submission(rid, OnboardingDocumentType.PROOF_OF_ADDRESS, 2)
        checklist.record(second)
        await handle.signal(OnboardingWorkflow.document_submitted, second)
        result = await handle.result()

        assert result.final_status == "ACTIVE"
        detail = await handle.query("onboarding_detail")
        assert detail["received_document_ids"] == [first.document_id, second.document_id]


async def test_kyb_result_signal_is_correlated_and_drives_manual_review():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(
            handle,
            "waiting on the verification provider",
            lambda s: s["waiting_on"] == "entity_verification_provider",
        )

        # Neither a stale reference nor another request's result may advance it.
        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.VERIFIED, vendor_reference="stale-ref"),
        )
        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(str(uuid.uuid4()), NormalisedResult.VERIFIED),
        )
        status = await current_status(handle)
        assert (status["status"], status["waiting_on"]) == (
            "ENTITY_VERIFICATION_IN_PROGRESS",
            "entity_verification_provider",
        )

        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.REQUIRES_MANUAL_REVIEW),
        )
        await wait_until_status(
            handle,
            "under manual review",
            lambda s: s["status"] == "UNDER_REVIEW" and s["waiting_on"] == "manual_review",
        )

        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.VERIFIED),
        )
        result = await handle.result()

    assert result.final_status == "ACTIVE"
    await assert_transitions(
        request_id,
        [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.UNDER_REVIEW, *FORWARD_PATH[2:]],
    )


async def test_kyb_result_arriving_before_submission_returns_is_held_and_applied():
    class _GatedVerifier(StubEntityVerifier):
        def __init__(self) -> None:
            super().__init__(outcome=NormalisedResult.PENDING)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def submit(self, onboarding_request_id: str) -> EntityVerificationSubmission:
            self.entered.set()
            await self.release.wait()
            return await super().submit(onboarding_request_id)

    verifier = _GatedVerifier()
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await asyncio.wait_for(verifier.entered.wait(), timeout=30)

        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            KybResultReceived(rid, verifier.vendor_id, "unrelated-ref", "REJECTED"),
        )
        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.VERIFIED),
        )
        verifier.release.set()
        result = await handle.result()

    assert result.final_status == "ACTIVE"


async def test_compliance_decision_signal_is_correlated():
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(
        document_checklist=no_documents_required(), compliance_approver=approver
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(
            handle, "waiting on compliance", lambda s: s["waiting_on"] == "compliance"
        )

        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(
                rid,
                OnboardingComplianceDecision.REJECTED,
                approval_request_id="stub-approval:unrelated",
            ),
        )
        status = await current_status(handle)
        assert (status["status"], status["waiting_on"]) == (
            "PENDING_COMPLIANCE_APPROVAL",
            "compliance",
        )

        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(rid, OnboardingComplianceDecision.APPROVED),
        )
        result = await handle.result()

    assert result.final_status == "ACTIVE"
    assert deps.account_creator.calls == [("create_accounts", rid)]


async def test_compliance_rejection_by_signal_rejects():
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(
        document_checklist=no_documents_required(), compliance_approver=approver
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on compliance", lambda s: s["waiting_on"] == "compliance")
        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(rid, OnboardingComplianceDecision.REJECTED),
        )
        result = await handle.result()

    assert (result.final_status, result.rejection_category) == ("REJECTED", "COMPLIANCE_REJECTION")
    request = await read_onboarding_request(request_id)
    assert request.rejection_category == OnboardingRejectionCategory.COMPLIANCE_REJECTION
    assert request.rejection_reason is None


async def test_duplicate_signals_are_applied_once():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    checklist = StubDocumentChecklist(required=(OnboardingDocumentType.LICENCE,))
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(
        entity_verifier=verifier, document_checklist=checklist, compliance_approver=approver
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)

        await wait_until_status(
            handle, "waiting on provider", lambda s: s["waiting_on"] == "entity_verification_provider"
        )
        await send_signal_twice(
            handle,
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.VERIFIED),
        )

        await wait_until_status(handle, "waiting on customer", lambda s: s["waiting_on"] == "customer")
        licence = checklist.submission(rid, OnboardingDocumentType.LICENCE)
        checklist.record(licence)
        await send_signal_twice(handle, OnboardingWorkflow.document_submitted, licence)

        await wait_until_status(handle, "waiting on compliance", lambda s: s["waiting_on"] == "compliance")
        decision = approver.decision_for(rid, OnboardingComplianceDecision.APPROVED)
        await send_signal_twice(handle, OnboardingWorkflow.compliance_decision_received, decision)

        result = await handle.result()
        detail = await handle.query("onboarding_detail")

    assert result.final_status == "ACTIVE"
    assert detail["received_document_ids"] == [licence.document_id]
    assert len(checklist.calls) == 2  # on entering collection, and after the one new document
    await assert_transitions(request_id, FORWARD_PATH)


# ── inactivity ────────────────────────────────────────────────────────────────


async def test_customer_inactivity_abandons_after_the_default_thirty_days():
    deps = stub_dependencies(
        document_checklist=StubDocumentChecklist(required=(OnboardingDocumentType.LICENCE,))
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        await wait_until_status(handle, "waiting on customer", lambda s: s["waiting_on"] == "customer")
        detail = await handle.query("onboarding_detail")
        deadline = datetime.fromisoformat(detail["inactivity_deadline"])
        started = datetime.fromisoformat(detail["transitions"][-1]["occurred_at"])
        assert deadline - started == timedelta(days=30)

        result = await handle.result()
        status = await current_status(handle)

    assert result.final_status == "ABANDONED"
    assert result.rejection_category is None
    assert (status["waiting_on"], status["next_customer_action"]) == (None, None)
    assert deps.screener.calls == []

    request = await read_onboarding_request(request_id)
    assert request.status == S.ABANDONED
    assert request.rejection_category is None
    events = await read_onboarding_events(request_id)
    assert (events[-1].from_status, events[-1].to_status) == (
        "DOCUMENT_COLLECTION_IN_PROGRESS",
        "ABANDONED",
    )
    assert events[-1].created_at is not None


async def test_customer_document_submission_resets_the_inactivity_timer():
    checklist = StubDocumentChecklist(required=(OnboardingDocumentType.LICENCE,))
    deps = stub_dependencies(document_checklist=checklist)

    async with onboarding_workflow(deps) as (env, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", lambda s: s["waiting_on"] == "customer")
        collection_started = datetime.fromisoformat(
            (await handle.query("onboarding_detail"))["transitions"][-1]["occurred_at"]
        )

        await env.sleep(timedelta(days=20))
        # A document that does not complete the set is still a customer action.
        other = checklist.submission(rid, OnboardingDocumentType.BANK_STATEMENT, 1)
        await handle.signal(OnboardingWorkflow.document_submitted, other)

        async def _processed() -> bool:
            d = await handle.query("onboarding_detail")
            return d["waiting_on"] == "customer" and d["received_document_ids"] == [other.document_id]

        await wait_for(_processed, what="document processed")
        detail = await handle.query("onboarding_detail")
        activity_at = datetime.fromisoformat(detail["last_customer_activity_at"])
        assert activity_at - collection_started >= timedelta(days=20)
        assert datetime.fromisoformat(detail["inactivity_deadline"]) == activity_at + timedelta(days=30)

        await env.sleep(timedelta(days=15))  # 35 days after collection began
        assert (await current_status(handle))["status"] == "DOCUMENT_COLLECTION_IN_PROGRESS"

        result = await handle.result()

    assert result.final_status == "ABANDONED"
    request = await read_onboarding_request(request_id)
    assert request.last_activity_at is not None
    assert request.last_activity_at >= activity_at


async def test_waiting_on_verification_does_not_count_as_customer_inactivity():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (env, handle, request_id):
        await wait_until_status(
            handle, "waiting on provider", lambda s: s["waiting_on"] == "entity_verification_provider"
        )
        await env.sleep(timedelta(days=45))
        detail = await handle.query("onboarding_detail")
        assert detail["status"] == "ENTITY_VERIFICATION_IN_PROGRESS"
        assert detail["inactivity_deadline"] is None

        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(str(request_id), NormalisedResult.VERIFIED),
        )
        result = await handle.result()

    assert result.final_status == "ACTIVE"


# ── activity failures ─────────────────────────────────────────────────────────


async def test_retryable_activity_failure_is_retried_and_succeeds():
    screener = StubScreener()
    screener.fail_next(times=2)
    deps = stub_dependencies(document_checklist=no_documents_required(), screener=screener)

    async with onboarding_workflow(deps, retry_max_attempts=3) as (_, handle, request_id):
        result = await handle.result()

    assert result.final_status == "ACTIVE"
    assert len(screener.calls) == 3
    await assert_transitions(request_id, FORWARD_PATH)


async def test_retryable_failure_that_outlasts_the_retry_policy_fails_the_workflow():
    screener = StubScreener()
    screener.fail_next(times=3)
    deps = stub_dependencies(document_checklist=no_documents_required(), screener=screener)

    async with onboarding_workflow(deps, retry_max_attempts=3) as (_, handle, request_id):
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    assert len(screener.calls) == 3
    assert (await read_onboarding_request(request_id)).status == S.SCREENING_IN_PROGRESS


async def test_non_retryable_activity_failure_fails_without_retrying():
    screener = StubScreener()
    screener.fail_next(OnboardingDependencyUnavailableError("screening"))
    deps = stub_dependencies(document_checklist=no_documents_required(), screener=screener)

    async with onboarding_workflow(deps, retry_max_attempts=5) as (_, handle, request_id):
        with pytest.raises(WorkflowFailureError) as exc:
            await handle.result()

    cause = exc.value.cause
    while getattr(cause, "cause", None) is not None:
        cause = cause.cause
    assert getattr(cause, "type", None) == "OnboardingDependencyUnavailableError"
    assert len(screener.calls) == 1
    assert (await read_onboarding_request(request_id)).status == S.SCREENING_IN_PROGRESS
    assert deps.risk_rater.calls == []


# ── start service ─────────────────────────────────────────────────────────────


async def test_start_service_is_idempotent_per_request():
    from app.modules.onboarding.application.onboarding_workflow_service import (
        start_onboarding_workflow,
    )
    from app.platform.workflow.adapters import client as client_module
    from app.platform.workflow.tests.fixtures.temporal_env import embedded_temporal_client

    request_id = str(await create_onboarding_request())
    async with embedded_temporal_client():
        first = await start_onboarding_workflow(request_id)
        second = await start_onboarding_workflow(request_id)
        assert first == second == workflow_id_for(request_id)

        client = await client_module.get_temporal_client()
        handle = client.get_workflow_handle(first)
        description = await handle.describe()
        assert description.status is not None and description.status.name == "RUNNING"
        await handle.terminate("test finished")
