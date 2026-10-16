"""``ExporterContactActivityService`` — the contact and activity-log
service, mirroring ``OnboardingRequestService``'s method-per-operation style.

Kept as a separate service from ``ExporterProfileService`` because it owns a
different pair of aggregates (``ExporterContact``, ``ExporterActivity``) and
never writes the profile row itself. It does **read** it: since migration 0014
both tables carry a real foreign key to ``exporter_profile.customer_id``
(``fk_exporter_contact_customer_id``, ``fk_exporter_activity_customer_id``), so
a contact or an activity for a company that does not exist is refused by the
database.

This module's docstring used to say the opposite — that neither method required
an ``ExporterProfile`` to exist, because a contact could be recorded the moment
Sales had a ``customer_id`` to hang it on. There is no such moment any more: a
company *is* an ``exporter_profile`` row from creation
(``docs/contracts/company-record.md`` §1). So both writers check the company
first and raise ``ExporterProfileNotFoundError`` — a 404 naming the
company, rather than the 500 an ``IntegrityError`` would surface as.

**People.** A contact row is also how a company's directors and beneficial owners are
recorded (``domain/people.py``): the same add and edit, with roles and person fields.
The identification number is encrypted here, before it reaches the session, and only
its last four characters are kept in clear. Gaining or losing the director or owner
role writes one ``contact`` history row (``person_added``, ``person_roles_changed``):
the sanctions screening reads it as "someone new to screen".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions, people
from app.modules.onboarding.domain.engagement_views import PendingActivityView
from app.modules.onboarding.domain.entities.engagement_enums import (
    ContactStatus,
    ExporterActivityType,
)
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.exceptions import (
    ActivityDueInPastError,
    ContactNotActiveError,
    ExporterContactAlreadyExistsError,
    ExporterContactNotFoundError,
    ExporterContactPrimaryConflictError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
    ExporterProfileRepository,
)
from app.platform.security.field_cipher import encrypt_field
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The partial unique index behind "at most one primary contact per company".
_PRIMARY_INDEX = "uq_exporter_contact_primary_per_customer"


def set_identification_number(person: ExporterContact, number: str | None) -> None:
    """Seal ``number`` onto ``person``, or clear it (and its type) when empty. The type
    itself is the caller's: a number without one is refused by ``check_person``."""
    number = (number or "").strip()
    if not number:
        person.identification_encrypted = None
        person.identification_last4 = None
        person.identification_type = None
        return
    person.identification_encrypted = encrypt_field(number, purpose=people.IDENTIFICATION_PURPOSE)
    person.identification_last4 = number[-4:]


class ExporterContactActivityService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._contacts = ExporterContactRepository(db)
        self._activities = ExporterActivityRepository(db)
        # Read-only. This service never writes the company row — that is
        # the company record's — but both of its writers have to know the company is
        # real before the foreign key finds out for them.
        self._profiles = ExporterProfileRepository(db)

    # ── Contacts ──────────────────────────────────────────────────────────

    async def _refuse_a_duplicate(
        self,
        customer_id: uuid.UUID,
        *,
        email: str | None,
        phone: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Refuse a contact this company can already reach the same way.

        Either field is enough: an email address already on the company, or a phone
        number already on it, and the contact is not written. A second row holds
        nothing the first does not.

        Decided for this CRM, and worth knowing what it also refuses: one person listed
        twice under two roles shares an email, and an office switchboard is shared by
        several people. Where one of those is real, the second contact goes in without
        the shared field, or the first is edited.

        Checked here rather than in the route, so every caller is held to it, and
        before anything is written, so a refusal leaves nothing behind.
        """
        matches = await self._contacts.others_sharing_details(
            customer_id, email=email, phone=phone, exclude_id=exclude_id
        )
        if not matches:
            return

        wanted_email = (email or "").strip().lower()
        other = matches[0]
        # Which field matched, so the form can say which line to change. The email is
        # the more telling of the two when both do.
        matched_email = bool(wanted_email) and (other.email or "").strip().lower() == wanted_email
        raise ExporterContactAlreadyExistsError(
            contact_id=other.id,
            name=other.name,
            field="email" if matched_email else "phone",
        )

    async def add_contact(
        self,
        customer_id: uuid.UUID,
        *,
        name: str,
        role: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        department: str | None = None,
        is_primary: bool = False,
        is_contact: bool = True,
        is_director: bool = False,
        is_ubo: bool = False,
        details: Mapping[str, object] | None = None,
        actor_id: str | None = None,
    ) -> ExporterContact:
        """Create a person: a contact, a director, a beneficial owner, or several.

        ``details`` carries the optional person fields (``people.PERSON_FIELDS``) and
        ``identification_number``, which is encrypted before it is set. A person that
        breaks a rule (no role, a DIN on someone who is not a director, ...) is refused
        with a ``ValidationError`` before anything is written. Adding a director or
        beneficial owner writes a ``person_added`` history row.

        When ``is_primary=True``, demotes any existing
        primary contact for ``customer_id`` in the same transaction as the
        insert, so one call never leaves two primaries. Two calls racing for the
        same company can still both promote; ``uq_exporter_contact_primary_per_customer``
        refuses the second, and it surfaces as ``ExporterContactPrimaryConflictError``
        (409) rather than a 500.

        Raises ``ExporterProfileNotFoundError`` (404) when no company has this
        ``customer_id``, before demoting anything — so a write refused for a
        company that does not exist cannot have demoted somebody's primary
        contact on the way past.
        """
        await self._require_company(customer_id)
        await self._refuse_a_duplicate(customer_id, email=email, phone=phone)

        fields = dict(details or {})
        number = fields.pop("identification_number", None)
        contact = ExporterContact(
            customer_id=customer_id,
            name=name,
            role=role,
            email=email,
            phone=phone,
            department=department,
            is_primary_contact=is_primary,
            is_contact=is_contact,
            is_director=is_director,
            is_ubo=is_ubo,
            **{field: fields.get(field) for field in people.PERSON_FIELDS},
        )
        if number:
            set_identification_number(contact, str(number))
        people.check_person(contact)

        if is_primary:
            await self._contacts.demote_existing_primary(customer_id)
        async with self._primary_conflict_as_409(customer_id):
            await self._contacts.create(contact)
            if people.is_person_of_interest(contact):
                await self._record_roles(contact, before=[], actor_id=actor_id)
            await self._db.commit()
        await self._db.refresh(contact)

        logger.info(
            "exporter_contact.add.ok",
            customer_id=str(customer_id),
            contact_id=str(contact.id),
            is_primary=is_primary,
        )
        return contact

    async def update_contact(
        self,
        customer_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        changes: Mapping[str, object],
        actor_id: str | None = None,
    ) -> ExporterContact:
        """Change the fields named in ``changes`` on one contact, and nothing else.

        ``changes`` holds only the fields the caller actually sent, so a field left out
        keeps its value and a field sent as ``null`` is cleared. Those two cases are not
        the same thing, which is why this takes a mapping rather than a parameter per
        column defaulting to ``None`` — with defaults, "leave the phone alone" and
        "delete the phone" arrive here identically.

        ``is_primary`` is translated to the column's own name and handled like
        ``add_contact`` does: promoting this contact demotes whichever other one held
        it, in the same transaction, so the company never has two primaries. Demoting
        the only primary is allowed — a company with no primary contact is a state the
        record can be in, and refusing it would trap whoever recorded the wrong one.

        Roles change the same way. Taking one away clears the fields that belong only
        to it (a former director keeps no DIN); taking away the contact role stops the
        person being the primary contact. ``identification_number`` is encrypted, and
        sent as ``null`` clears the number and its type. A change that would break a
        rule is refused with a ``ValidationError`` before anything is written, and a
        change to the director or owner role writes a ``person_roles_changed`` row.

        Raises ``ExporterProfileNotFoundError`` when the company does not exist,
        ``ExporterContactNotFoundError`` when it does but this contact is not its, and
        ``ExporterContactPrimaryConflictError`` when another write promoted a different
        contact at the same moment.
        """
        await self._require_company(customer_id)
        contact = await self._contacts.get_for_customer(customer_id, contact_id)
        if contact is None:
            raise ExporterContactNotFoundError(customer_id, contact_id)

        fields = dict(changes)
        promote = fields.pop("is_primary", None)
        number_sent = "identification_number" in fields
        number = fields.pop("identification_number", None)
        before = people.roles_of(contact)
        for name, value in fields.items():
            setattr(contact, name, value)
        if number_sent:
            set_identification_number(contact, number)
        people.clear_fields_of_removed_roles(contact, before=before)
        if not contact.is_contact and promote is None:
            contact.is_primary_contact = False

        # On the values the edit leaves behind, not the ones it sent: changing only the
        # phone onto a contact that already has this one's email is the same duplicate
        # as sending both. Itself excluded — a contact never duplicates itself.
        if {"email", "phone"} & set(fields):
            await self._refuse_a_duplicate(
                customer_id,
                email=contact.email,
                phone=contact.phone,
                exclude_id=contact_id,
            )

        if promote is not None:
            if promote and contact.status != ContactStatus.ACTIVE.value:
                raise ContactNotActiveError(contact_id, contact.status)
            contact.is_primary_contact = bool(promote)
        # Before the demotion below: its statement would otherwise flush this row first,
        # and a broken rule would reach the database as a 500 rather than a 422.
        people.check_person(contact)
        if promote:
            # Everyone else, so this row's own flag is not cleared and re-set. Not
            # autoflushed: this row, now primary, is written after the others are
            # demoted, or it would meet the one-primary index while they still hold it.
            with self._db.no_autoflush:
                await self._contacts.demote_existing_primary(
                    customer_id, except_id=contact_id
                )

        after = people.roles_of(contact)
        async with self._primary_conflict_as_409(customer_id):
            if after != before and {people.DIRECTOR, people.UBO} & {*before, *after}:
                await self._record_roles(contact, before=before, actor_id=actor_id)
            await self._db.commit()
        await self._db.refresh(contact)

        logger.info(
            "exporter_contact.update.ok",
            customer_id=str(customer_id),
            contact_id=str(contact_id),
            # The names only: a contact's email and phone are masked for most roles on
            # the way out, and a log line is read by people a response is not.
            changed=sorted(changes),
        )
        return contact

    async def set_contact_status(
        self,
        customer_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        status: ContactStatus,
        reason: str | None,
        actor_id: str,
    ) -> ExporterContact:
        """Move a contact to ``status``: a reason is required to leave ACTIVE, and a
        contact that leaves ACTIVE stops being the primary (only an active contact can be
        the person to reach — the database refuses anything else). One ``contact``
        history row records it."""
        await self._require_company(customer_id)
        contact = await self._contacts.get_for_customer(customer_id, contact_id)
        if contact is None:
            raise ExporterContactNotFoundError(customer_id, contact_id)
        reason = (reason or "").strip() or None
        if status is not ContactStatus.ACTIVE and reason is None:
            raise ValidationError("A reason is required when a contact is no longer active")
        if contact.status == status.value:
            return contact

        previous = contact.status
        was_primary = contact.is_primary_contact
        contact.status = status.value
        contact.status_changed_at = datetime.now(UTC)
        contact.status_reason = reason
        if status is not ContactStatus.ACTIVE:
            contact.is_primary_contact = False
        await HistoryService(self._db).record(
            customer_id,
            dimension=history_dimensions.CONTACT,
            event_type="contact_status_changed",
            from_value=previous,
            to_value=status.value,
            reason=reason,
            actor_id=actor_id,
            source="exporter_contact.set_status",
            details={
                "contact_id": str(contact_id),
                "contact_name": contact.name,
                "was_primary": was_primary and not contact.is_primary_contact,
            },
        )
        await self._db.commit()
        await self._db.refresh(contact)
        logger.info(
            "exporter_contact.status.ok",
            customer_id=str(customer_id),
            contact_id=str(contact_id),
            status=status.value,
        )
        return contact

    async def mark_contact_verified(
        self, customer_id: uuid.UUID, contact_id: uuid.UUID, *, actor_id: str
    ) -> ExporterContact:
        """Someone confirmed the contact's details are right: stamp when and who."""
        await self._require_company(customer_id)
        contact = await self._contacts.get_for_customer(customer_id, contact_id)
        if contact is None:
            raise ExporterContactNotFoundError(customer_id, contact_id)
        contact.last_verified_at = datetime.now(UTC)
        contact.last_verified_by = actor_id
        await HistoryService(self._db).record(
            customer_id,
            dimension=history_dimensions.CONTACT,
            event_type="contact_verified",
            to_value="VERIFIED",
            actor_id=actor_id,
            source="exporter_contact.mark_verified",
            details={"contact_id": str(contact_id), "contact_name": contact.name},
        )
        await self._db.commit()
        await self._db.refresh(contact)
        return contact

    async def list_contacts(
        self, customer_id: uuid.UUID, *, role: str | None = people.CONTACT
    ) -> list[ExporterContact]:
        """The company's people holding ``role`` (``people.CONTACT`` by default); every
        person when ``role`` is ``None``."""
        return await self._contacts.list_by_customer(customer_id, role=role)

    # ── Activities ────────────────────────────────────────────────────────

    async def log_activity(
        self,
        customer_id: uuid.UUID,
        *,
        activity_type: ExporterActivityType,
        subject: str,
        actor_id: str,
        notes: str | None = None,
        due_at: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> ExporterActivity:
        """Append one activity-log entry. ``occurred_at`` defaults to now();
        a caller backfilling a historical activity (e.g. an imported call
        log) may supply it explicitly. The row is append-only from here on —
        see ``exporter_activity.py``'s module docstring.

        ``due_at`` may not fall before ``occurred_at``: a follow-up that exists already
        overdue is a mistyped date, and it makes the Follow-ups page's overdue count
        mean less. ``ActivityDueInPastError`` (422), matching the refusals the
        conversation gauge and the follow-up reschedule already make.

        Raises ``ExporterProfileNotFoundError`` (404) when no company has this
        ``customer_id``. The activity table is append-only, so a row written
        against a ghost company could never be corrected — the check is cheap
        insurance for a table nothing can repair.
        """
        await self._require_company(customer_id)
        # A follow-up cannot be created already overdue — the same rule the conversation
        # gauge applies to `check_back_on` and the follow-up service to a reschedule.
        # Compared against `occurred_at` rather than the clock, so that an import
        # backfilling last month's call with next month's follow-up is not refused for
        # being in the past of today; for the API, where `occurred_at` is always now,
        # the two are the same comparison.
        if due_at is not None:
            happened = occurred_at or datetime.now(UTC)
            if due_at < happened:
                raise ActivityDueInPastError(customer_id, due_at)

        activity = ExporterActivity(
            customer_id=customer_id,
            activity_type=activity_type,
            subject=subject,
            notes=notes,
            actor_id=actor_id,
            occurred_at=occurred_at or datetime.now(UTC),
            due_at=due_at,
        )
        await self._activities.create(activity)
        await self._db.commit()
        await self._db.refresh(activity)

        logger.info(
            "exporter_activity.log.ok",
            customer_id=str(customer_id),
            activity_id=str(activity.id),
            activity_type=activity_type.value,
        )
        return activity

    async def list_activities(
        self,
        customer_id: uuid.UUID,
        *,
        activity_type: ExporterActivityType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterActivity]:
        return await self._activities.list_by_customer(
            customer_id, activity_type=activity_type, limit=limit, offset=offset
        )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _record_roles(
        self, person: ExporterContact, *, before: list[str], actor_id: str | None
    ) -> None:
        """One ``contact`` history row: a director or beneficial owner was added, or a
        person's roles changed. Names and roles only; the person fields are masked for
        most viewers and a history row is read by people a response is not."""
        await self._db.flush()
        after = people.roles_of(person)
        await HistoryService(self._db).record(
            person.customer_id,
            dimension=history_dimensions.CONTACT,
            event_type="person_roles_changed" if before else "person_added",
            from_value=",".join(before) if before else None,
            to_value=",".join(after),
            actor_id=actor_id,
            source="exporter_contact.roles",
            details={
                "contact_id": str(person.id),
                "contact_name": person.name,
                "roles": after,
            },
        )

    @asynccontextmanager
    async def _primary_conflict_as_409(self, customer_id: uuid.UUID) -> AsyncIterator[None]:
        """Turn a lost race for the primary flag into a 409.

        Demoting the other primaries and promoting this one happen in one transaction,
        but two such transactions for the same company — two people promoting two
        different contacts at once — cannot see each other's promotion, and the second
        to commit meets the partial unique index. That refusal is correct; this only
        changes how it reads, from a 500 to ``EXPORTER_CONTACT_PRIMARY_CONFLICT``. Any
        other integrity error is not this race and is re-raised untouched.
        """
        try:
            yield
        except IntegrityError as exc:
            await self._db.rollback()
            if _PRIMARY_INDEX in str(exc.orig):
                raise ExporterContactPrimaryConflictError(customer_id) from None
            raise

    async def _require_company(self, customer_id: uuid.UUID) -> None:
        """Refuse a write for a company that does not exist, with a 404.

        The database refuses it too — that is what the two foreign keys are for,
        and ``test_contact_activity_links.py`` proves it in raw SQL. This
        check exists so the *API* answer is a 404 naming the company instead of
        the 500 an ``IntegrityError`` escaping a request handler produces.

        Not locked and not part of a transaction that spans the insert: between
        this check and the insert the company could in principle be deleted, and
        then the foreign key refuses the row. That is the right outcome and the
        reason the constraint is the authority here; this is the error message.
        """
        if await self._profiles.get_by_customer_id(customer_id) is None:
            raise ExporterProfileNotFoundError(customer_id)

    # ── Cross-exporter pending/follow-up list ────────────────────────────────

    async def list_pending_activities(
        self,
        *,
        actor_id: str | None = None,
        activity_type: ExporterActivityType | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PendingActivityView]:
        """Everything pending, across every exporter — a Follow-ups/pending-work
        screen's own query, answering a question `list_activities` cannot:
        that method only ever scopes to one `customer_id`.

        `actor_id=None` (the default) returns across every actor — a
        manager's team-wide view; passing it scopes to just that person's own
        pending items. "Pending" means "carries a `due_at`" — the append-only
        activity log's only stand-in for "this is a follow-up item, not just
        a note" (see `exporter_activity.py`'s module docstring: `due_at` is
        nullable and meaningful only for TASK/FOLLOW_UP entries).

        Each `PendingActivityView` already carries the exporter's display
        name and a computed `is_overdue` — resolved in the one query
        `ExporterActivityRepository.list_pending` runs, never a per-row
        follow-up query.
        """
        now = datetime.now(UTC)
        rows = await self._activities.list_pending(
            actor_id=actor_id,
            activity_type=activity_type,
            due_before=due_before,
            due_after=due_after,
            limit=limit,
            offset=offset,
        )
        views = []
        for activity, legal_name in rows:
            # ExporterActivityRepository.list_pending's own WHERE clause
            # (`due_at IS NOT NULL`) guarantees this at the SQL level; this
            # assertion is what lets the type checker know it too, rather
            # than widening PendingActivityView.due_at to Optional for a case
            # that can never actually occur.
            assert activity.due_at is not None
            views.append(
                PendingActivityView(
                    id=activity.id,
                    customer_id=activity.customer_id,
                    exporter_display_name=legal_name,
                    activity_type=activity.activity_type,
                    subject=activity.subject,
                    notes=activity.notes,
                    actor_id=activity.actor_id,
                    occurred_at=activity.occurred_at,
                    due_at=activity.due_at,
                    is_overdue=activity.due_at < now,
                    created_at=activity.created_at,
                )
            )
        return views


__all__ = ["ExporterContactActivityService"]
