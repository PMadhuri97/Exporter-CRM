"""Repository for ``exporter_profile`` rows (EXP-1)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database.adapters.repository import BaseRepository


class ExporterProfileRepository(BaseRepository[ExporterProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterProfile, session)

    async def get_by_customer_id(self, customer_id: uuid.UUID) -> ExporterProfile | None:
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        customer_ids: Sequence[uuid.UUID] | None = None,
        source: ExporterSource | None = None,
        lifecycle_status: ExporterLifecycleStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfile]:
        """Filtered profile search, newest first.

        ``customer_ids`` restricts the result to a set already resolved
        elsewhere — ``ExporterProfileService.search_profiles`` passes the
        companies whose name matched. This query reads ``exporter_profile``
        only; the company's name is not its concern.
        """
        stmt = select(ExporterProfile)
        if gstin is not None:
            stmt = stmt.where(ExporterProfile.gstin == gstin)
        if pan is not None:
            stmt = stmt.where(ExporterProfile.pan == pan)
        if iec is not None:
            stmt = stmt.where(ExporterProfile.iec == iec)
        if source is not None:
            stmt = stmt.where(ExporterProfile.source == source)
        if lifecycle_status is not None:
            stmt = stmt.where(ExporterProfile.lifecycle_status == lifecycle_status)
        if customer_ids is not None:
            stmt = stmt.where(ExporterProfile.customer_id.in_(customer_ids))

        stmt = stmt.order_by(ExporterProfile.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["ExporterProfileRepository"]
