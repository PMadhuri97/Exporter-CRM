"""Starting the onboarding workflow for an onboarding request.

Configuration is read here, outside the workflow, and handed to it as input so the
workflow itself stays deterministic.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def start_onboarding_workflow(onboarding_request_id: str) -> str:
    """Start the onboarding workflow for a request and return its workflow id.

    Idempotent: the workflow id is derived from the request id, so a second start
    for the same request finds the workflow already running and returns its id.
    """
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from app.modules.onboarding.workflows.onboarding_workflow import (
        OnboardingWorkflow,
        OnboardingWorkflowInput,
        workflow_id_for,
    )
    from app.platform.configuration.config import get_settings
    from app.platform.workflow.adapters.client import get_temporal_client

    settings = get_settings()
    client = await get_temporal_client()
    workflow_id = workflow_id_for(onboarding_request_id)
    try:
        await client.start_workflow(
            OnboardingWorkflow.run,
            OnboardingWorkflowInput(
                onboarding_request_id=onboarding_request_id,
                inactivity_timeout_seconds=settings.ONBOARDING_INACTIVITY_TIMEOUT_DAYS * 86_400,
                retry_max_attempts=settings.TEMPORAL_MAX_RETRY_ATTEMPTS,
                retry_initial_interval_seconds=settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS,
            ),
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "onboarding_workflow_already_started",
            onboarding_request_id=onboarding_request_id,
            workflow_id=workflow_id,
        )
        return workflow_id

    logger.info(
        "onboarding_workflow_started",
        onboarding_request_id=onboarding_request_id,
        workflow_id=workflow_id,
    )
    return workflow_id
