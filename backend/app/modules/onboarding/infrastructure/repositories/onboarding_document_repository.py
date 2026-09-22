"""Repository for `onboarding_document` rows (Epic 4.1, S7)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_document import OnboardingDocument
from app.platform.database.adapters.repository import BaseRepository


class OnboardingDocumentRepository(BaseRepository[OnboardingDocument]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OnboardingDocument, session)

    async def list_by_onboarding_request(
        self, onboarding_request_id: uuid.UUID
    ) -> list[OnboardingDocument]:
        result = await self.session.execute(
            select(OnboardingDocument).where(
                OnboardingDocument.onboarding_request_id == onboarding_request_id
            )
        )
        return list(result.scalars().all())


__all__ = ["OnboardingDocumentRepository"]
