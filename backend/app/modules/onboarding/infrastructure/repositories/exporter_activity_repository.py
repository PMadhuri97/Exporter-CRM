"""Repository for ``exporter_activity`` rows (EXP-1, Piece 2). Append-only:
``AppendOnlyRepository`` exposes no update or delete, and
``trg_exporter_activity_append_only`` enforces the same rule at the
database — mirroring ``OnboardingEventRepository``'s sibling pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
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
        display name is resolved via a single outer join against a "most
        recent `OnboardingRequest` per `customer_id`" subquery, the same
        `OnboardingRequest.legal_name` `ExporterProfileService.
        search_profiles` already joins to — never a second, per-row query
        (this is the acceptance criterion: no N+1). A bare Lead whose
        `OnboardingRequest` (if it has one at all) carries no name yet joins
        to `NULL`, same as `search_profiles`'s own "nothing to match" case.

        Ordered soonest-due first (overdue items sort to the very front,
        since their `due_at` is furthest in the past) — the natural reading
        order for "what needs attention".
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

        stmt = (
            select(ExporterActivity, latest_name.c.legal_name)
            .outerjoin(latest_name, latest_name.c.customer_id == ExporterActivity.customer_id)
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
