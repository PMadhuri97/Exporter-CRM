"""Repository for ``background_check_proposal`` and its resolution — **owner: Developer
1** (maker-checker, plan P3-1a/b).

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and both
tables' triggers refuse them at the database.

**Flushes, never commits.** ``BackgroundCheckService`` holds the company row
``FOR UPDATE`` and commits once. "One open proposal per company" is the service's rule
under that lock: *open* means "no resolution row", which no constraint can see.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.background_check_proposal import (
    BackgroundCheckProposal,
    BackgroundCheckProposalResolution,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database.adapters.repository import AppendOnlyRepository

ProposalRow = tuple[BackgroundCheckProposal, BackgroundCheckProposalResolution | None]
#: A proposal, its resolution and its company's name — the cross-company queue's row.
QueueRow = tuple[BackgroundCheckProposal, BackgroundCheckProposalResolution | None, str | None]

#: The statuses a list can be filtered by: open, or one resolution outcome.
STATUS_OPEN = "OPEN"


class BackgroundCheckProposalRepository(AppendOnlyRepository[BackgroundCheckProposal]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BackgroundCheckProposal, session)

    # ── Writes (flush only) ──────────────────────────────────────────────────

    async def add_proposal(self, proposal: BackgroundCheckProposal) -> BackgroundCheckProposal:
        self.session.add(proposal)
        await self.session.flush()
        return proposal

    async def add_resolution(
        self, resolution: BackgroundCheckProposalResolution
    ) -> BackgroundCheckProposalResolution:
        self.session.add(resolution)
        await self.session.flush()
        return resolution

    # ── Reads ────────────────────────────────────────────────────────────────

    def _with_resolution(self) -> Select:
        return select(BackgroundCheckProposal, BackgroundCheckProposalResolution).outerjoin(
            BackgroundCheckProposalResolution,
            BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
        )

    async def open_for_company(self, company_id: uuid.UUID) -> BackgroundCheckProposal | None:
        """The company's open proposal — the one with no resolution — or ``None``."""
        return await self.session.scalar(
            select(BackgroundCheckProposal)
            .outerjoin(
                BackgroundCheckProposalResolution,
                BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
            )
            .where(
                BackgroundCheckProposal.company_id == company_id,
                BackgroundCheckProposalResolution.id.is_(None),
            )
            .order_by(BackgroundCheckProposal.created_at.desc(), BackgroundCheckProposal.id.desc())
            .limit(1)
        )

    async def get_for_company(
        self, company_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> ProposalRow | None:
        """One proposal with its resolution, only if it belongs to this company."""
        row = (
            await self.session.execute(
                self._with_resolution().where(
                    BackgroundCheckProposal.id == proposal_id,
                    BackgroundCheckProposal.company_id == company_id,
                )
            )
        ).first()
        return (row[0], row[1]) if row is not None else None

    async def list_for_company(
        self, company_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ProposalRow], int]:
        """One company's proposals, newest first, and how many there are."""
        rows = (
            await self.session.execute(
                self._with_resolution()
                .where(BackgroundCheckProposal.company_id == company_id)
                .order_by(
                    BackgroundCheckProposal.created_at.desc(), BackgroundCheckProposal.id.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        total = await self.session.scalar(
            select(func.count())
            .select_from(BackgroundCheckProposal)
            .where(BackgroundCheckProposal.company_id == company_id)
        )
        return [(row[0], row[1]) for row in rows], int(total or 0)

    async def list_across_companies(
        self,
        *,
        status: str,
        exclude_proposer: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[QueueRow], int]:
        """Proposals of every company in ``status`` (``OPEN`` or an outcome), oldest
        first for the open queue — the longest-waiting at the top — newest first
        otherwise; each with its company's name. ``exclude_proposer`` drops one user's
        own proposals ("awaiting **me**")."""
        conditions = []
        if status == STATUS_OPEN:
            conditions.append(BackgroundCheckProposalResolution.id.is_(None))
        else:
            conditions.append(BackgroundCheckProposalResolution.outcome == status)
        if exclude_proposer is not None:
            conditions.append(BackgroundCheckProposal.created_by != exclude_proposer)

        newest_first = status != STATUS_OPEN
        order = (
            (BackgroundCheckProposal.created_at.desc(), BackgroundCheckProposal.id.desc())
            if newest_first
            else (BackgroundCheckProposal.created_at.asc(), BackgroundCheckProposal.id.asc())
        )
        rows = (
            await self.session.execute(
                select(
                    BackgroundCheckProposal,
                    BackgroundCheckProposalResolution,
                    ExporterProfile.name,
                )
                .outerjoin(
                    BackgroundCheckProposalResolution,
                    BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
                )
                .join(
                    ExporterProfile,
                    ExporterProfile.customer_id == BackgroundCheckProposal.company_id,
                )
                .where(*conditions)
                .order_by(*order)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        total = await self.session.scalar(
            select(func.count())
            .select_from(BackgroundCheckProposal)
            .outerjoin(
                BackgroundCheckProposalResolution,
                BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
            )
            .where(*conditions)
        )
        return [(row[0], row[1], row[2]) for row in rows], int(total or 0)


__all__ = ["STATUS_OPEN", "BackgroundCheckProposalRepository", "ProposalRow", "QueueRow"]
