"""E9 persistence service for screening review state and bank findings."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.screening_review import (
    BankActivityFinding,
    ScreeningReviewItem,
)


class ScreeningReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_review_items(self, customer_id: uuid.UUID) -> list[ScreeningReviewItem]:
        result = await self._db.execute(
            select(ScreeningReviewItem)
            .where(ScreeningReviewItem.customer_id == customer_id)
            .order_by(ScreeningReviewItem.item_key.asc())
        )
        return list(result.scalars().all())

    async def upsert_review_item(
        self,
        customer_id: uuid.UUID,
        *,
        item_key: str,
        status: str,
        comment: str | None,
        actor_id: str,
    ) -> ScreeningReviewItem:
        result = await self._db.execute(
            select(ScreeningReviewItem).where(
                ScreeningReviewItem.customer_id == customer_id,
                ScreeningReviewItem.item_key == item_key,
            )
        )
        item = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if item is None:
            item = ScreeningReviewItem(
                customer_id=customer_id,
                item_key=item_key,
                status=status,
                comment=comment,
                reviewed_by=actor_id,
                reviewed_at=now,
            )
            self._db.add(item)
        else:
            item.status = status
            item.comment = comment
            item.reviewed_by = actor_id
            item.reviewed_at = now
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def list_bank_findings(self, customer_id: uuid.UUID) -> list[BankActivityFinding]:
        result = await self._db.execute(
            select(BankActivityFinding)
            .where(BankActivityFinding.customer_id == customer_id)
            .order_by(BankActivityFinding.detected_at.desc())
        )
        return list(result.scalars().all())


__all__ = ["ScreeningReviewService"]
