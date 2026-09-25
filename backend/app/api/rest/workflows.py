"""
Workflow router — observability endpoints for running Temporal workflows.

Thin-slice: read-only; management operations (terminate, cancel) come later.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.configuration.config import settings
from app.shared.exceptions import AnerBaseException, NotFoundError

logger = structlog.get_logger(__name__)
router = APIRouter()

# Workflow status exposes a settlement's internal execution state, and
# `/start` launches one. Both are operational tools, so both are gated to
# staff. Before this they checked only that the caller was logged in, so any
# account — including a fresh self-service API_USER — could start a
# settlement workflow for any transaction id it could guess.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


class WorkflowStatusResponse(BaseModel):
    transaction_id: uuid.UUID
    workflow_id: str
    status: str
    history_length: int | None = None
    current_state: dict[str, Any] | None = None


@router.get(
    "/{transaction_id}",
    response_model=WorkflowStatusResponse,
    summary="Get Temporal workflow status for a transaction",
    responses={
        200: {"model": WorkflowStatusResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Workflow not found or Temporal not enabled"},
        503: {"description": "Temporal unavailable"},
    },
)
async def get_workflow_status(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
) -> WorkflowStatusResponse:
    if not settings.TEMPORAL_ENABLED:
        raise NotFoundError(
            "Temporal workflows are not enabled. Set TEMPORAL_ENABLED=true."
        )

    try:
        from app.platform.workflow.adapters.client import get_temporal_client

        client = await get_temporal_client()
        handle = client.get_workflow_handle(str(transaction_id))
        desc = await handle.describe()
    except Exception as exc:
        err = str(exc)
        if "not found" in err.lower() or "does not exist" in err.lower():
            raise NotFoundError(f"No workflow found for transaction {transaction_id}")
        raise AnerBaseException(
            detail=f"Temporal unavailable: {err}",
            error_code="TEMPORAL_UNAVAILABLE",
            status_code=503,
        )

    try:
        current_state = await handle.query("current_state")  # type: ignore[arg-type]
    except Exception:
        current_state = None

    return WorkflowStatusResponse(
        transaction_id=transaction_id,
        workflow_id=desc.id,
        status=desc.status.name if desc.status else "UNKNOWN",
        history_length=desc.history_length,
        current_state=current_state,
    )


@router.post(
    "/{transaction_id}/start",
    response_model=WorkflowStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually start (or re-attach to) a SettlementWorkflow",
    responses={
        202: {"model": WorkflowStatusResponse, "description": "Workflow started or already running"},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Transaction not found"},
        503: {"description": "Temporal unavailable"},
    },
)
async def start_workflow(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
) -> WorkflowStatusResponse:
    """
    Manually trigger SettlementWorkflow for a transaction.
    Idempotent: if the workflow already exists, returns its current status.
    """
    if not settings.TEMPORAL_ENABLED:
        raise NotFoundError(
            "Temporal workflows are not enabled. Set TEMPORAL_ENABLED=true."
        )

    try:
        from app.modules.orchestration.application.models import SettlementWorkflowInput
        from app.modules.orchestration.workflows.settlement_workflow import SettlementWorkflow
        from app.modules.payments.infrastructure.repository import TransactionRepository
        from app.platform.database.services import AsyncSessionLocal
        from app.platform.workflow.adapters.client import get_temporal_client

        async with AsyncSessionLocal() as db:
            tx_repo = TransactionRepository(db)
            tx = await tx_repo.get_by_transaction_id(transaction_id)
            if tx is None:
                raise NotFoundError(f"Transaction {transaction_id} not found")

            client = await get_temporal_client()
            handle = await client.start_workflow(
                SettlementWorkflow.run,
                SettlementWorkflowInput(
                    transaction_id=str(tx.transaction_id),
                    sender_customer_id=str(tx.sender_customer_id),
                    beneficiary_customer_id=str(tx.beneficiary_customer_id),
                    amount_minor=int(tx.amount),
                    source_currency=tx.source_currency,
                    destination_currency=tx.destination_currency,
                ),
                id=str(transaction_id),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            desc = await handle.describe()

        return WorkflowStatusResponse(
            transaction_id=transaction_id,
            workflow_id=desc.id,
            status=desc.status.name if desc.status else "RUNNING",
            history_length=desc.history_length,
        )

    except NotFoundError:
        raise
    except AnerBaseException:
        raise
    except Exception as exc:
        raise AnerBaseException(
            detail=f"Failed to start workflow: {exc}",
            error_code="TEMPORAL_START_FAILED",
            status_code=503,
        )
