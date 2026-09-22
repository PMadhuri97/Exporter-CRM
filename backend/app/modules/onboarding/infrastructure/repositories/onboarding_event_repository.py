"""
Repository for ``onboarding_event`` rows.

Append-only: ``AppendOnlyRepository`` exposes no update or delete, and the
``prevent_mutation()`` trigger enforces the same rule at the database — mirroring
``WebhookEventRepository``'s sibling pattern for the module's other append-only
table.

``list_by_request`` and ``find_transition`` are AL-672's (PR #112), built for
``OnboardingTransitionService``. ``list_all_ordered`` is Epic 4.1 Story S7T2's,
built independently for ``OnboardingQueryService.get_time_in_state_metrics``; it
has no equivalent on the AL-672 side, so it stays. S7T1 originally built its own
``list_by_onboarding_request`` with the same query shape as ``list_by_request``
(oldest-first, one request's events) — reconciled onto AL-672's version, which
adds an ``id`` tie-break for a deterministic order when two events share a
``created_at`` timestamp; callers were switched to ``list_by_request``.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.platform.database.adapters.repository import AppendOnlyRepository


class OnboardingEventRepository(AppendOnlyRepository[OnboardingEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OnboardingEvent, session)

    async def list_by_request(
        self, onboarding_request_id: uuid.UUID
    ) -> Sequence[OnboardingEvent]:
        """Oldest first — the request's lifecycle history, read in order."""
        result = await self.session.execute(
            select(OnboardingEvent)
            .where(OnboardingEvent.onboarding_request_id == onboarding_request_id)
            .order_by(OnboardingEvent.created_at, OnboardingEvent.id)
        )
        return result.scalars().all()

    async def find_transition(
        self,
        onboarding_request_id: uuid.UUID,
        *,
        event_type: str,
        from_status: str,
        to_status: str,
    ) -> OnboardingEvent | None:
        """The event recorded for one transition of one request, if it happened.

        The lifecycle is acyclic, so a request crosses each ``from → to`` edge at most
        once and this finds at most one row.
        """
        result = await self.session.execute(
            select(OnboardingEvent)
            .where(
                OnboardingEvent.onboarding_request_id == onboarding_request_id,
                OnboardingEvent.event_type == event_type,
                OnboardingEvent.from_status == from_status,
                OnboardingEvent.to_status == to_status,
            )
            .order_by(OnboardingEvent.created_at, OnboardingEvent.id)
            .limit(1)
        )
        return result.scalars().first()

    async def list_all_ordered(self) -> list[OnboardingEvent]:
        """Every event across every onboarding_request, grouped by request and
        time-ordered within each group.

        Used by `OnboardingQueryService.get_time_in_state_metrics` (S7T2),
        which needs consecutive-event pairs per request to compute time spent
        in each status; ordering by `(onboarding_request_id, created_at)` lets
        the caller derive those pairs with a single `itertools.groupby` pass
        instead of one query per request.
        """
        result = await self.session.execute(
            select(OnboardingEvent).order_by(
                OnboardingEvent.onboarding_request_id.asc(),
                OnboardingEvent.created_at.asc(),
            )
        )
        return list(result.scalars().all())


__all__ = ["OnboardingEventRepository"]
