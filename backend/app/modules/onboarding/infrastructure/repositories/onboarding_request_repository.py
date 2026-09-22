"""
Repository for the ``onboarding_request`` aggregate root.

The status column is written in exactly one way: :meth:`compare_and_set_status`, a
conditional ``UPDATE … WHERE id = :id AND status = :expected_status``. There is no
version column on this table, so the expected status is the concurrency guard: of
two writers that read the same status, the database lets only one move it.
``OnboardingTransitionService`` (AL-672) is the only caller of that method.

The read/query methods below (``get_by_id``, ``get_by_tenant_and_idempotency_key``,
``list_by_customer``, ``list_by_status``, ``list_initiated_between``) were built for
Epic 4.1 Story S7 (``OnboardingRequestService`` / ``OnboardingQueryService``) against
the same table, independently of the transition-writing methods below them, which
AL-672 (PR #112) built for the Temporal workflow. Reconciled into one repository
file rather than kept as two competing repository classes for the same table.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.platform.database.adapters.repository import BaseRepository


class OnboardingRequestRepository(BaseRepository[OnboardingRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OnboardingRequest, session)

    # ── Reads (Epic 4.1 S7) ─────────────────────────────────────────────────

    async def get_by_id(self, onboarding_request_id: uuid.UUID) -> OnboardingRequest | None:
        return await self.get(onboarding_request_id)

    async def get_by_tenant_and_idempotency_key(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> OnboardingRequest | None:
        result = await self.session.execute(
            select(OnboardingRequest).where(
                OnboardingRequest.tenant_id == tenant_id,
                OnboardingRequest.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_customer(self, customer_id: uuid.UUID) -> list[OnboardingRequest]:
        """All onboarding attempts for a customer, reverse chronological (S7T1)."""
        result = await self.session.execute(
            select(OnboardingRequest)
            .where(OnboardingRequest.customer_id == customer_id)
            .order_by(OnboardingRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_status(
        self, status: OnboardingRequestStatus
    ) -> list[OnboardingRequest]:
        """Every onboarding_request currently in `status` (S7T2 queue reads)."""
        result = await self.session.execute(
            select(OnboardingRequest).where(OnboardingRequest.status == status)
        )
        return list(result.scalars().all())

    async def list_initiated_between(
        self, start: datetime, end: datetime
    ) -> list[OnboardingRequest]:
        """Requests initiated in `[start, end]`, for S7T2 statistics aggregation."""
        result = await self.session.execute(
            select(OnboardingRequest).where(
                OnboardingRequest.initiated_at >= start,
                OnboardingRequest.initiated_at <= end,
            )
        )
        return list(result.scalars().all())

    async def get_status(
        self, onboarding_request_id: uuid.UUID
    ) -> OnboardingRequestStatus | None:
        """The request's committed-or-flushed status, read fresh; None if it does not exist."""
        return await self.session.scalar(
            select(OnboardingRequest.status).where(
                OnboardingRequest.id == onboarding_request_id
            )
        )

    # ── Writes (AL-672 — OnboardingTransitionService is the only caller) ───

    async def compare_and_set_status(
        self,
        onboarding_request_id: uuid.UUID,
        *,
        expected_status: OnboardingRequestStatus,
        to_status: OnboardingRequestStatus,
        occurred_at: datetime | None,
        set_initiated_at: bool = False,
        set_completed_at: bool = False,
        rejection_category: OnboardingRejectionCategory | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Move the request to ``to_status`` only if it is still in ``expected_status``.

        Returns False, having changed nothing, when the request does not exist or is
        in any other status. Flushes but does not commit — the caller owns the
        transaction, so the status change and its event commit together.

        ``occurred_at`` stamps ``last_activity_at`` (and ``initiated_at`` /
        ``completed_at`` when asked); ``None`` uses the database clock. A caller that
        may retry passes the same value each time so a retry writes the same row.
        """
        at = occurred_at if occurred_at is not None else func.now()
        values: dict = {
            "status": to_status,
            "last_activity_at": at,
            "updated_at": func.now(),
        }
        if set_initiated_at:
            values["initiated_at"] = func.coalesce(OnboardingRequest.initiated_at, at)
        if set_completed_at:
            values["completed_at"] = at
        if rejection_category is not None:
            values["rejection_category"] = rejection_category
            values["rejection_reason"] = rejection_reason

        result = await self.session.execute(
            update(OnboardingRequest)
            .where(OnboardingRequest.id == onboarding_request_id)
            .where(OnboardingRequest.status == expected_status)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def record_activity(
        self,
        onboarding_request_id: uuid.UUID,
        *,
        expected_status: OnboardingRequestStatus,
        occurred_at: datetime,
    ) -> bool:
        """Stamp a customer action on ``last_activity_at`` without changing status.

        Applies only while the request is still in ``expected_status``, and never
        moves the timestamp backwards, so a retry or a late duplicate is harmless.
        Returns False when nothing matched. Flushes but does not commit.
        """
        result = await self.session.execute(
            update(OnboardingRequest)
            .where(OnboardingRequest.id == onboarding_request_id)
            .where(OnboardingRequest.status == expected_status)
            .values(
                last_activity_at=func.greatest(
                    func.coalesce(OnboardingRequest.last_activity_at, occurred_at),
                    occurred_at,
                ),
                updated_at=func.now(),
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


__all__ = ["OnboardingRequestRepository"]
