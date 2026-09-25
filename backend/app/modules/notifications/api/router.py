from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.api.schemas import NotificationResponse
from app.modules.notifications.application.services import NotificationService
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter()

# Notification rows carry customer-facing message content and the transaction
# they belong to, and `process-pending` dispatches them. Both are internal
# operations, so both are gated to staff. Before this, neither route had any
# auth dependency at all: anyone who could reach the port could read the queue
# and trigger delivery.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


@router.get(
    "/",
    response_model=list[NotificationResponse],
    summary="List pending notifications, or a transaction's notifications",
    responses={
        200: {"model": list[NotificationResponse]},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_notifications(
    current_user: Annotated[User, Depends(_STAFF)],
    transaction_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    service = NotificationService(db)
    if transaction_id is not None:
        events = await service.get_by_transaction(transaction_id)
    else:
        events = await service.list_pending()
    return [NotificationResponse.model_validate(event) for event in events]


@router.post(
    "/process-pending",
    response_model=list[NotificationResponse],
    summary="Dispatch the pending notification queue",
    responses={
        200: {"model": list[NotificationResponse]},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def process_pending_notifications(
    current_user: Annotated[User, Depends(_STAFF)],
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    service = NotificationService(db)
    events = await service.process_pending(limit=limit)
    return [NotificationResponse.model_validate(event) for event in events]
