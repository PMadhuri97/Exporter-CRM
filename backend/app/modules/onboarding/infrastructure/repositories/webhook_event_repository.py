from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.webhook_event import WebhookEvent
from app.platform.database.adapters.repository import BaseRepository


class WebhookEventRepository(BaseRepository[WebhookEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(WebhookEvent, session)

    async def get_by_dedup_key(self, dedup_key: str) -> WebhookEvent | None:
        result = await self.session.execute(
            select(WebhookEvent).where(WebhookEvent.dedup_key == dedup_key)
        )
        return result.scalar_one_or_none()
