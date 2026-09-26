"""Repository for ``exporter_activity`` rows (EXP-1, Piece 2). Append-only:
``AppendOnlyRepository`` exposes no update or delete, and
``trg_exporter_activity_append_only`` enforces the same rule at the
database — mirroring ``OnboardingEventRepository``'s sibling pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database.adapters.repository import AppendOnlyRepository


class ExporterActivityRepository(AppendOnlyRepository[ExporterActivity]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterActivity, session)

    async def list_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        activity_type: ExporterActivityType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterActivity]:
        """Most recent first — a relationship-history feed is read newest-on-top."""
        stmt = select(ExporterActivity).where(ExporterActivity.customer_id == customer_id)
        if activity_type is not None:
            stmt = stmt.where(ExporterActivity.activity_type == activity_type)
        stmt = stmt.order_by(ExporterActivity.occurred_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending(
        self,
        *,
        actor_id: str | None = None,
        activity_type: ExporterActivityType | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[ExporterActivity, str | None]]:
        """Every activity that carries a `due_at` (the append-only log's own
        stand-in for "this is a follow-up item"), across every exporter,
        optionally scoped to one `actor_id` — the cross-exporter
        pending/follow-up list (Piece 2).

        Returns `(activity, exporter_display_name)` pairs in one query: the
        display name is the company's own `exporter_profile.name`, joined
        once — never a second, per-row query (this is the acceptance
        criterion: no N+1). A company created without a name joins to `NULL`.
        (Migration 0014 moved the name onto the company record; this join
        used to reach the legacy `onboarding_request` table for it.)

        Ordered soonest-due first (overdue items sort to the very front,
        since their `due_at` is furthest in the past) — the natural reading
        order for "what needs attention".
        """
        stmt = (
            select(ExporterActivity, ExporterProfile.name)
            .outerjoin(ExporterProfile, ExporterProfile.customer_id == ExporterActivity.customer_id)
            .where(ExporterActivity.due_at.isnot(None))
        )
        if actor_id is not None:
            stmt = stmt.where(ExporterActivity.actor_id == actor_id)
        if activity_type is not None:
            stmt = stmt.where(ExporterActivity.activity_type == activity_type)
        if due_before is not None:
            stmt = stmt.where(ExporterActivity.due_at < due_before)
        if due_after is not None:
            stmt = stmt.where(ExporterActivity.due_at > due_after)

        stmt = stmt.order_by(ExporterActivity.due_at.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


__all__ = ["ExporterActivityRepository"]
