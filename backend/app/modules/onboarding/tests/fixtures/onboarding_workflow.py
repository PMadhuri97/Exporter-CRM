"""Harness for running the onboarding workflow in tests.

Wraps the platform Temporal fixtures (``app.platform.workflow.tests.fixtures``) with
what every onboarding workflow test needs: a fresh onboarding request, a worker
running the real activities over a stub dependency set, and helpers for waiting on
and asserting the workflow's progress. Synchronisation is always on durable state —
a query result or a persisted row — never on elapsed time.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from itertools import pairwise
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from app.modules.onboarding.application.activities import OnboardingActivities
from app.modules.onboarding.domain.entities.orchestration_enums import OnboardingRequestStatus
from app.modules.onboarding.domain.workflow_dependencies import OnboardingWorkflowDependencies
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    create_onboarding_request,
    read_onboarding_events,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubDocumentChecklist,
)
from app.modules.onboarding.workflows.onboarding_workflow import (
    OnboardingWorkflow,
    OnboardingWorkflowInput,
    workflow_id_for,
)
from app.platform.workflow.tests.fixtures.temporal_env import (
    new_task_queue,
    run_worker,
    start_time_skipping_env,
    wait_for,
)

S = OnboardingRequestStatus

#: Every status of a successful onboarding, in order.
FORWARD_PATH: list[OnboardingRequestStatus] = [
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


def no_documents_required() -> StubDocumentChecklist:
    return StubDocumentChecklist(required=())


@asynccontextmanager
async def running_worker(
    client: Client,
    task_queue: str,
    deps: OnboardingWorkflowDependencies,
    *,
    activities: list[Any] | None = None,
) -> AsyncIterator[None]:
    """A worker for the onboarding workflow, with ``activities`` replacing the
    defaults built from ``deps`` when given."""
    async with run_worker(
        client,
        task_queue=task_queue,
        workflows=[OnboardingWorkflow],
        activities=activities or OnboardingActivities(deps).activity_methods(),
    ):
        yield


async def start_onboarding(
    client: Client, task_queue: str, request_id: uuid.UUID, **input_overrides: Any
) -> WorkflowHandle:
    return await client.start_workflow(
        OnboardingWorkflow.run,
        OnboardingWorkflowInput(onboarding_request_id=str(request_id), **input_overrides),
        id=workflow_id_for(str(request_id)),
        task_queue=task_queue,
    )


@asynccontextmanager
async def onboarding_workflow(
    deps: OnboardingWorkflowDependencies,
    *,
    activities: list[Any] | None = None,
    **input_overrides: Any,
) -> AsyncIterator[tuple[WorkflowEnvironment, WorkflowHandle, uuid.UUID]]:
    """Yield ``(env, handle, request_id)``: a time-skipping server, a worker, and a
    started onboarding workflow for a freshly created request."""
    request_id = await create_onboarding_request()
    task_queue = new_task_queue("onboarding")
    async with await start_time_skipping_env() as env:
        async with running_worker(env.client, task_queue, deps, activities=activities):
            handle = await start_onboarding(env.client, task_queue, request_id, **input_overrides)
            yield env, handle, request_id


async def current_status(handle: WorkflowHandle) -> dict:
    return await handle.query("current_status")


async def wait_until_status(
    handle: WorkflowHandle, what: str, check: Callable[[dict], bool]
) -> dict:
    """Poll ``current_status`` until ``check`` holds and return that status.

    A failed query (for instance while a restarted worker is still replaying) is
    treated as not yet.
    """
    seen: dict = {}

    async def _reached() -> bool:
        nonlocal seen
        try:
            seen = await current_status(handle)
        except Exception:
            return False
        return bool(check(seen))

    await wait_for(_reached, what=what)
    return seen


async def assert_transitions(
    request_id: uuid.UUID, path: list[OnboardingRequestStatus]
) -> None:
    """The request's persisted events are exactly one per step of ``path``."""
    events = await read_onboarding_events(request_id)
    assert [(e.from_status, e.to_status) for e in events] == [
        (a.value, b.value) for a, b in pairwise(path)
    ]
