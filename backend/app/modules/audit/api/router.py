"""Audit query API — read-only access to the write-once `audit_events` store.

The audit trail is written by every module through `AuditService.record()`; these
endpoints expose it for compliance review and lifecycle reconstruction. All routes
are read-only — the store is immutable at the database level (no create/update/
delete is offered or possible).
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.api.schemas import AuditEventListResponse, AuditEventResponse
from app.modules.audit.application.services import AuditService
from app.modules.audit.domain.entities.audit import ActorType
from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter()

# The cross-transaction feed is a privileged, platform-wide view.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)


@router.get(
    "/events",
    response_model=AuditEventListResponse,
    summary="Query the audit trail (compliance/admin)",
    description=(
        "Platform-wide, filterable feed of audit events, most recent first. "
        "Filter by event_type, actor_type, transaction_id and/or correlation_id. "
        "Restricted to COMPLIANCE and ADMIN roles."
    ),
    responses={
        200: {"model": AuditEventListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
    },
)
async def query_audit_events(
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    actor_type: ActorType | None = None,
    transaction_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await AuditService(db).query(
        event_type=event_type,
        actor_type=actor_type,
        transaction_id=transaction_id,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/events/{event_id}",
    response_model=AuditEventResponse,
    summary="Get a single audit event",
    responses={
        200: {"model": AuditEventResponse},
        401: {"description": "Unauthorized"},
        404: {"description": "Audit event not found"},
    },
)
async def get_audit_event(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> AuditEventResponse:
    return await AuditService(db).get_event(event_id)


@router.get(
    "/transactions/{transaction_id}",
    response_model=AuditEventListResponse,
    summary="Get the audit trail for a transaction",
    description="All audit events for a transaction, in chronological order.",
    responses={
        200: {"model": AuditEventListResponse},
        401: {"description": "Unauthorized"},
        404: {"description": "Transaction not found"},
    },
)
async def get_transaction_audit_trail(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await AuditService(db).list_for_transaction(
        transaction_id, limit=limit, offset=offset
    )


@router.get(
    "/correlations/{correlation_id}",
    response_model=AuditEventListResponse,
    summary="Trace audit events by correlation ID",
    description=(
        "Every audit event — across all transactions and services — that shares the "
        "given correlation ID, in chronological order."
    ),
    responses={
        200: {"model": AuditEventListResponse},
        401: {"description": "Unauthorized"},
    },
)
async def get_correlation_audit_trail(
    correlation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await AuditService(db).list_for_correlation(
        correlation_id, limit=limit, offset=offset
    )
