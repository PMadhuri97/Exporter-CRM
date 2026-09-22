"""Repository for ``exporter_profile`` rows (EXP-1)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
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
        legal_name_customer_ids: Sequence[uuid.UUID] | None = None,
        source: ExporterSource | None = None,
        lifecycle_status: ExporterLifecycleStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[ExporterProfile, str | None]]:
        """Filtered profile search.

        ``legal_name_customer_ids`` is the set of ``customer_id``s already
        resolved by ``ExporterProfileService.search_profiles`` via a
        case-insensitive ``ILIKE`` match against
        ``OnboardingRequest.legal_name`` — a *different* thing from the
        ``legal_name`` this method itself returns alongside every row (the
        display name for the list, joined here regardless of whether
        ``legal_name_contains`` filtering was requested at all).

        Returns ``(profile, legal_name)`` pairs — the same "most recent
        ``OnboardingRequest`` per ``customer_id``" window-function join
        ``ExporterActivityRepository.list_pending`` already uses for
        ``PendingActivityView.exporter_display_name``, so a list screen never
        needs a second, per-row query (no N+1). ``None`` for a bare Lead with
        no ``OnboardingRequest`` yet.
        """
        latest_request = (
            select(
                OnboardingRequest.customer_id.label("customer_id"),
                OnboardingRequest.legal_name.label("legal_name"),
                func.row_number()
                .over(
                    partition_by=OnboardingRequest.customer_id,
                    order_by=OnboardingRequest.created_at.desc(),
                )
                .label("rn"),
            )
        ).subquery("latest_request")
        latest_name = (
            select(latest_request.c.customer_id, latest_request.c.legal_name)
            .where(latest_request.c.rn == 1)
        ).subquery("latest_name")

        stmt = select(ExporterProfile, latest_name.c.legal_name).outerjoin(
            latest_name, latest_name.c.customer_id == ExporterProfile.customer_id
        )
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
        if legal_name_customer_ids is not None:
            stmt = stmt.where(ExporterProfile.customer_id.in_(legal_name_customer_ids))

        stmt = stmt.order_by(ExporterProfile.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


__all__ = ["ExporterProfileRepository"]
