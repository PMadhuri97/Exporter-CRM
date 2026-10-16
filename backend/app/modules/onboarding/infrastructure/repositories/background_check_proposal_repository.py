"""Repository for ``background_check_proposal`` and its resolution (maker-checker).

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and both
tables' triggers refuse them at the database.

**Flushes, never commits.** ``BackgroundCheckService`` holds the company row
``FOR UPDATE`` and commits once. "One open proposal per company" is the service's rule
under that lock: *open* means "no resolution row", which no constraint can see.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import Select, func, or_, select
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
        status: str | None,
        exclude_proposer: str | None = None,
        reviewed_by: str | None = None,
        since: datetime | None = None,
        proposal_ids: Collection[uuid.UUID] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[QueueRow], int]:
        """Proposals of every company, each with its company's name.

        ``status`` is ``OPEN`` or an outcome; ``None`` is every status, which only the
        reviewed-by listing wants — one person's own work reads as a sequence, and
        splitting it by outcome would hide the proposal they are still waiting on.

        Ordered oldest first for the open queue — the longest-waiting at the top —
        and newest first otherwise, which is also what a history reads as.

        ``exclude_proposer`` drops one user's own proposals; ``reviewed_by`` keeps only
        the proposals that user had a hand in, as either the proposer or the one who
        resolved it; ``since`` bounds how far back it reaches; ``proposal_ids`` keeps
        only those (a page already chosen).
        """
        conditions = []
        if proposal_ids is not None:
            conditions.append(BackgroundCheckProposal.id.in_(list(proposal_ids)))
        if status == STATUS_OPEN:
            conditions.append(BackgroundCheckProposalResolution.id.is_(None))
        elif status is not None:
            conditions.append(BackgroundCheckProposalResolution.outcome == status)
        if exclude_proposer is not None:
            conditions.append(BackgroundCheckProposal.created_by != exclude_proposer)
        if reviewed_by is not None:
            # Both sides of maker-checker. A proposal this person proposed is their
            # work whatever became of it, and one they approved or rejected is their
            # work even though somebody else wrote it.
            conditions.append(
                or_(
                    BackgroundCheckProposal.created_by == reviewed_by,
                    BackgroundCheckProposalResolution.created_by == reviewed_by,
                )
            )
        if since is not None:
            # On the proposal's own date, not the resolution's, so a row keeps its place
            # in the list when it is approved rather than jumping to the top.
            conditions.append(BackgroundCheckProposal.created_at >= since)

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
