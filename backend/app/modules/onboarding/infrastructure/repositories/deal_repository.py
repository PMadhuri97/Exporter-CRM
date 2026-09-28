"""Repository for ``deal`` — **owner: Developer 3B** (L3-05).

Mutable, unlike the append-only tables in this module: a deal's stage genuinely
changes, and the record of *how* it changed is a history row
(``dimension="deal"``), not a second deal row. So this extends
``BaseRepository`` — but note there is deliberately **no delete path used
anywhere**: ``WITHDRAWN`` is how a deal ends (deal contract §2), and the base
class's ``delete`` is simply never called.

The buyer is loaded with the deal (``lazy="selectin"`` on the relationship), so a
list of deals costs two statements rather than one per row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.platform.database.adapters.repository import BaseRepository


class DealRepository(BaseRepository[Deal]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Deal, session)

    async def get_by_id(self, deal_id: uuid.UUID) -> Deal | None:
        result = await self.session.execute(select(Deal).where(Deal.id == deal_id))
        return result.scalar_one_or_none()

    async def lock_by_id(self, deal_id: uuid.UUID) -> Deal | None:
        """The deal row, locked for the rest of the transaction and read fresh.

        Two concurrent stage moves are then judged one after the other, and the
        second sees the first — so the history can never show two moves out of the
        same stage. The same reason ``ConversationService._lock_profile`` and
        ``QualificationService`` lock.

        ``populate_existing`` matters as much as the lock: without it a row
        already in this session's identity map would be returned from memory, and
        the guard would judge a stale stage.
        """
        result = await self.session.execute(
            select(Deal)
            .where(Deal.id == deal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    def _for_company(self, company_id: uuid.UUID) -> Select[tuple[Deal]]:
        return select(Deal).where(Deal.company_id == company_id)

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        stages: tuple[DealStage, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Deal], int]:
        """One company's deals, newest first, with the total behind the page.

        Newest first because the deal someone is working on is almost always the
        one they just opened; ``ix_deal_company_recent`` serves exactly this.
        """
        statement = self._for_company(company_id)
        if stages:
            statement = statement.where(Deal.stage.in_(stages))

        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        result = await self.session.execute(
            statement.order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def count_for_company(self, company_id: uuid.UUID) -> int:
        """How many deals a company has, at any stage.

        Used by the company panel's header, which wants the number without the
        rows.
        """
        total = await self.session.scalar(
            select(func.count()).select_from(Deal).where(Deal.company_id == company_id)
        )
        return int(total or 0)
