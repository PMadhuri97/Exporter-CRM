"""
Reliability of the onboarding workflow: signal ordering and correlation, retry
behaviour and its effect on persisted transitions, inactivity edge cases, and the
queries at every point the workflow can wait.

Complements ``test_onboarding_workflow.py``, which covers each step's outcome. Runs
on a time-skipping Temporal server with the real activities and PostgreSQL and
deterministic stub dependencies. Nothing here depends on elapsed wall-clock time:
waits are on query results, and Temporal time is advanced explicitly.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta

import pytest

from app.modules.onboarding.application.activities import OnboardingActivities
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRequestStatus,
    OnboardingScreeningResult,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    ComplianceApprovalRequested,
    KybResultReceived,
)
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    SEEDED_LEGAL_NAME,
    SEEDED_REGISTRATION_NUMBER,
    SEEDED_TAX_IDENTIFICATION_NUMBER,
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
    StubAccountCreator,
    StubComplianceApprover,
    StubDocumentChecklist,
    StubEntityVerifier,
    StubScreener,
    stub_dependencies,
)
from app.modules.onboarding.workflows.onboarding_workflow import (
    NON_RETRYABLE_ERROR_TYPES,
    OnboardingWorkflow,
)
from app.platform.workflow.tests.fixtures.activity_faults import (
    FaultController,
    FaultMode,
    faulty_activity,
)
from app.platform.workflow.tests.fixtures.temporal_env import wait_for
from app.shared.enums.kyb import NormalisedResult

S = OnboardingRequestStatus
LICENCE = OnboardingDocumentType.LICENCE


def _waiting_on(who: str):
    return lambda s: s["waiting_on"] == who


async def _detail(handle) -> dict:
    return await handle.query("onboarding_detail")


async def _history_events(handle) -> list:
    return [event async for event in handle.fetch_history_events()]


# ── signals ───────────────────────────────────────────────────────────────────


async def test_document_submitted_before_collection_starts_is_taken_into_account():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    checklist = StubDocumentChecklist(required=(LICENCE,))
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=checklist)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on provider", _waiting_on("entity_verification_provider"))

        # The customer uploads before the workflow has reached document collection.
        licence = checklist.submission(rid, LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)
        detail = await _detail(handle)
        assert detail["status"] == "ENTITY_VERIFICATION_IN_PROGRESS"
        assert detail["received_document_ids"] == [licence.document_id]

        await handle.signal(
            OnboardingWorkflow.kyb_result_received, verifier.result_for(rid, NormalisedResult.VERIFIED)
        )
        result = await handle.result()
        detail = await _detail(handle)

    assert result.final_status == "ACTIVE"
    # Collection found the set complete on its first check: it never waited on the customer.
    assert checklist.calls == [("check", rid)]
    assert detail["received_document_ids"] == [licence.document_id]
    await assert_transitions(request_id, FORWARD_PATH)


async def test_compliance_decision_before_the_approval_request_returns_is_applied():
    class _GatedApprover(StubComplianceApprover):
        def __init__(self) -> None:
            super().__init__(decision=None)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def request_approval(self, onboarding_request_id: str) -> ComplianceApprovalRequested:
            self.entered.set()
            await self.release.wait()
            return await super().request_approval(onboarding_request_id)

    approver = _GatedApprover()
    deps = stub_dependencies(document_checklist=no_documents_required(), compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await asyncio.wait_for(approver.entered.wait(), timeout=60)

        # Two decisions arrive while the approval request is still being raised; only
        # the one naming that approval request may count.
        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(
                rid, OnboardingComplianceDecision.REJECTED, approval_request_id="stub-approval:unrelated"
            ),
        )
        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(rid, OnboardingComplianceDecision.APPROVED),
        )
        approver.release.set()
        result = await handle.result()

    assert result.final_status == "ACTIVE"
    await assert_transitions(request_id, FORWARD_PATH)


async def test_signals_with_unrelated_correlation_are_ignored():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    checklist = StubDocumentChecklist(required=(LICENCE,))
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=checklist)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on provider", _waiting_on("entity_verification_provider"))

        # Right request and reference, wrong vendor.
        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            KybResultReceived(rid, "another-vendor", verifier.reference_for(rid), "VERIFIED"),
        )
        # A document for a different onboarding request.
        stray = checklist.submission(str(uuid.uuid4()), LICENCE)
        await handle.signal(OnboardingWorkflow.document_submitted, stray)

        detail = await _detail(handle)
        assert detail["status"] == "ENTITY_VERIFICATION_IN_PROGRESS"
        assert detail["waiting_on"] == "entity_verification_provider"
        assert detail["received_document_ids"] == []
        assert detail["last_customer_activity_at"] is None

        await handle.signal(
            OnboardingWorkflow.kyb_result_received, verifier.result_for(rid, NormalisedResult.VERIFIED)
        )
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))
        assert (await _detail(handle))["received_document_ids"] == []

        licence = checklist.submission(rid, LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)
        result = await handle.result()

    assert result.final_status == "ACTIVE"


async def test_multiple_documents_submitted_together_are_all_counted():
    required = (
        OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
        OnboardingDocumentType.MEMORANDUM_OF_ASSOCIATION,
        OnboardingDocumentType.PROOF_OF_ADDRESS,
    )
    checklist = StubDocumentChecklist(required=required)
    deps = stub_dependencies(document_checklist=checklist)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))

        submissions = [checklist.submission(rid, t, n) for n, t in enumerate(required, start=1)]
        for submission in submissions:
            checklist.record(submission)
        await asyncio.gather(
            *(handle.signal(OnboardingWorkflow.document_submitted, s) for s in submissions)
        )
        result = await handle.result()
        detail = await _detail(handle)

    assert result.final_status == "ACTIVE"
    assert sorted(detail["received_document_ids"]) == sorted(s.document_id for s in submissions)
    await assert_transitions(request_id, FORWARD_PATH)


async def test_duplicate_document_submission_counts_as_one_customer_action():
    checklist = StubDocumentChecklist(
        required=(OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, LICENCE)
    )
    deps = stub_dependencies(document_checklist=checklist)

    async with onboarding_workflow(deps) as (env, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))

        first = checklist.submission(rid, OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, 1)
        checklist.record(first)
        await handle.signal(OnboardingWorkflow.document_submitted, first)
        await wait_until_status(
            handle, "one missing", lambda s: s["missing_document_types"] == ["LICENCE"]
        )
        activity_at = (await _detail(handle))["last_customer_activity_at"]

        await env.sleep(timedelta(days=10))
        await handle.signal(OnboardingWorkflow.document_submitted, first)  # redelivered later
        detail = await _detail(handle)

        assert detail["received_document_ids"] == [first.document_id]
        # A redelivery is not a new customer action and does not extend the deadline.
        assert detail["last_customer_activity_at"] == activity_at
        assert len(checklist.calls) == 2


# ── retries ───────────────────────────────────────────────────────────────────


async def test_activities_are_scheduled_with_exponential_backoff_and_non_retryable_types():
    deps = stub_dependencies(document_checklist=no_documents_required())

    async with onboarding_workflow(deps, retry_max_attempts=4, retry_initial_interval_seconds=2) as (
        _,
        handle,
        _request_id,
    ):
        await handle.result()
        events = await _history_events(handle)

    scheduled = [
        e.activity_task_scheduled_event_attributes
        for e in events
        if e.HasField("activity_task_scheduled_event_attributes")
    ]
    assert scheduled, "no activities were scheduled"
    for attrs in scheduled:
        policy = attrs.retry_policy
        assert policy.backoff_coefficient == 2.0, attrs.activity_type.name
        assert policy.initial_interval.ToTimedelta() == timedelta(seconds=2)
        assert policy.maximum_attempts == 4
        assert list(policy.non_retryable_error_types) == NON_RETRYABLE_ERROR_TYPES
        assert attrs.start_to_close_timeout.ToTimedelta() > timedelta(0)


async def test_transient_failure_retries_until_success():
    screener = StubScreener()
    screener.fail_next(times=3)
    deps = stub_dependencies(document_checklist=no_documents_required(), screener=screener)

    async with onboarding_workflow(deps, retry_max_attempts=4) as (_, handle, request_id):
        result = await handle.result()
        events = await _history_events(handle)

    assert result.final_status == "ACTIVE"
    assert len(screener.calls) == 4
    started_attempts = [
        e.activity_task_started_event_attributes.attempt
        for e in events
        if e.HasField("activity_task_started_event_attributes")
    ]
    assert max(started_attempts) == 4
    await assert_transitions(request_id, FORWARD_PATH)


@pytest.mark.parametrize(
    ("override", "rejection_category", "called"),
    [
        (
            {"entity_verifier": StubEntityVerifier(outcome=NormalisedResult.NOT_FOUND)},
            "KYB_FAILURE",
            "entity_verifier",
        ),
        (
            {"screener": StubScreener(result=OnboardingScreeningResult.HARD_BLOCK)},
            "SCREENING_BLOCK",
            "screener",
        ),
        (
            {
                "compliance_approver": StubComplianceApprover(
                    decision=OnboardingComplianceDecision.REJECTED, reason="declined"
                )
            },
            "COMPLIANCE_REJECTION",
            "compliance_approver",
        ),
    ],
    ids=["kyb", "screening", "compliance"],
)
async def test_terminal_business_outcomes_are_not_retried(override, rejection_category, called):
    deps = stub_dependencies(document_checklist=no_documents_required(), **override)

    async with onboarding_workflow(deps, retry_max_attempts=5) as (_, handle, _request_id):
        result = await handle.result()
        events = await _history_events(handle)

    assert (result.final_status, result.rejection_category) == ("REJECTED", rejection_category)
    assert len(getattr(deps, called).calls) == 1
    assert not any(e.HasField("activity_task_failed_event_attributes") for e in events)


async def test_transition_retried_after_its_commit_is_not_applied_twice():
    """Every transition commits and then loses its response, so Temporal retries each
    one. The retry finds the transition already applied: one event per transition."""
    deps = stub_dependencies(document_checklist=no_documents_required())
    activities = OnboardingActivities(deps)
    controller = FaultController()
    lossy_transition = faulty_activity(
        activities.transition_onboarding_request,
        name="transition_onboarding_request",
        mode=FaultMode.COMMIT_THEN_TIMEOUT,
        controller=controller,
    )
    methods = [
        lossy_transition if m.__name__ == "transition_onboarding_request" else m
        for m in activities.activity_methods()
    ]

    async with onboarding_workflow(deps, activities=methods, retry_max_attempts=3) as (
        _,
        handle,
        request_id,
    ):
        result = await handle.result()
        detail = await _detail(handle)

    transitions = len(FORWARD_PATH) - 1
    assert result.final_status == "ACTIVE"
    assert controller.fault_count("transition_onboarding_request") == transitions
    assert controller.call_count("transition_onboarding_request") == 2 * transitions

    events = await read_onboarding_events(request_id)
    await assert_transitions(request_id, FORWARD_PATH)
    # The workflow recorded the event the first, committed attempt created.
    assert [t["event_id"] for t in detail["transitions"]] == [str(e.id) for e in events]


async def test_dependency_retried_after_it_took_effect_does_not_repeat_transitions():
    creator = StubAccountCreator()
    deps = stub_dependencies(document_checklist=no_documents_required(), account_creator=creator)
    activities = OnboardingActivities(deps)
    controller = FaultController()
    lossy_create = faulty_activity(
        activities.create_accounts,
        name="create_onboarding_accounts",
        mode=FaultMode.COMMIT_THEN_TIMEOUT,
        controller=controller,
    )
    methods = [
        lossy_create if m.__name__ == "create_accounts" else m for m in activities.activity_methods()
    ]

    async with onboarding_workflow(deps, activities=methods) as (_, handle, request_id):
        result = await handle.result()
        detail = await _detail(handle)

    rid = str(request_id)
    assert result.final_status == "ACTIVE"
    assert creator.calls == [("create_accounts", rid), ("create_accounts", rid)]
    assert detail["account_ids"] == [f"{rid}:account:1"]
    await assert_transitions(request_id, FORWARD_PATH)


# ── inactivity ────────────────────────────────────────────────────────────────


async def test_system_activity_does_not_reset_customer_inactivity():
    verifier = StubEntityVerifier()
    checklist = StubDocumentChecklist(required=(LICENCE,))
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=checklist)

    async with onboarding_workflow(deps) as (env, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))
        detail = await _detail(handle)
        collection_started = datetime.fromisoformat(detail["transitions"][-1]["occurred_at"])
        deadline = detail["inactivity_deadline"]
        assert datetime.fromisoformat(deadline) == collection_started + timedelta(days=30)
        assert detail["last_customer_activity_at"] is None

        await env.sleep(timedelta(days=20))
        # System-originated signals — a late verification result and a document for
        # another request — are not customer actions on this request.
        await handle.signal(
            OnboardingWorkflow.kyb_result_received, verifier.result_for(rid, NormalisedResult.VERIFIED)
        )
        await handle.signal(
            OnboardingWorkflow.document_submitted, checklist.submission(str(uuid.uuid4()), LICENCE)
        )
        detail = await _detail(handle)
        assert detail["inactivity_deadline"] == deadline
        assert detail["last_customer_activity_at"] is None

        result = await handle.result()
        detail = await _detail(handle)

    assert result.final_status == "ABANDONED"
    abandoned_at = datetime.fromisoformat(detail["transitions"][-1]["occurred_at"])
    assert timedelta(days=30) <= abandoned_at - collection_started < timedelta(days=30, minutes=1)
    assert checklist.calls == [("check", rid)]
    assert (await read_onboarding_request(request_id)).status == S.ABANDONED


async def test_customer_activity_moves_the_abandonment_point():
    checklist = StubDocumentChecklist(required=(OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, LICENCE))
    deps = stub_dependencies(document_checklist=checklist)

    async with onboarding_workflow(deps) as (env, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))

        await env.sleep(timedelta(days=25))
        first = checklist.submission(rid, OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION, 1)
        checklist.record(first)
        await handle.signal(OnboardingWorkflow.document_submitted, first)

        async def _recorded() -> bool:
            d = await _detail(handle)
            return d["last_customer_activity_at"] is not None and d["waiting_on"] == "customer"

        await wait_for(_recorded, what="customer activity recorded")
        activity_at = datetime.fromisoformat((await _detail(handle))["last_customer_activity_at"])

        result = await handle.result()
        detail = await _detail(handle)

    assert result.final_status == "ABANDONED"
    abandoned_at = datetime.fromisoformat(detail["transitions"][-1]["occurred_at"])
    assert timedelta(days=30) <= abandoned_at - activity_at < timedelta(days=30, minutes=1)
    request = await read_onboarding_request(request_id)
    assert request.status == S.ABANDONED


@pytest.mark.parametrize(
    ("screening_result", "final_status"),
    [
        (OnboardingScreeningResult.CLEAR, "ACTIVE"),
        (OnboardingScreeningResult.HARD_BLOCK, "REJECTED"),
    ],
)
async def test_terminal_onboarding_is_never_abandoned(screening_result, final_status):
    checklist = StubDocumentChecklist(required=(LICENCE,))
    deps = stub_dependencies(
        document_checklist=checklist, screener=StubScreener(result=screening_result)
    )

    async with onboarding_workflow(deps) as (env, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))
        licence = checklist.submission(rid, LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)

        result = await handle.result()
        events_at_end = len(await read_onboarding_events(request_id))

        await env.sleep(timedelta(days=60))
        description = await handle.describe()
        status = await current_status(handle)

    assert result.final_status == final_status
    assert description.status is not None and description.status.name == "COMPLETED"
    assert status["status"] == final_status and status["waiting_on"] is None
    request = await read_onboarding_request(request_id)
    assert request.status == OnboardingRequestStatus(final_status)
    assert len(await read_onboarding_events(request_id)) == events_at_end
    assert all(e.to_status != "ABANDONED" for e in await read_onboarding_events(request_id))


# ── queries ───────────────────────────────────────────────────────────────────


async def test_current_status_reports_state_and_next_action_at_every_wait():
    verifier = StubEntityVerifier(outcome=NormalisedResult.PENDING)
    checklist = StubDocumentChecklist(required=(LICENCE,))
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(
        entity_verifier=verifier, document_checklist=checklist, compliance_approver=approver
    )

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)

        assert await wait_until_status(
            handle, "provider", _waiting_on("entity_verification_provider")
        ) == {
            "status": "ENTITY_VERIFICATION_IN_PROGRESS",
            "waiting_on": "entity_verification_provider",
            "next_customer_action": None,
            "missing_document_types": [],
        }

        await handle.signal(
            OnboardingWorkflow.kyb_result_received,
            verifier.result_for(rid, NormalisedResult.REQUIRES_MANUAL_REVIEW),
        )
        assert await wait_until_status(handle, "review", _waiting_on("manual_review")) == {
            "status": "UNDER_REVIEW",
            "waiting_on": "manual_review",
            "next_customer_action": None,
            "missing_document_types": [],
        }

        await handle.signal(
            OnboardingWorkflow.kyb_result_received, verifier.result_for(rid, NormalisedResult.VERIFIED)
        )
        assert await wait_until_status(handle, "customer", _waiting_on("customer")) == {
            "status": "DOCUMENT_COLLECTION_IN_PROGRESS",
            "waiting_on": "customer",
            "next_customer_action": "submit_documents",
            "missing_document_types": ["LICENCE"],
        }

        licence = checklist.submission(rid, LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)
        assert await wait_until_status(handle, "compliance", _waiting_on("compliance")) == {
            "status": "PENDING_COMPLIANCE_APPROVAL",
            "waiting_on": "compliance",
            "next_customer_action": None,
            "missing_document_types": [],
        }

        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(rid, OnboardingComplianceDecision.APPROVED),
        )
        await handle.result()
        assert await current_status(handle) == {
            "status": "ACTIVE",
            "waiting_on": None,
            "next_customer_action": None,
            "missing_document_types": [],
        }


#: Exactly the fields ``onboarding_detail`` is meant to expose. A new field has to be
#: added here deliberately, which is the point: nothing reaches the query by accident.
EXPECTED_DETAIL_FIELDS = {
    "onboarding_request_id",
    "status",
    "waiting_on",
    "rejection_category",
    "entity_verification_vendor_id",
    "entity_verification_reference",
    "entity_verification_outcome",
    "ubo_owner_references",
    "ubo_owners_mapped",
    "received_document_ids",
    "missing_document_types",
    "last_customer_activity_at",
    "inactivity_deadline",
    "screening_reference",
    "screening_result",
    "risk_rating_reference",
    "risk_rating",
    "compliance_approval_request_id",
    "compliance_decision",
    "account_ids",
    "user_reference",
    "completion_notification_reference",
    "transitions",
}


async def test_onboarding_detail_exposes_only_the_intended_workflow_safe_fields():
    checklist = StubDocumentChecklist(required=(LICENCE,))
    approver = StubComplianceApprover(
        decision=OnboardingComplianceDecision.REJECTED, reason="reviewer notes that stay private"
    )
    deps = stub_dependencies(document_checklist=checklist, compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", _waiting_on("customer"))
        waiting = await _detail(handle)

        licence = checklist.submission(rid, LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)
        await handle.result()
        final = await _detail(handle)

    for detail in (waiting, final):
        assert set(detail) == EXPECTED_DETAIL_FIELDS
        assert set(detail["transitions"][0]) == {"from_status", "to_status", "occurred_at", "event_id"}
        serialised = json.dumps(detail)
        for sensitive in (
            SEEDED_LEGAL_NAME,
            SEEDED_REGISTRATION_NUMBER,
            SEEDED_TAX_IDENTIFICATION_NUMBER,
            "Fixture Street",
            "fixture-initial-user",
            "reviewer notes that stay private",
        ):
            assert sensitive not in serialised

    assert waiting["status"] == "DOCUMENT_COLLECTION_IN_PROGRESS"
    assert waiting["missing_document_types"] == ["LICENCE"]
    assert waiting["inactivity_deadline"] is not None
    assert waiting["screening_result"] is None and waiting["compliance_decision"] is None

    assert final["status"] == "REJECTED"
    assert final["rejection_category"] == "COMPLIANCE_REJECTION"
    assert final["compliance_decision"] == "REJECTED"
    assert final["inactivity_deadline"] is None
    assert final["waiting_on"] is None
    assert final["account_ids"] == [] and final["user_reference"] is None


async def test_onboarding_detail_matches_persisted_transitions():
    deps = stub_dependencies(document_checklist=no_documents_required())

    async with onboarding_workflow(deps) as (_, handle, request_id):
        await handle.result()
        detail = await _detail(handle)

    events = await read_onboarding_events(request_id)
    assert [
        (t["from_status"], t["to_status"], t["event_id"]) for t in detail["transitions"]
    ] == [(e.from_status, e.to_status, str(e.id)) for e in events]
