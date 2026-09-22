"""Repository for `kyc_case`."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.kyc_case import KycCase
from app.platform.database.adapters.repository import BaseRepository


class KycCaseRepository(BaseRepository[KycCase]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(KycCase, session)

    async def get_by_case_id(self, case_id: uuid.UUID) -> KycCase | None:
        result = await self.session.execute(select(KycCase).where(KycCase.case_id == case_id))
        return result.scalar_one_or_none()
