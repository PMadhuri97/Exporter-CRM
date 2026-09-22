import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.domain.entities.notifications import NotificationEvent, WebhookStatus
from app.platform.database.adapters.repository import BaseRepository


class NotificationEventRepository(BaseRepository[NotificationEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(NotificationEvent, session)

    async def list_by_transaction(
        self, transaction_id: uuid.UUID
    ) -> Sequence[NotificationEvent]:
        result = await self.session.execute(
            select(NotificationEvent)
            .where(NotificationEvent.transaction_id == transaction_id)
            .order_by(NotificationEvent.created_at.desc())
        )
        return result.scalars().all()

    async def list_pending(self) -> Sequence[NotificationEvent]:
        result = await self.session.execute(
            select(NotificationEvent)
            .where(NotificationEvent.status == WebhookStatus.PENDING)
            .order_by(NotificationEvent.created_at.asc())
        )
        return result.scalars().all()

    async def list_deliverable(self) -> Sequence[NotificationEvent]:
        """Events still eligible for a delivery attempt: never-attempted (PENDING)
        or a retryable prior failure (FAILED). EXHAUSTED/DELIVERED are terminal.
        FIFO so the webhook queue drains fairly."""
        result = await self.session.execute(
            select(NotificationEvent)
            .where(
                NotificationEvent.status.in_(
                    (WebhookStatus.PENDING, WebhookStatus.FAILED)
                )
            )
            .order_by(NotificationEvent.created_at.asc())
        )
        return result.scalars().all()
