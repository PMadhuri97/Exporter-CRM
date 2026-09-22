"""Repository for `kyb_vendor_result` rows (Epic 4.1, S7).

Not to be confused with `KybVendorRegistration` (the registry of *which*
vendors exist, S1T4) — this table holds the per-onboarding verification
*results* returned by a vendor for a specific `onboarding_request`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.kyb_vendor_result import KybVendorResult
from app.platform.database.adapters.repository import BaseRepository


class KybVendorResultRepository(BaseRepository[KybVendorResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(KybVendorResult, session)

    async def list_by_onboarding_request(
        self, onboarding_request_id: uuid.UUID
    ) -> list[KybVendorResult]:
        result = await self.session.execute(
            select(KybVendorResult).where(
                KybVendorResult.onboarding_request_id == onboarding_request_id
            )
        )
        return list(result.scalars().all())


__all__ = ["KybVendorResultRepository"]
