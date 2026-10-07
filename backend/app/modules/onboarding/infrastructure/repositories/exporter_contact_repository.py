"""Repository for ``exporter_contact`` rows."""

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

    async def get_for_customer(
        self, customer_id: uuid.UUID, contact_id: uuid.UUID
    ) -> ExporterContact | None:
        """One contact, **scoped to its company**.

        The company is part of the lookup, not checked afterwards: a contact id from
        another company then reads as missing rather than as somebody else's row, so a
        guessed id tells the caller nothing it did not already know.
        """
        result = await self.session.execute(
            select(ExporterContact).where(
                ExporterContact.id == contact_id,
                ExporterContact.customer_id == customer_id,
            )
        )
        return result.scalar_one_or_none()

    async def demote_existing_primary(
        self, customer_id: uuid.UUID, *, except_id: uuid.UUID | None = None
    ) -> None:
        """Clear ``is_primary_contact`` on every existing contact for
        ``customer_id``. Flushes but does not commit — the caller
        (``ExporterContactActivityService.add_contact``) runs this and the
        new contact's insert in the same transaction, so a demotion is never
        observable without its corresponding promotion.

        ``except_id`` leaves one row alone. An edit that promotes a contact passes its
        own id: demoting it here and promoting it a moment later would, for the length
        of the statement, leave the company with no primary at all, and on a row that is
        already primary it would be a write that undoes itself.
        """
        conditions = [
            ExporterContact.customer_id == customer_id,
            ExporterContact.is_primary_contact.is_(True),
        ]
        if except_id is not None:
            conditions.append(ExporterContact.id != except_id)
        await self.session.execute(
            update(ExporterContact)
            .where(*conditions)
            .values(is_primary_contact=False)
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()


__all__ = ["ExporterContactRepository"]
