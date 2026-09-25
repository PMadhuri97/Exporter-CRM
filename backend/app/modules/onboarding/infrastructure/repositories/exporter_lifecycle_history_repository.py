"""
Repository for ``exporter_lifecycle_history`` rows.

Append-only: ``AppendOnlyRepository`` exposes no update or delete, and
``trg_exporter_lifecycle_history_append_only`` enforces the same rule at the
database — the same pairing ``OnboardingEventRepository`` and
``ExporterActivityRepository`` already use for this module's other append-only
tables.

``list_by_customer`` is newest-first because every caller so far wants "what
happened to this exporter most recently"; ``find_transition`` answers "did this
exporter ever cross this edge, and who moved it", which is what a downstream
completion hook (ANER-4.2-S1T2) asks.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.platform.database.adapters.repository import AppendOnlyRepository


class ExporterLifecycleHistoryRepository(AppendOnlyRepository[ExporterLifecycleHistory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterLifecycleHistory, session)

    async def list_by_customer(
        self, customer_id: uuid.UUID, *, dimension: str | None = None
    ) -> Sequence[ExporterLifecycleHistory]:
        """One exporter's history, newest first, optionally one dimension only.

        The table became the shared CRM history log in migration 0013, so an
        unfiltered read now returns the journey, every gauge and every deal
        mixed together — which is what a company timeline wants and what a
        single gauge panel does not. `dimension` narrows it, served by
        `ix_exporter_lifecycle_history_dimension_recent`, whose column order and
        direction mirror this query so the ordering comes from the index rather
        than a sort.

        ``created_at`` defaults to ``now()`` — transaction start time — so two
        rows written in one transaction share a timestamp. The ``id`` tie-break
        makes that case deterministic, not chronological (``id`` is a random
        ``uuid4``). Every write path today commits one row per transaction, so
        it does not arise; a caller writing several rows in one transaction
        must not rely on this order between them.
        """
        stmt = select(ExporterLifecycleHistory).where(
            ExporterLifecycleHistory.customer_id == customer_id
        )
        if dimension is not None:
            stmt = stmt.where(ExporterLifecycleHistory.dimension == dimension)
        result = await self.session.execute(
            stmt.order_by(
                ExporterLifecycleHistory.created_at.desc(),
                ExporterLifecycleHistory.id.desc(),
            )
        )
        return result.scalars().all()

    async def find_transition(
        self,
        customer_id: uuid.UUID,
        *,
        from_status: str,
        to_status: str,
    ) -> ExporterLifecycleHistory | None:
        """The first time this exporter crossed this edge, if it ever did.

        First rather than latest: the lifecycle permits a return trip
        (``ACTIVE -> SUSPENDED -> ACTIVE``, ``COMPLIANCE_REVIEW ->
        DATA_COLLECTION`` and back), so an edge can be crossed more than once,
        and a consumer asking "when was this exporter onboarded" means the
        first time.
        """
        result = await self.session.execute(
            select(ExporterLifecycleHistory)
            .where(
                ExporterLifecycleHistory.customer_id == customer_id,
                ExporterLifecycleHistory.from_status == from_status,
                ExporterLifecycleHistory.to_status == to_status,
            )
            .order_by(
                ExporterLifecycleHistory.created_at.asc(),
                ExporterLifecycleHistory.id.asc(),
            )
            .limit(1)
        )
        return result.scalars().first()


__all__ = ["ExporterLifecycleHistoryRepository"]
