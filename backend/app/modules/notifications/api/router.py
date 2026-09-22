from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.api.schemas import NotificationResponse
from app.modules.notifications.application.services import NotificationService
from app.platform.database.services import get_db

router = APIRouter()


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(
    transaction_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    service = NotificationService(db)
    if transaction_id is not None:
        events = await service.get_by_transaction(transaction_id)
    else:
        events = await service.list_pending()
    return [NotificationResponse.model_validate(event) for event in events]


@router.post("/process-pending", response_model=list[NotificationResponse])
async def process_pending_notifications(
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    service = NotificationService(db)
    events = await service.process_pending(limit=limit)
    return [NotificationResponse.model_validate(event) for event in events]
