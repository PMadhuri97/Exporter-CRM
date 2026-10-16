"""Repository for ``exporter_contact`` rows."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.engagement_enums import ContactStatus
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.people import ROLE_COLUMNS
from app.platform.database.adapters.repository import BaseRepository

#: Everything but the digits, stripped before one phone number is compared with
#: another: the same line reaches the CRM as `+91 98765 43210`, `098765 43210` and
#: `9876543210`.
_NOT_A_DIGIT = r'[^0-9]'

#: How many trailing digits decide whether two numbers are the same line.
#:
#: Not the whole string. Those three spellings hold 12, 11 and 10 digits, and comparing
#: them whole calls one person three people — a country code or a trunk `0` in front is
#: exactly what varies between one entry and the next. The last eight are the part that
#: does not: two different lines sharing them is rare enough to accept, and the result
#: is a warning somebody reads, not a refusal.
SIGNIFICANT_PHONE_DIGITS = 8


class ExporterContactRepository(BaseRepository[ExporterContact]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterContact, session)

    async def list_by_customer(
        self, customer_id: uuid.UUID, *, role: str | None = None
    ) -> list[ExporterContact]:
        """The company's people, oldest first; only those holding ``role`` (``CONTACT``,
        ``DIRECTOR``, ``UBO``) when one is given."""
        statement = select(ExporterContact).where(ExporterContact.customer_id == customer_id)
        if role is not None:
            statement = statement.where(getattr(ExporterContact, ROLE_COLUMNS[role]).is_(True))
        result = await self.session.execute(statement.order_by(ExporterContact.created_at.asc()))
        return list(result.scalars().all())

    async def others_sharing_details(
        self,
        customer_id: uuid.UUID,
        *,
        email: str | None,
        phone: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> list[ExporterContact]:
        """This company's other **active** contacts reachable at the same email or
        phone number.

        For a warning, never a refusal: one person is legitimately listed twice at some
        companies — a founder who is both the commercial and the finance contact — and
        one switchboard number serves a whole office. What this catches is the
        accidental second entry, the same details typed twice.

        Compared on the stored values, which only this side holds. Contact details
        reach most roles masked, so a browser comparing what it was shown would match
        two different people at one domain and miss two spellings of one number. Email
        is compared without case; a phone by its last `SIGNIFICANT_PHONE_DIGITS` digits.

        `INACTIVE` and `LEFT_COMPANY` contacts are left out. Their details are kept as a
        record of who was once there, and warning that a new contact matches someone who
        has left would put a warning on exactly the entry that replaces them.
        """
        matches = []
        if email and email.strip():
            matches.append(func.lower(ExporterContact.email) == email.strip().lower())
        digits = "".join(character for character in (phone or "") if character.isdigit())
        if len(digits) >= SIGNIFICANT_PHONE_DIGITS:
            stored = func.regexp_replace(ExporterContact.phone, _NOT_A_DIGIT, "", "g")
            matches.append(
                func.right(stored, SIGNIFICANT_PHONE_DIGITS) == digits[-SIGNIFICANT_PHONE_DIGITS:]
            )
        elif digits:
            # Too short to compare by its ending — an extension, or half a number.
            # Matched whole, so it still catches the same thing typed twice.
            matches.append(
                func.regexp_replace(ExporterContact.phone, _NOT_A_DIGIT, "", "g") == digits
            )
        if not matches:
            return []

        conditions = [
            ExporterContact.customer_id == customer_id,
            ExporterContact.status == ContactStatus.ACTIVE.value,
            or_(*matches),
        ]
        if exclude_id is not None:
            conditions.append(ExporterContact.id != exclude_id)
        result = await self.session.execute(
            select(ExporterContact).where(*conditions).order_by(ExporterContact.created_at.asc())
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


__all__ = ["SIGNIFICANT_PHONE_DIGITS", "ExporterContactRepository"]
