"""Repository for ``exporter_contact`` rows (EXP-1)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.platform.database.adapters.repository import BaseRepository


class ExporterContactRepository(BaseRepository[ExporterContact]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterContact, session)

    async def list_by_customer(self, customer_id: uuid.UUID) -> list[ExporterContact]:
        result = await self.session.execute(
            select(ExporterContact)
            .where(ExporterContact.customer_id == customer_id)
            .order_by(ExporterContact.created_at.asc())
        )
        return list(result.scalars().all())

    async def demote_existing_primary(self, customer_id: uuid.UUID) -> None:
        """Clear ``is_primary_contact`` on every existing contact for
        ``customer_id``. Flushes but does not commit — the caller
        (``ExporterContactActivityService.add_contact``) runs this and the
        new contact's insert in the same transaction, so a demotion is never
        observable without its corresponding promotion.
        """
        await self.session.execute(
            update(ExporterContact)
            .where(
                ExporterContact.customer_id == customer_id,
                ExporterContact.is_primary_contact.is_(True),
            )
            .values(is_primary_contact=False)
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()


__all__ = ["ExporterContactRepository"]
