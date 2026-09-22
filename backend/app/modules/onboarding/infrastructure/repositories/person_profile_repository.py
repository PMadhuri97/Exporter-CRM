"""Repository for `person_profile`. Handles PII — never log a returned instance."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.person_profile import PersonProfile
from app.platform.database.adapters.repository import BaseRepository


class PersonProfileRepository(BaseRepository[PersonProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PersonProfile, session)

    async def get_by_case_id(self, case_id: uuid.UUID) -> PersonProfile | None:
        result = await self.session.execute(
            select(PersonProfile).where(PersonProfile.case_id == case_id)
        )
        return result.scalar_one_or_none()
