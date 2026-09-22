"""
The onboarding workflow survives a Temporal server restart.

Uses the platform's persistent local Temporal dev server, whose state lives in a file
that outlives a stop, so a restarted server holds the same workflow histories. Each
run drives a fresh onboarding to a point with real progress behind it — entity
verified, owners mapped, collection started and waiting on the customer — then stops
the worker, kills the server, restarts both, and lets the original execution finish.

What "resumed" is taken to mean, and asserted:

* the same execution (same run id) completes; no new one is started;
* nothing completed before the restart is done again — the verification and UBO
  dependencies are not called a second time, and no transition event is repeated;
* the workflow's replayed state is intact: it is still waiting on the customer for
  the same missing document, and accepts the document sent after the restart.

Opt-in, like the settlement resilience suite, because it starts and stops a real
server ten times: ``RUN_RESILIENCE_TESTS=1``. Synchronisation is on query results
and persisted rows, never on elapsed time.
"""
from __future__ import annotations

import os

import pytest

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingDocumentType,
    OnboardingRequestStatus,
)
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    create_onboarding_request,
    read_onboarding_events,
    read_onboarding_request,
)
from app.modules.onboarding.tests.fixtures.onboarding_workflow import (
    FORWARD_PATH,
    assert_transitions,
    running_worker,
    start_onboarding,
    wait_until_status,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubDocumentChecklist,
    stub_dependencies,
)
from app.modules.onboarding.workflows.onboarding_workflow import (
    OnboardingWorkflow,
    workflow_id_for,
)
from app.platform.workflow.tests.fixtures.temporal_env import (
    PersistentTemporalServer,
    new_task_queue,
    wait_until_running,
)

RUNS = 10
LICENCE = OnboardingDocumentType.LICENCE

#: Statuses the request has passed through when the restart happens.
BEFORE_RESTART = FORWARD_PATH[: FORWARD_PATH.index(OnboardingRequestStatus.DOCUMENT_COLLECTION_IN_PROGRESS) + 1]

resilience = pytest.mark.skipif(
    os.getenv("RUN_RESILIENCE_TESTS") != "1",
    reason="onboarding restart suite is opt-in; set RUN_RESILIENCE_TESTS=1 to run",
)


@resilience
@pytest.mark.temporal_persistent
@pytest.mark.timeout(1800)
async def test_onboarding_resumes_after_temporal_restart_10x():
    server = PersistentTemporalServer()
    try:
        await server.start()
        for run in range(1, RUNS + 1):
            checklist = StubDocumentChecklist(required=(LICENCE,))
            deps = stub_dependencies(document_checklist=checklist)
            request_id = await create_onboarding_request()
            rid = str(request_id)
            workflow_id = workflow_id_for(rid)
            task_queue = new_task_queue("onboarding-restart")

            # ── before: progress to document collection, waiting on the customer ──
            async with running_worker(server.client, task_queue, deps):
                handle = await start_onboarding(server.client, task_queue, request_id)
                run_id = await wait_until_running(handle)
                await wait_until_status(
                    handle, "waiting on customer", lambda s: s["waiting_on"] == "customer"
                )

            await assert_transitions(request_id, BEFORE_RESTART)
            dependency_calls_before = {
                "entity_verifier": list(deps.entity_verifier.calls),
                "ubo_mapper": list(deps.ubo_mapper.calls),
            }

            # ── kill and restart the server on the same persisted state ───────────
            await server.stop()
            await server.start()

            # ── after: a new worker on the restarted server finishes the same run ──
            async with running_worker(server.client, task_queue, deps):
                handle = server.client.get_workflow_handle_for(OnboardingWorkflow.run, workflow_id)
                status = await wait_until_status(
                    handle, "replayed and waiting on customer", lambda s: s["waiting_on"] == "customer"
                )
                assert status["status"] == "DOCUMENT_COLLECTION_IN_PROGRESS", f"run {run}"
                assert status["missing_document_types"] == ["LICENCE"], f"run {run}"
                # Nothing was re-executed by the replay.
                await assert_transitions(request_id, BEFORE_RESTART)

                licence = checklist.submission(rid, LICENCE)
                checklist.record(licence)
                await handle.signal(OnboardingWorkflow.document_submitted, licence)
                result = await handle.result()
                description = await handle.describe()

            assert result.final_status == "ACTIVE", f"run {run}"
            assert description.run_id == run_id, f"run {run}: a new execution was started"
            assert deps.entity_verifier.calls == dependency_calls_before["entity_verifier"], f"run {run}"
            assert deps.ubo_mapper.calls == dependency_calls_before["ubo_mapper"], f"run {run}"
            assert len(deps.completion_notifier.calls) == 1, f"run {run}"

            await assert_transitions(request_id, FORWARD_PATH)
            events = await read_onboarding_events(request_id)
            assert len({(e.from_status, e.to_status) for e in events}) == len(events), f"run {run}"
            assert (await read_onboarding_request(request_id)).status == OnboardingRequestStatus.ACTIVE
    finally:
        await server.stop()
