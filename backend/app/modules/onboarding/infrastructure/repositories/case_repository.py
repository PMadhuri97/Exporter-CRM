"""Repository for the `onboarding_case` aggregate root."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.case import Case
from app.platform.database.adapters.repository import BaseRepository


class DirectStateMutationError(RuntimeError):
    """
    Raised when any code tries to set `Case.state` through the repository.

    Not an `AnerBaseException`: this is a programming error, not a client error. It
    must never reach an HTTP response, because no request can legitimately provoke it.
    """


class CaseRepository(BaseRepository[Case]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Case, session)

    async def get_by_id(self, case_id: uuid.UUID) -> Case | None:
        return await self.get(case_id)

    async def get_by_idempotency_key(self, tenant_id: uuid.UUID, key: str) -> Case | None:
        result = await self.session.execute(
            select(Case).where(Case.tenant_id == tenant_id, Case.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_external_case_id(
        self, tenant_id: uuid.UUID, external_case_id: str
    ) -> Case | None:
        result = await self.session.execute(
            select(Case).where(
                Case.tenant_id == tenant_id, Case.external_case_id == external_case_id
            )
        )
        return result.scalar_one_or_none()

    async def update(self, instance: Case, **kwargs: Any) -> Case:
        """
        Update mutable case attributes.

        Refuses `state`. The rule is that "state cannot be updated directly from
        random service code", and this is the repository-layer half of that
        rule. The state machine is the only writer, and it will set the
        column on the ORM instance itself after checking the transition is legal.
        """
        if "state" in kwargs:
            raise DirectStateMutationError(
                "Case.state cannot be set through CaseRepository.update(). "
                "State changes must go through the case state machine."
            )
        return await super().update(instance, **kwargs)
