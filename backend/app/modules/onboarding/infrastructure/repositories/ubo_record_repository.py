"""Repository for `ubo_record` rows (Epic 4.1, S7)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.platform.database.adapters.repository import BaseRepository


class UboRecordRepository(BaseRepository[UboRecord]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(UboRecord, session)

    async def list_by_onboarding_request(
        self, onboarding_request_id: uuid.UUID
    ) -> list[UboRecord]:
        result = await self.session.execute(
            select(UboRecord).where(
                UboRecord.onboarding_request_id == onboarding_request_id
            )
        )
        return list(result.scalars().all())


__all__ = ["UboRecordRepository"]
