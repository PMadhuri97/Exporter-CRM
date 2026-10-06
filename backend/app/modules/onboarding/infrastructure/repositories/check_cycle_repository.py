"""Repository for ``check_cycle``.

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and
``trg_check_cycle_append_only`` refuses both at the database.

**Flushes, never commits.** The caller owns the transaction and the company lock:

* a writer of an input (a verification result, a screening answer) holds the company
  row ``FOR SHARE`` and asks :meth:`current_or_initial` for the cycle to stamp;
* ``BackgroundCheckService`` holds it ``FOR UPDATE`` for a decision and for starting a
  new cycle (:meth:`add_next`), so a new cycle and an input can never interleave.

Two writers holding ``FOR SHARE`` may both find a company with no cycle yet and both
create its cycle 1; the insert is ``ON CONFLICT DO NOTHING`` on
``uq_check_cycle_company_number`` and re-reads, so both stamp the same row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.check_cycle import (
    CYCLE_SOURCE_FIRST_INPUT,
    CheckCycle,
    CheckCycleKind,
)
from app.platform.database.adapters.repository import AppendOnlyRepository


def in_cycle(cycle_column, cycle: CheckCycle | None) -> ColumnElement[bool]:
    """The rows of ``cycle`` in a table with a nullable ``cycle_id`` column.

    The legacy read rule lives here, once: a ``NULL`` ``cycle_id`` is the company's
    cycle 1. So cycle 1 is its own rows **and** the ``NULL`` ones; any later cycle is
    only its own rows. ``cycle`` ``None`` — a company with no cycle row yet — means
    every row (all of them are legacy, or there are none).
    """
    if cycle is None:
        return true()
    if cycle.number == 1:
        return or_(cycle_column == cycle.id, cycle_column.is_(None))
    return cycle_column == cycle.id


def resolved_cycle_id(
    stored: uuid.UUID | None, initial: CheckCycle | None
) -> uuid.UUID | None:
    """A row's cycle, with the legacy rule applied: ``NULL`` reads as cycle 1's id."""
    if stored is not None:
        return stored
    return initial.id if initial is not None else None


class CheckCycleRepository(AppendOnlyRepository[CheckCycle]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CheckCycle, session)

    # ── Reads ────────────────────────────────────────────────────────────────

    async def list_for_company(self, company_id: uuid.UUID) -> list[CheckCycle]:
        """Every cycle of one company, cycle 1 first."""
        result = await self.session.execute(
            select(CheckCycle)
            .where(CheckCycle.company_id == company_id)
            .order_by(CheckCycle.number.asc())
        )
        return list(result.scalars().all())

    async def current_for_company(self, company_id: uuid.UUID) -> CheckCycle | None:
        """The company's highest-numbered cycle, or ``None`` before it has one."""
        return await self.session.scalar(
            select(CheckCycle)
            .where(CheckCycle.company_id == company_id)
            .order_by(CheckCycle.number.desc())
            .limit(1)
        )

    async def get_for_company(
        self, company_id: uuid.UUID, cycle_id: uuid.UUID
    ) -> CheckCycle | None:
        """One cycle, only if it belongs to this company."""
        return await self.session.scalar(
            select(CheckCycle).where(
                CheckCycle.id == cycle_id, CheckCycle.company_id == company_id
            )
        )

    async def by_ids(self, cycle_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, CheckCycle]:
        ids = {cycle_id for cycle_id in cycle_ids if cycle_id is not None}
        if not ids:
            return {}
        result = await self.session.execute(select(CheckCycle).where(CheckCycle.id.in_(ids)))
        return {cycle.id: cycle for cycle in result.scalars().all()}

    # ── Writes (flush only) ──────────────────────────────────────────────────

    async def current_or_initial(
        self, company_id: uuid.UUID, *, actor_id: str, source_ref: str | None, at: datetime
    ) -> CheckCycle:
        """The cycle a new input or decision belongs to — creating cycle 1 if the company
        has none yet. The caller holds the company row (``FOR SHARE`` or ``FOR UPDATE``).
        """
        current = await self.current_for_company(company_id)
        if current is not None:
            return current
        await self.session.execute(
            insert(CheckCycle)
            .values(
                id=uuid.uuid4(),
                company_id=company_id,
                number=1,
                kind=CheckCycleKind.INITIAL.value,
                reason=None,
                started_at=at,
                rules_version=None,
                created_by=actor_id,
                source=CYCLE_SOURCE_FIRST_INPUT,
                source_ref=source_ref,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "number"])
        )
        created = await self.current_for_company(company_id)
        if created is None:  # pragma: no cover — the insert or a concurrent one made it
            raise RuntimeError(f"company {company_id} has no check cycle after creating one")
        return created

    async def add_next(
        self,
        company_id: uuid.UUID,
        *,
        previous: CheckCycle,
        kind: CheckCycleKind,
        reason: str,
        actor_id: str,
        source: str,
        source_ref: str | None,
        rules_version: str,
        at: datetime,
    ) -> CheckCycle:
        """Insert the cycle after ``previous``. The caller holds the company ``FOR UPDATE``.

        ``source_ref`` names what the start caused, where there is something to name —
        the reopen decision a Re-KYC on a ``CLEAR`` company records in the same
        transaction (its id is chosen before either row is written)."""
        cycle = CheckCycle(
            id=uuid.uuid4(),
            company_id=company_id,
            number=previous.number + 1,
            kind=kind.value,
            reason=reason,
            started_at=at,
            rules_version=rules_version,
            created_by=actor_id,
            source=source,
            source_ref=source_ref,
        )
        return await self.create(cycle)


__all__ = ["CheckCycleRepository", "in_cycle", "resolved_cycle_id"]
