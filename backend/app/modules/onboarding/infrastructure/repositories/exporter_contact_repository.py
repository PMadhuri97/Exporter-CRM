"""Repository for ``exporter_contact`` rows."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.engagement_enums import ContactStatus
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.people import ROLE_COLUMNS
from app.platform.database.adapters.repository import BaseRepository

#: Everything but the digits, stripped before one phone number is compared with
#: another: the same line reaches the CRM as `+91 98765 43210`, `098765 43210` and
#: `9876543210`.
_NOT_A_DIGIT = r'[^0-9]'

#: The fewest digits a number must have before its ending is compared at all.
#:
#: Below this an "extension" or half a number would match far too much, so a short
#: value is compared whole.
SIGNIFICANT_PHONE_DIGITS = 7


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

    async def lock_company(self, customer_id: uuid.UUID) -> None:
        """Take the company's row for update, so writers to its contacts queue.

        The duplicate check reads the company's contacts and then writes one. Without a
        lock, two requests both read "no duplicate" before either writes, and both
        write — which is exactly the double submit the rule exists to catch. Four
        simultaneous submits produced four contacts.

        The lock is on `exporter_profile`, not on the contacts: there is no row to lock
        for a contact that does not exist yet, and the company is the thing being
        added to. It is held until the transaction commits, so the check and the insert
        are one step as far as any other writer is concerned.

        A company that does not exist locks nothing and returns; `_require_company`
        answers that with a 404 before this is reached.
        """
        await self.session.execute(
            select(ExporterProfile.customer_id)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
        )

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

        What the duplicate rule is built on: a match here **refuses** the write
        (`ExporterContactAlreadyExistsError`). It is not a warning, and the comparison
        is written for that — an ending-match on the phone rather than a truncation, so
        two different lines are never called one.

        It does refuse things a company may genuinely want: one person listed twice
        under two roles shares an email, and an office switchboard is shared by several
        people. That was decided for this CRM; the second contact goes in without the
        shared field.

        Compared on the stored values, which only this side holds. Contact details
        reach most roles masked, so a browser comparing what it was shown would match
        two different people at one domain and miss two spellings of one number. Email
        is compared without case; a phone by whether either number ends with the other.

        `INACTIVE` and `LEFT_COMPANY` contacts are left out. Their details are kept as a
        record of who was once there, and warning that a new contact matches someone who
        has left would put a warning on exactly the entry that replaces them.
        """
        matches = []
        if email and email.strip():
            matches.append(func.lower(ExporterContact.email) == email.strip().lower())
        digits = "".join(character for character in (phone or "") if character.isdigit())
        digits = digits[1:] if digits.startswith("0") else digits
        if len(digits) >= SIGNIFICANT_PHONE_DIGITS:
            # A single leading `0` is a trunk prefix, not part of the number, and it
            # is dropped before the endings are compared: otherwise `09876543210` and
            # `919876543210` — one line, dialled two ways — end differently and the
            # duplicate goes in.
            stored = func.regexp_replace(
                func.regexp_replace(ExporterContact.phone, _NOT_A_DIGIT, "", "g"), "^0", ""
            )
            # One number is the same line as another when either ends with the other:
            # `919876543210`, `09876543210` and `9876543210` are one line, because a
            # country code or a trunk `0` is exactly what varies between two entries.
            #
            # Deliberately *not* "the last eight digits are equal", which this used to
            # be. That treats `0802 2345678` and `0442 2345678` — two cities, two
            # lines — as the same number, and refuses the second. Comparing endings
            # keeps the variants together without ever merging two numbers of the same
            # length that differ anywhere.
            matches.append(
                or_(
                    stored.like(f"%{digits}"),
                    and_(
                        func.length(stored) >= SIGNIFICANT_PHONE_DIGITS,
                        literal(digits).like(func.concat("%", stored)),
                    ),
                )
            )
        elif digits:
            # Too short for its ending to mean anything — an extension, or half a
            # number. Matched whole, so it still catches the same thing typed twice.
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
