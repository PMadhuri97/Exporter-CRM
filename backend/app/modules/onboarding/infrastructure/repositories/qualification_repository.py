"""Queries for qualification criteria, results and outcomes — **owner:
Developer 2** (L2-09, L2-10).

Reads and appends only. The three versioned/decision tables are append-only in
the database; nothing here updates or deletes, and there is no method that
could.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.qualification import (
    QualificationCriterion,
    QualificationOutcome,
    QualificationReasonCode,
    QualificationResult,
)


class QualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: object) -> None:
        """Insert one row and flush, so its id and server defaults are set."""
        self.session.add(row)
        await self.session.flush()

    # ── Criteria ─────────────────────────────────────────────────────────────

    async def current_criteria(self) -> list[QualificationCriterion]:
        """The latest version of every criterion, by key."""
        latest = (
            select(
                QualificationCriterion.key,
                func.max(QualificationCriterion.version).label("version"),
            )
            .group_by(QualificationCriterion.key)
            .subquery()
        )
        result = await self.session.execute(
            select(QualificationCriterion)
            .join(
                latest,
                (QualificationCriterion.key == latest.c.key)
                & (QualificationCriterion.version == latest.c.version),
            )
            .order_by(QualificationCriterion.key)
        )
        return list(result.scalars().all())

    async def versions(self, key: str) -> list[QualificationCriterion]:
        """Every version of one criterion, oldest first."""
        result = await self.session.execute(
            select(QualificationCriterion)
            .where(QualificationCriterion.key == key)
            .order_by(QualificationCriterion.version)
        )
        return list(result.scalars().all())

    async def latest_version(self, key: str) -> QualificationCriterion | None:
        result = await self.session.execute(
            select(QualificationCriterion)
            .where(QualificationCriterion.key == key)
            .order_by(QualificationCriterion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Reason codes ─────────────────────────────────────────────────────────

    async def reason_codes(self) -> list[QualificationReasonCode]:
        result = await self.session.execute(
            select(QualificationReasonCode).order_by(QualificationReasonCode.code)
        )
        return list(result.scalars().all())

    # ── Results and outcomes ─────────────────────────────────────────────────

    async def results_for(self, customer_id: uuid.UUID) -> list[QualificationResult]:
        """Every result for a company, newest first."""
        result = await self.session.execute(
            select(QualificationResult)
            .where(QualificationResult.customer_id == customer_id)
            .order_by(QualificationResult.recorded_at.desc(), QualificationResult.id.desc())
        )
        return list(result.scalars().unique().all())

    async def outcomes_for(self, customer_id: uuid.UUID) -> list[QualificationOutcome]:
        """Every outcome for a company, newest first."""
        result = await self.session.execute(
            select(QualificationOutcome)
            .where(QualificationOutcome.customer_id == customer_id)
            .order_by(QualificationOutcome.decided_at.desc(), QualificationOutcome.id.desc())
        )
        return list(result.scalars().all())

    async def latest_outcome(self, customer_id: uuid.UUID) -> QualificationOutcome | None:
        """The end of the company's outcome chain: the outcome no other
        outcome supersedes."""
        superseded = select(QualificationOutcome.supersedes_outcome_id).where(
            QualificationOutcome.customer_id == customer_id,
            QualificationOutcome.supersedes_outcome_id.is_not(None),
        )
        result = await self.session.execute(
            select(QualificationOutcome).where(
                QualificationOutcome.customer_id == customer_id,
                QualificationOutcome.id.not_in(superseded),
            )
        )
        return result.scalar_one_or_none()

    async def company_for_partner_reference(
        self, source: str, reference: str
    ) -> uuid.UUID | None:
        """The company a partner delivery with this reference was recorded
        for, read from the outcome's history row (where the reference is kept).
        Read-only use of the shared history log."""
        result = await self.session.execute(
            select(ExporterLifecycleHistory.customer_id)
            .where(
                ExporterLifecycleHistory.dimension == "qualification",
                ExporterLifecycleHistory.event_metadata["source"].astext == source,
                ExporterLifecycleHistory.event_metadata["partner_reference"].astext == reference,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def results_by_id(self, ids: Sequence[uuid.UUID]) -> list[QualificationResult]:
        if not ids:
            return []
        result = await self.session.execute(
            select(QualificationResult).where(QualificationResult.id.in_(ids))
        )
        return list(result.scalars().unique().all())


__all__ = ["QualificationRepository"]
