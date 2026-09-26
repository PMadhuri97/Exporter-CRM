"""``ExporterContactActivityService`` — EXP-1's contact and activity-log
service, mirroring ``OnboardingRequestService``'s method-per-operation style.

Kept as a separate service from ``ExporterProfileService`` because it owns a
different pair of aggregates (``ExporterContact``, ``ExporterActivity``) with
no shared write path to the profile row itself — ``customer_id`` is a bare
reference on both, the same no-FK convention ``exporter_contact.py`` and
``exporter_activity.py`` document, so neither method here requires an
``ExporterProfile`` to already exist for the given ``customer_id`` (a contact
or a call log can be recorded the moment Sales has a ``customer_id`` to hang
it on, even before a profile row is created).
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
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
)

logger = structlog.get_logger(__name__)


class ExporterContactActivityService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._contacts = ExporterContactRepository(db)
        self._activities = ExporterActivityRepository(db)

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
        """
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
        """
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

    # ── Cross-exporter pending/follow-up list (Piece 2) ──────────────────────

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
