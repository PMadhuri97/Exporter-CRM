"""Where a company's name and country are kept until the company record has
columns for them — **owner: Developer 2. Transitional: deleted by migration
0014 (L2-05).**

The company record (``exporter_profile``) has no ``name`` or ``country``
column, and adding them is migration 0014's job, which waits on an open
decision (the history foreign key; see ``docs/contracts/migration-register.md``).
Until then the only durable place a company's name has ever been written is
the legacy ``onboarding_request`` row that ``ExporterProfileService.create_lead``
creates beside the profile.

This file is the **only** CRM code that touches ``onboarding_request`` for a
company's identity. Everything else — the profile service, the profile
repository, the routes, the schemas, the views and the frontend — asks this
store for a ``CompanyIdentity`` and has no idea where it comes from. When 0014
lands, the store's four methods are replaced by reads and writes of the
company record's own columns and this file is deleted; nothing that calls it
changes shape.

What this store does **not** do:

* It never updates or deletes an ``onboarding_request`` row. It inserts one
  when a company is created (as ``create_lead`` always has) and reads.
* It does not run, advance or depend on the legacy onboarding workflow. The
  row it inserts is a ``DRAFT`` that nothing moves.
* It is not a second source of truth. A company's identity is whatever the
  most recent ``onboarding_request`` for its id says, exactly as the list and
  search did before this change.

Developer 3's ``ExporterActivityRepository.list_pending`` still joins
``onboarding_request`` for the Follow-ups display name on its own. That is left
for Developer 3 to repoint when 0014 gives the company record a ``name`` column.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
)
from app.modules.onboarding.domain.exporter_profile_views import CompanyIdentity
from app.modules.onboarding.infrastructure.repositories import (
    OnboardingEventRepository,
    OnboardingRequestRepository,
)
from app.platform.configuration.config import settings

logger = structlog.get_logger(__name__)


class LegacyCompanyIdentityStore:
    """Reads and writes a company's name and country (see module docstring)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._requests = OnboardingRequestRepository(db)
        self._events = OnboardingEventRepository(db)

    async def record(
        self,
        company_id: uuid.UUID,
        identity: CompanyIdentity,
        *,
        idempotency_key: str,
        created_by_email: str,
        actor_id: str | None,
        entity_type: OnboardingEntityType = OnboardingEntityType.CORPORATION,
        correlation_id: str | None = None,
    ) -> uuid.UUID | None:
        """Store a new company's identity. Flushes; never commits.

        Returns ``None`` when the identity was stored for ``company_id``. On a
        replay — a retried create with an ``idempotency_key`` that already
        stored an identity — stores nothing and returns the company id that
        replay originally created, so the caller can return that company.

        ``created_by_email`` is the signed-in staff member's address. The
        legacy row needs a reachable contact and the staff member who entered
        the lead is one (the column has always accepted "the Sales rep's own
        address"); it is not asked of the person creating the company.
        """
        now = datetime.now(UTC)
        request = OnboardingRequest(
            tenant_id=uuid.UUID(settings.ANER_TENANT_ID),
            idempotency_key=idempotency_key,
            customer_id=company_id,
            status=OnboardingRequestStatus.DRAFT,
            entity_type=entity_type,
            legal_name=identity.name,
            registration_number=None,
            incorporation_country=identity.country,
            registered_address=None,
            initial_user_id=created_by_email,
            initiated_at=now,
            last_activity_at=now,
            correlation_id=correlation_id,
        )
        try:
            async with self._db.begin_nested():
                self._db.add(request)
                await self._db.flush()
        except IntegrityError:
            existing = await self._requests.get_by_tenant_and_idempotency_key(
                uuid.UUID(settings.ANER_TENANT_ID), idempotency_key
            )
            if existing is None:
                raise
            logger.info(
                "company_identity.record.replay",
                company_id=str(existing.customer_id),
                idempotency_key=idempotency_key,
            )
            return existing.customer_id

        await self._events.create(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="state_transition",
                from_status=None,
                to_status=OnboardingRequestStatus.DRAFT.value,
                actor_id=actor_id,
                event_metadata={"trigger": "lead_created_via_exporter_profile"},
            )
        )
        return None

    async def get(self, company_id: uuid.UUID) -> CompanyIdentity | None:
        """The company's identity, or ``None`` if it has none on file."""
        return (await self.get_many([company_id])).get(company_id)

    async def get_many(
        self, company_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, CompanyIdentity]:
        """Identities for a page of companies, in one query.

        Companies with no identity on file are simply absent from the result.
        """
        ids = list(dict.fromkeys(company_ids))
        if not ids:
            return {}
        latest = (
            select(
                OnboardingRequest.customer_id.label("customer_id"),
                OnboardingRequest.legal_name.label("name"),
                OnboardingRequest.incorporation_country.label("country"),
                func.row_number()
                .over(
                    partition_by=OnboardingRequest.customer_id,
                    order_by=OnboardingRequest.created_at.desc(),
                )
                .label("rn"),
            ).where(OnboardingRequest.customer_id.in_(ids))
        ).subquery("latest_identity")
        rows = await self._db.execute(
            select(latest.c.customer_id, latest.c.name, latest.c.country).where(
                latest.c.rn == 1
            )
        )
        return {
            row.customer_id: CompanyIdentity(name=row.name, country=row.country)
            for row in rows
        }

    async def find_company_ids_by_name(self, fragment: str) -> list[uuid.UUID]:
        """Companies whose name contains ``fragment``, ignoring case."""
        result = await self._db.execute(
            select(OnboardingRequest.customer_id)
            .where(OnboardingRequest.legal_name.ilike(f"%{fragment}%"))
            .distinct()
        )
        return list(result.scalars().all())


__all__ = ["LegacyCompanyIdentityStore"]
