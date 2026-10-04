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
from collections.abc import Collection, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.platform.database.adapters.repository import AppendOnlyRepository


class ExporterLifecycleHistoryRepository(AppendOnlyRepository[ExporterLifecycleHistory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterLifecycleHistory, session)

    @staticmethod
    def _about_company(customer_id: uuid.UUID, *, include_deals_as_buyer: bool):
        """Which rows count as "this company's history" (task 2.7).

        Every row carries the ``customer_id`` of the company it is **about**, and for
        a deal row that is the **seller** — the deal hangs off the selling company.
        So a company that is the buyer on a deal sees nothing of that deal on its own
        timeline, which was right while a buyer was a ``deal_buyer`` row and is wrong
        now that a buyer is a company record: being bought from is part of a
        company's story (plan P4-4).

        With ``include_deals_as_buyer`` the predicate also admits the ``deal``-dimension
        rows of deals this company buys on. Matched through ``deal.buyer_company_id``
        with a subquery rather than by writing a second history row per event: one
        event, one row, is what makes the log reconstructible, and two rows would have
        to be kept in step forever on an append-only table where a mistake cannot be
        edited out.

        **Only the ``deal`` and ``trade`` dimensions**, and that restriction is the
        whole subtlety here. Other dimensions carry a ``deal_id`` too — a
        ``conversation`` row when seam S1 moves a seller to ``READY_NOW`` on opening a
        deal, a ``verification`` row for a check run in a deal's context — but those are
        about the *seller's* own state and merely mention the deal. Admitting every row
        that carries the id would put the seller's conversation gauge on the buyer's
        timeline, where it would read as the buyer's own. The buyer's own rows,
        including its own checks, already arrive through ``customer_id``.

        ``trade`` rows are the other kind: an invoice for the deal and how it was paid
        are about the trade between the two companies, so the buyer is a party to them
        (``trade-history.md`` §6, plan P5-3/P5-4: "on the seller's timeline, and the
        buyer's by read-side union"; R-23). Past trade recorded with no deal carries no
        ``deal_id`` and stays on the seller's timeline.

        Used by both the page and its count, so the two cannot disagree about what
        the company's history is.
        """
        from app.modules.onboarding.domain import history_dimensions
        from app.modules.onboarding.domain.entities.deal import Deal

        own = ExporterLifecycleHistory.customer_id == customer_id
        if not include_deals_as_buyer:
            return own
        bought_on = and_(
            ExporterLifecycleHistory.dimension.in_(
                (history_dimensions.DEAL, history_dimensions.TRADE)
            ),
            ExporterLifecycleHistory.deal_id.in_(
                select(Deal.id).where(Deal.buyer_company_id == customer_id)
            ),
        )
        return or_(own, bought_on)

    async def list_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        dimension: str | None = None,
        exclude_dimensions: Collection[str] = (),
        include_deals_as_buyer: bool = False,
        limit: int | None = None,
        offset: int = 0,
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
        ``uuid4``). Several write paths do write more than one row in a
        transaction — a qualification outcome and the journey move it causes, a
        deal and seam S1's conversation move, a clearance and the move to
        ``CUSTOMER`` — so a reader must not rely on the order between rows that
        share a timestamp; each row's ``from``/``to`` says what it was.

        ``exclude_dimensions`` leaves whole dimensions out — the history route
        uses it to keep from DEVELOPER what decision D8 keeps from it elsewhere.

        ``include_deals_as_buyer`` adds the rows of deals this company buys on; see
        ``_about_company``. It composes with ``exclude_dimensions``, so D8 still
        applies to rows that arrive this way: a dimension DEVELOPER may not see on
        its own company is not readable through a deal either.
        """
        stmt = select(ExporterLifecycleHistory).where(
            self._about_company(
                customer_id, include_deals_as_buyer=include_deals_as_buyer
            )
        )
        if dimension is not None:
            stmt = stmt.where(ExporterLifecycleHistory.dimension == dimension)
        if exclude_dimensions:
            stmt = stmt.where(ExporterLifecycleHistory.dimension.not_in(exclude_dimensions))
        stmt = stmt.order_by(
            ExporterLifecycleHistory.created_at.desc(),
            ExporterLifecycleHistory.id.desc(),
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        dimension: str | None = None,
        exclude_dimensions: Collection[str] = (),
        include_deals_as_buyer: bool = False,
    ) -> int:
        """How many rows the matching `list_by_customer` call would return in
        total, so a paged response can say how much more there is.

        ``include_deals_as_buyer`` must match the ``list_by_customer`` call it is
        counting for, or the page and the total describe different things."""
        stmt = select(func.count()).select_from(ExporterLifecycleHistory).where(
            self._about_company(
                customer_id, include_deals_as_buyer=include_deals_as_buyer
            )
        )
        if dimension is not None:
            stmt = stmt.where(ExporterLifecycleHistory.dimension == dimension)
        if exclude_dimensions:
            stmt = stmt.where(ExporterLifecycleHistory.dimension.not_in(exclude_dimensions))
        return int(await self.session.scalar(stmt) or 0)

    async def list_by_deal(
        self,
        deal_id: uuid.UUID,
        *,
        exclude_dimensions: Collection[str] = (),
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ExporterLifecycleHistory]:
        """One deal's history, newest first.

        Served by `ix_exporter_lifecycle_history_deal_recent`, which is partial
        on `deal_id IS NOT NULL` — this query never asks for NULL, so the
        partial index covers it exactly.

        Nothing here checks that the deal is real: an unknown deal is an empty
        page, the same answer as a deal with no history yet.
        """
        stmt = select(ExporterLifecycleHistory).where(ExporterLifecycleHistory.deal_id == deal_id)
        if exclude_dimensions:
            stmt = stmt.where(ExporterLifecycleHistory.dimension.not_in(exclude_dimensions))
        stmt = stmt.order_by(
            ExporterLifecycleHistory.created_at.desc(),
            ExporterLifecycleHistory.id.desc(),
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_deal(
        self, deal_id: uuid.UUID, *, exclude_dimensions: Collection[str] = ()
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ExporterLifecycleHistory)
            .where(ExporterLifecycleHistory.deal_id == deal_id)
        )
        if exclude_dimensions:
            stmt = stmt.where(ExporterLifecycleHistory.dimension.not_in(exclude_dimensions))
        return int(await self.session.scalar(stmt) or 0)

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
