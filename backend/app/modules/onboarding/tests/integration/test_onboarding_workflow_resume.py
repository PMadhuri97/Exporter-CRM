"""
Resuming an onboarding from its persisted lifecycle status.

An execution can fail with the request part-way through its lifecycle. Starting the
workflow again must continue from the persisted status: completed steps are not
repeated, the step the request was in is re-run safely, no transition event is
written twice, and a request that has already ended is not restarted.

Earlier progress is set up either through the transition service directly — which
is exactly what an earlier execution leaves behind — or by genuinely failing an
execution and starting a new one under the same workflow id. Dependencies are the
deterministic stubs; the database is real.
"""
from __future__ import annotations

import uuid
from itertools import pairwise
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError

from app.modules.onboarding.application.activities import (
    OnboardingActivities,
    TransitionOnboardingRequestInput,
    TransitionOnboardingRequestOutput,
)
from app.modules.onboarding.application.onboarding_transition_service import (
    OnboardingTransitionService,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.modules.onboarding.exceptions import OnboardingDependencyUnavailableError
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    create_onboarding_request,
    read_onboarding_events,
    read_onboarding_request,
)
from app.modules.onboarding.tests.fixtures.onboarding_workflow import (
    FORWARD_PATH,
    assert_transitions,
    current_status,
    no_documents_required,
    running_worker,
    start_onboarding,
    wait_until_status,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubEntityVerifier,
    StubScreener,
    stub_dependencies,
)
from app.modules.onboarding.workflows.onboarding_workflow import OnboardingWorkflow
from app.platform.database import services as database
from app.platform.workflow.tests.fixtures.temporal_env import (
    new_task_queue,
    start_time_skipping_env,
)
from app.shared.enums.kyb import NormalisedResult

S = OnboardingRequestStatus

#: The dependency each workflow step calls first, in step order.
STEP_DEPENDENCIES = [
    "entity_verifier",
    "ubo_mapper",
    "document_checklist",
    "screener",
    "risk_rater",
    "compliance_approver",
    "account_creator",
]


async def _seed(
    path: list[OnboardingRequestStatus],
    *,
    rejection_category: OnboardingRejectionCategory | None = None,
) -> uuid.UUID:
    """A request moved along ``path`` by the transition service, events and all —
    what an earlier execution that got that far leaves behind."""
    request_id = await create_onboarding_request()
    for from_status, to_status in pairwise(path):
        async with database.AsyncSessionLocal() as session:
            await OnboardingTransitionService(session).transition(
                request_id,
                expected_status=from_status,
                to_status=to_status,
                actor_id="earlier-execution",
                rejection_category=rejection_category if to_status == S.REJECTED else None,
            )
    return request_id


def _path_to(status: OnboardingRequestStatus) -> list[OnboardingRequestStatus]:
    return FORWARD_PATH[: FORWARD_PATH.index(status) + 1]


async def _assert_detail_lists_every_event(detail: dict, request_id: uuid.UUID) -> None:
    """``onboarding_detail`` reports every persisted transition — including those an
    earlier execution recorded — each exactly once, in order."""
    events = await read_onboarding_events(request_id)
    assert [
        (t["from_status"], t["to_status"], t["event_id"]) for t in detail["transitions"]
    ] == [(e.from_status, e.to_status, str(e.id)) for e in events]


async def _run(deps, request_id: uuid.UUID, **input_overrides: Any):
    """Run one execution to completion; return ``(result, handle)``."""
    task_queue = new_task_queue("onboarding-resume")
    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps):
            handle = await start_onboarding(env.client, task_queue, request_id, **input_overrides)
            result = await handle.result()
            return result, handle, await handle.query("onboarding_detail")


# ── starting fresh ────────────────────────────────────────────────────────────


async def test_request_in_draft_follows_the_normal_path():
    deps = stub_dependencies(document_checklist=no_documents_required())
    request_id = await create_onboarding_request()

    result, _, detail = await _run(deps, request_id)

    assert result.final_status == "ACTIVE"
    await assert_transitions(request_id, FORWARD_PATH)
    await _assert_detail_lists_every_event(detail, request_id)
    for name in STEP_DEPENDENCIES:
        assert getattr(deps, name).calls, f"{name} was not called"


# ── resuming from a persisted status ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("persisted", "resume_step"),
    [
        # completed statuses: continue with the next step
        (S.ENTITY_VERIFIED, 1),
        (S.UBO_MAPPING_COMPLETE, 2),
        (S.DOCUMENT_COLLECTION_COMPLETE, 3),
        (S.SCREENING_COMPLETE, 4),
        (S.RISK_RATED, 5),
        (S.APPROVED, 6),
        # in-progress statuses: re-run that step
        (S.ENTITY_VERIFICATION_IN_PROGRESS, 0),
        (S.UBO_MAPPING_IN_PROGRESS, 1),
        (S.DOCUMENT_COLLECTION_IN_PROGRESS, 2),
        (S.SCREENING_IN_PROGRESS, 3),
        (S.RISK_RATING_IN_PROGRESS, 4),
        (S.PENDING_COMPLIANCE_APPROVAL, 5),
        (S.ACCOUNT_CREATION_IN_PROGRESS, 6),
    ],
    ids=lambda v: v.value if isinstance(v, OnboardingRequestStatus) else str(v),
)
async def test_resumes_from_the_persisted_status(persisted, resume_step):
    request_id = await _seed(_path_to(persisted))
    deps = stub_dependencies(document_checklist=no_documents_required())

    result, _, detail = await _run(deps, request_id)

    assert result.final_status == "ACTIVE"
    # Steps already behind the request are not repeated...
    for name in STEP_DEPENDENCIES[:resume_step]:
        assert getattr(deps, name).calls == [], f"{name} was repeated"
    # ...and the step it resumed at, and every later one, ran.
    for name in STEP_DEPENDENCIES[resume_step:]:
        assert getattr(deps, name).calls, f"{name} did not run"
    assert len(deps.completion_notifier.calls) == 1

    # One event per transition across both executions: nothing re-applied.
    await assert_transitions(request_id, FORWARD_PATH)
    # The query reports the earlier execution's transitions as well as this one's.
    await _assert_detail_lists_every_event(detail, request_id)


async def test_resume_under_manual_review_waits_for_the_reviewed_result():
    request_id = await _seed([S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.UNDER_REVIEW])
    verifier = StubEntityVerifier(outcome=NormalisedResult.REQUIRES_MANUAL_REVIEW)
    deps = stub_dependencies(entity_verifier=verifier, document_checklist=no_documents_required())

    task_queue = new_task_queue("onboarding-resume")
    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps):
            handle = await start_onboarding(env.client, task_queue, request_id)
            status = await wait_until_status(
                handle, "waiting on manual review", lambda s: s["waiting_on"] == "manual_review"
            )
            assert status["status"] == "UNDER_REVIEW"

            # The resubmission re-established the vendor reference to correlate on.
            await handle.signal(
                OnboardingWorkflow.kyb_result_received,
                verifier.result_for(str(request_id), NormalisedResult.VERIFIED),
            )
            result = await handle.result()

    assert result.final_status == "ACTIVE"
    assert verifier.calls == [("submit", str(request_id))]
    await assert_transitions(
        request_id, [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.UNDER_REVIEW, *FORWARD_PATH[2:]]
    )


# ── a real failure, then a new execution ──────────────────────────────────────


async def test_failed_execution_is_resumed_without_repeating_completed_steps():
    screener = StubScreener()
    screener.fail_next(OnboardingDependencyUnavailableError("screening"))
    deps = stub_dependencies(document_checklist=no_documents_required(), screener=screener)
    request_id = await create_onboarding_request()
    task_queue = new_task_queue("onboarding-resume")

    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps):
            first = await start_onboarding(env.client, task_queue, request_id)
            with pytest.raises(WorkflowFailureError):
                await first.result()
            assert (await read_onboarding_request(request_id)).status == S.SCREENING_IN_PROGRESS
            calls_before = {name: list(getattr(deps, name).calls) for name in STEP_DEPENDENCIES}

            # Same workflow id; the failed run is closed, so a new run starts.
            second = await start_onboarding(env.client, task_queue, request_id)
            result = await second.result()
            first_run = first.result_run_id
            second_run = second.result_run_id

    assert result.final_status == "ACTIVE"
    assert first_run != second_run
    for name in ("entity_verifier", "ubo_mapper", "document_checklist"):
        assert getattr(deps, name).calls == calls_before[name], f"{name} was repeated"
    # The step that failed is the one retried.
    assert len(screener.calls) == 2
    await assert_transitions(request_id, FORWARD_PATH)


async def test_transition_committed_by_a_failed_execution_is_not_written_again():
    """The move into screening commits, then its activity fails for good. The workflow
    never learned the transition happened; the next execution must not repeat it."""
    deps = stub_dependencies(document_checklist=no_documents_required())
    activities = OnboardingActivities(deps)
    failed_once: set[str] = set()

    @activity.defn(name="transition_onboarding_request")
    async def transition_then_fail(
        inp: TransitionOnboardingRequestInput,
    ) -> TransitionOnboardingRequestOutput:
        output = await activities.transition_onboarding_request(inp)
        if inp.to_status == "SCREENING_IN_PROGRESS" and inp.to_status not in failed_once:
            failed_once.add(inp.to_status)
            raise ApplicationError("response lost after commit", non_retryable=True)
        return output

    methods = [
        transition_then_fail if m.__name__ == "transition_onboarding_request" else m
        for m in activities.activity_methods()
    ]
    request_id = await create_onboarding_request()
    task_queue = new_task_queue("onboarding-resume")

    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps, activities=methods):
            first = await start_onboarding(env.client, task_queue, request_id)
            with pytest.raises(WorkflowFailureError):
                await first.result()
            assert (await read_onboarding_request(request_id)).status == S.SCREENING_IN_PROGRESS
            events_before = await read_onboarding_events(request_id)

            second = await start_onboarding(env.client, task_queue, request_id)
            result = await second.result()
            detail = await second.query("onboarding_detail")

    assert result.final_status == "ACTIVE"
    assert events_before[-1].to_status == "SCREENING_IN_PROGRESS"
    assert len(deps.screener.calls) == 1
    await assert_transitions(request_id, FORWARD_PATH)
    # The committed-but-unacknowledged transition is reported once, with its own event.
    await _assert_detail_lists_every_event(detail, request_id)


# ── terminal requests ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "category"),
    [
        (FORWARD_PATH, None),
        ([S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.REJECTED], OnboardingRejectionCategory.KYB_FAILURE),
        ([*_path_to(S.DOCUMENT_COLLECTION_IN_PROGRESS), S.ABANDONED], None),
    ],
    ids=["active", "rejected", "abandoned"],
)
async def test_terminal_request_is_not_restarted(path, category):
    request_id = await _seed(path, rejection_category=category)
    events_before = len(await read_onboarding_events(request_id))
    deps = stub_dependencies()

    task_queue = new_task_queue("onboarding-resume")
    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps):
            handle = await start_onboarding(env.client, task_queue, request_id)
            result = await handle.result()
            status = await current_status(handle)
            detail = await handle.query("onboarding_detail")

    final = path[-1]
    assert result.final_status == final.value
    assert result.rejection_category == (category.value if category else None)
    assert status["status"] == final.value and status["waiting_on"] is None
    # Nothing new was applied, but the query still reports the whole lifecycle.
    assert len(detail["transitions"]) == len(path) - 1
    await _assert_detail_lists_every_event(detail, request_id)
    for name in [*STEP_DEPENDENCIES, "customer_user_provisioner", "completion_notifier"]:
        assert getattr(deps, name).calls == [], f"{name} was called for an ended onboarding"
    assert len(await read_onboarding_events(request_id)) == events_before
    assert (await read_onboarding_request(request_id)).status == final


async def test_starting_a_completed_onboarding_again_changes_nothing():
    deps = stub_dependencies(document_checklist=no_documents_required())
    request_id = await create_onboarding_request()
    task_queue = new_task_queue("onboarding-resume")

    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps):
            first = await start_onboarding(env.client, task_queue, request_id)
            assert (await first.result()).final_status == "ACTIVE"
            calls_after_first = {name: len(getattr(deps, name).calls) for name in STEP_DEPENDENCIES}

            again = await start_onboarding(env.client, task_queue, request_id)
            result = await again.result()

    assert result.final_status == "ACTIVE"
    assert {name: len(getattr(deps, name).calls) for name in STEP_DEPENDENCIES} == calls_after_first
    assert len(deps.completion_notifier.calls) == 1
    await assert_transitions(request_id, FORWARD_PATH)
