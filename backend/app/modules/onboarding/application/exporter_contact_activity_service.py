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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.engagement_views import PendingActivityView
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
    ExporterProfileRepository,
)

logger = structlog.get_logger(__name__)


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
    ) -> ExporterContact:
        """Create a contact. When ``is_primary=True``, demotes any existing
        primary contact for ``customer_id`` in the same transaction as the
        insert — a single service-layer call a caller cannot race into two
        primaries, backed by ``uq_exporter_contact_primary_per_customer`` as
        the database-level guarantee if this method is ever bypassed.

        Raises ``ExporterProfileNotFoundError`` (404) when no company has this
        ``customer_id``, before demoting anything — so a write refused for a
        company that does not exist cannot have demoted somebody's primary
        contact on the way past.
        """
        await self._require_company(customer_id)
        if is_primary:
            await self._contacts.demote_existing_primary(customer_id)

        contact = ExporterContact(
            customer_id=customer_id,
            name=name,
            role=role,
            email=email,
            phone=phone,
            department=department,
            is_primary_contact=is_primary,
        )
        await self._contacts.create(contact)
        await self._db.commit()
        await self._db.refresh(contact)

        logger.info(
            "exporter_contact.add.ok",
            customer_id=str(customer_id),
            contact_id=str(contact.id),
            is_primary=is_primary,
        )
        return contact

    async def list_contacts(self, customer_id: uuid.UUID) -> list[ExporterContact]:
        return await self._contacts.list_by_customer(customer_id)

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

        Raises ``ExporterProfileNotFoundError`` (404) when no company has this
        ``customer_id``. The activity table is append-only, so a row written
        against a ghost company could never be corrected — the check is cheap
        insurance for a table nothing can repair.
        """
        await self._require_company(customer_id)
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
