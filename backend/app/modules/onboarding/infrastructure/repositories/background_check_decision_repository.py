"""Repository for ``background_check_decision`` and ``background_check_evidence``.

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and
both tables' triggers refuse them at the database whatever code tries.

**Flushes, never commits.** ``record`` adds one decision and its evidence and
flushes, so the caller — ``BackgroundCheckService`` — can assign the
company's current value and write the history row in the same transaction and
commit once (``history-row.md`` §5; ``background-check.md`` §9).

Reads here are of the background check's own two tables only. Nothing in this module
reads verification's tables; the evidence rows merely carry their ids.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.platform.database.adapters.repository import AppendOnlyRepository


class BackgroundCheckDecisionRepository(AppendOnlyRepository[BackgroundCheckDecision]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BackgroundCheckDecision, session)

    # ── Writes ───────────────────────────────────────────────────────────────

    async def record(
        self,
        decision: BackgroundCheckDecision,
        evidence: Sequence[BackgroundCheckEvidence] = (),
    ) -> BackgroundCheckDecision:
        """Add one decision and its evidence snapshot, flush, and return the decision.

        The evidence rows are attached to ``decision`` here, so a caller cannot pin
        evidence to a different decision by mistake. Flush only — the caller commits.
        The database refuses anything the contract forbids (an illegal move, a missing
        reason, ``CLEAR`` without risk, a forked or broken chain); the service is
        expected to have refused it first.
        """
        if decision.id is None:
            decision.id = uuid.uuid4()
        self.session.add(decision)
        for item in evidence:
            item.decision_id = decision.id
            self.session.add(item)
        await self.session.flush()
        return decision

    # ── Reads ────────────────────────────────────────────────────────────────

    async def latest_for_company(self, company_id: uuid.UUID) -> BackgroundCheckDecision | None:
        """The chain head: the company's decision no other decision supersedes.

        Defined by the chain, not by timestamps — `decided_at` is transaction time and
        two decisions in one transaction would tie. `None` if the company has none.
        """
        successor = aliased(BackgroundCheckDecision)
        result = await self.session.execute(
            select(BackgroundCheckDecision).where(
                BackgroundCheckDecision.company_id == company_id,
                ~select(successor.id)
                .where(successor.supersedes_decision_id == BackgroundCheckDecision.id)
                .exists(),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, company_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[BackgroundCheckDecision], int]:
        """One company's decisions, newest first, and how many there are in total.

        Served by ``ix_background_check_decision_company_recent``; ``id`` breaks the
        transaction-time tie deterministically.
        """
        rows = await self.session.execute(
            select(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id == company_id)
            .order_by(
                BackgroundCheckDecision.decided_at.desc(), BackgroundCheckDecision.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id == company_id)
        )
        return list(rows.scalars().all()), int(total or 0)

    async def evidence_for(
        self, decision_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[BackgroundCheckEvidence]]:
        """Each decision's evidence snapshot, keyed by decision id, in one query.

        Every requested id is a key, with an empty list when the decision pinned
        nothing. Rows are in a stable order (kind, then id).
        """
        snapshots: dict[uuid.UUID, list[BackgroundCheckEvidence]] = {
            decision_id: [] for decision_id in decision_ids
        }
        if not snapshots:
            return snapshots
        result = await self.session.execute(
            select(BackgroundCheckEvidence)
            .where(BackgroundCheckEvidence.decision_id.in_(list(snapshots)))
            .order_by(BackgroundCheckEvidence.kind, BackgroundCheckEvidence.id)
        )
        for item in result.scalars().all():
            snapshots[item.decision_id].append(item)
        return snapshots


__all__ = ["BackgroundCheckDecisionRepository"]
