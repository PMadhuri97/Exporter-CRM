"""Repository for ``exporter_profile`` rows (EXP-1)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterLifecycleStatus,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.platform.database.adapters.repository import BaseRepository


class ExporterProfileRepository(BaseRepository[ExporterProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterProfile, session)

    async def get_by_customer_id(self, customer_id: uuid.UUID) -> ExporterProfile | None:
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_pan(self, pan: str) -> ExporterProfile | None:
        """The company holding ``pan`` — at most one (``uq_exporter_profile_pan``)."""
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.pan == pan)
        )
        return result.scalar_one_or_none()

    async def other_holders_of_gstins(
        self, gstins: Sequence[str], customer_id: uuid.UUID
    ) -> dict[str, list[uuid.UUID]]:
        """For each of ``gstins`` that another company also holds, those
        companies' ids. GSTINs nobody else holds are absent."""
        if not gstins:
            return {}
        result = await self.session.execute(
            select(ExporterGstin.gstin, ExporterGstin.customer_id)
            .where(
                ExporterGstin.gstin.in_(gstins),
                ExporterGstin.customer_id != customer_id,
            )
            .order_by(ExporterGstin.gstin, ExporterGstin.customer_id)
        )
        holders: dict[str, list[uuid.UUID]] = {}
        for gstin, holder in result.all():
            holders.setdefault(gstin, []).append(holder)
        return holders

    async def search(
        self,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        name_contains: str | None = None,
        source: ExporterSource | None = None,
        lifecycle_status: ExporterLifecycleStatus | None = None,
        journey: ExporterJourney | None = None,
        qualification: QualificationState | None = None,
        marker: ExporterMarker | None = None,
        exclude_ended: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfile]:
        """Filtered profile search, newest first.

        ``name_contains`` is a case-insensitive partial match on the name.
        ``gstin`` matches any of a company's GSTINs. ``exclude_ended`` drops
        ``ENDED`` companies — the service decides when (the default working
        list); this query only applies it.
        """
        stmt = select(ExporterProfile)
        if gstin is not None:
            stmt = stmt.where(
                exists().where(
                    ExporterGstin.customer_id == ExporterProfile.customer_id,
                    ExporterGstin.gstin == gstin,
                )
            )
        if pan is not None:
            stmt = stmt.where(ExporterProfile.pan == pan)
        if iec is not None:
            stmt = stmt.where(ExporterProfile.iec == iec)
        if name_contains is not None:
            stmt = stmt.where(ExporterProfile.name.ilike(f"%{name_contains}%"))
        if source is not None:
            stmt = stmt.where(ExporterProfile.source == source)
        if lifecycle_status is not None:
            stmt = stmt.where(ExporterProfile.lifecycle_status == lifecycle_status)
        if journey is not None:
            stmt = stmt.where(ExporterProfile.journey == journey)
        if qualification is not None:
            stmt = stmt.where(ExporterProfile.qualification == qualification)
        if marker is not None:
            stmt = stmt.where(ExporterProfile.marker == marker)
        elif exclude_ended:
            stmt = stmt.where(ExporterProfile.marker != ExporterMarker.ENDED)

        stmt = stmt.order_by(ExporterProfile.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["ExporterProfileRepository"]
