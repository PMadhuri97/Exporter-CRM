"""
Repository for `case_state_transition`.

Append-only: `AppendOnlyRepository` exposes no `update` or `delete`, and the
`prevent_mutation()` trigger enforces the same rule at the database.

Created alongside its table. The state machine that calls `create()` lands later;
until then this repository is read-only in practice.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.case_state_transition import CaseStateTransition
from app.platform.database.adapters.repository import AppendOnlyRepository


class CaseStateTransitionRepository(AppendOnlyRepository[CaseStateTransition]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CaseStateTransition, session)

    async def list_by_case(self, case_id: uuid.UUID) -> Sequence[CaseStateTransition]:
        """Oldest first — this is the case's state history, read in order."""
        result = await self.session.execute(
            select(CaseStateTransition)
            .where(CaseStateTransition.case_id == case_id)
            .order_by(CaseStateTransition.created_at)
        )
        return result.scalars().all()
