"""Repository for ``deal_buyer`` — **owner: Developer 3B** (L3-06).

One row per deal, enforced by ``uq_deal_buyer_deal_id``. Setting a buyer on a deal
that already has one is an **update of that row**, not a second row — which is why
this exposes ``get_for_deal`` rather than a list: a caller that could get two
buyers back would have to decide which one is "the" buyer, and the handover
payload has no room for that ambiguity (architecture §3.6).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.platform.database.adapters.repository import BaseRepository


class DealBuyerRepository(BaseRepository[DealBuyer]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(DealBuyer, session)

    async def get_for_deal(self, deal_id: uuid.UUID) -> DealBuyer | None:
        result = await self.session.execute(
            select(DealBuyer).where(DealBuyer.deal_id == deal_id)
        )
        return result.scalar_one_or_none()
