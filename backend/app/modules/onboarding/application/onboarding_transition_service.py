"""
OnboardingTransitionService — the single gateway for onboarding request status changes.

Every change to ``onboarding_request.status`` goes through :meth:`transition`, which
writes the status change and its ``onboarding_event`` in one transaction:

1. **Permitted** — the lifecycle table must connect the two statuses, and a rejection
   must carry a category that describes a rejection from the status it leaves.
   Checked before any write.
2. **Expected status** — a conditional ``UPDATE … WHERE id = :id AND status =
   :expected_status``. The database, not a prior read, decides whether the request
   was still where the caller believed it was; of two concurrent callers only one
   update matches, and the other waits on the row lock and then matches nothing.
3. **Event** — the ``onboarding_event`` row is added in the same transaction, then
   both commit together. A failure anywhere rolls back both.

Repeating a transition that already happened succeeds without writing anything: when
the update matches nothing, the request is re-read, and if it is now in ``to_status``
with the event for this exact ``from → to`` edge recorded, the original event is
returned. That is what makes the call safe to retry — a retry after a commit whose
acknowledgement was lost, or a second attempt racing the first, produces exactly one
event. It relies on the lifecycle being acyclic (see
``domain/policies/onboarding_request_transitions.py``): each edge is crossed at most
once, so the edge identifies its event and no additional key column is needed.

The service commits, matching the settlement transition enforcer, because the status
and the event are only correct together.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.modules.onboarding.domain.policies.onboarding_request_transitions import (
    TERMINAL_STATUSES,
    is_permitted,
    is_permitted_rejection_category,
)
from app.modules.onboarding.exceptions import (
    OnboardingRequestNotFoundError,
    OnboardingStatusConflictError,
    OnboardingTransitionNotPermittedError,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_event_repository import (
    OnboardingEventRepository,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_request_repository import (
    OnboardingRequestRepository,
)

logger = structlog.get_logger(__name__)

#: ``onboarding_event.event_type`` for a lifecycle status change.
STATUS_CHANGED_EVENT_TYPE = "onboarding_request.status_changed"


@dataclass(frozen=True)
class OnboardingTransitionResult:
    """The outcome of a successful — or already completed — transition."""

    onboarding_request_id: uuid.UUID
    from_status: OnboardingRequestStatus
    to_status: OnboardingRequestStatus
    event_id: uuid.UUID
    #: True when this call wrote nothing because the transition had already happened.
    already_applied: bool


class OnboardingTransitionService:
    """Apply onboarding request status transitions. Instantiate per unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._requests = OnboardingRequestRepository(session)
        self._events = OnboardingEventRepository(session)

    async def transition(
        self,
        onboarding_request_id: uuid.UUID,
        *,
        expected_status: OnboardingRequestStatus,
        to_status: OnboardingRequestStatus,
        actor_id: str | None,
        occurred_at: datetime | None = None,
        rejection_category: OnboardingRejectionCategory | None = None,
        rejection_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OnboardingTransitionResult:
        """Move the request from ``expected_status`` to ``to_status`` and record the event.

        Raises:
            OnboardingTransitionNotPermittedError: the lifecycle does not permit the
                move, or the rejection details are missing or do not fit it.
            OnboardingRequestNotFoundError: no such request.
            OnboardingStatusConflictError: the request is in another status and this
                transition has not already been applied.
        """
        self._validate(expected_status, to_status, rejection_category, rejection_reason)

        try:
            moved = await self._requests.compare_and_set_status(
                onboarding_request_id,
                expected_status=expected_status,
                to_status=to_status,
                occurred_at=occurred_at,
                set_initiated_at=expected_status == OnboardingRequestStatus.DRAFT,
                set_completed_at=to_status in TERMINAL_STATUSES,
                rejection_category=rejection_category,
                rejection_reason=rejection_reason,
            )
            if not moved:
                await self._session.rollback()
                return await self._resolve_unmoved(
                    onboarding_request_id, expected_status=expected_status, to_status=to_status
                )

            event = await self._events.create(
                OnboardingEvent(
                    onboarding_request_id=onboarding_request_id,
                    event_type=STATUS_CHANGED_EVENT_TYPE,
                    from_status=expected_status.value,
                    to_status=to_status.value,
                    actor_id=actor_id,
                    event_metadata=self._event_metadata(
                        metadata, rejection_category, rejection_reason
                    ),
                )
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        logger.info(
            "onboarding_request_transition_applied",
            onboarding_request_id=str(onboarding_request_id),
            from_status=expected_status.value,
            to_status=to_status.value,
            event_id=str(event.id),
        )
        return OnboardingTransitionResult(
            onboarding_request_id=onboarding_request_id,
            from_status=expected_status,
            to_status=to_status,
            event_id=event.id,
            already_applied=False,
        )

    @staticmethod
    def _validate(
        from_status: OnboardingRequestStatus,
        to_status: OnboardingRequestStatus,
        rejection_category: OnboardingRejectionCategory | None,
        rejection_reason: str | None,
    ) -> None:
        if not is_permitted(from_status, to_status):
            raise OnboardingTransitionNotPermittedError(from_status.value, to_status.value)

        if to_status == OnboardingRequestStatus.REJECTED:
            if rejection_category is None:
                raise OnboardingTransitionNotPermittedError(
                    from_status.value, to_status.value, "a rejection category is required"
                )
            if not is_permitted_rejection_category(from_status, rejection_category):
                raise OnboardingTransitionNotPermittedError(
                    from_status.value,
                    to_status.value,
                    f"rejection category {rejection_category.value} does not apply here",
                )
        elif rejection_category is not None or rejection_reason is not None:
            raise OnboardingTransitionNotPermittedError(
                from_status.value,
                to_status.value,
                "rejection details are only recorded on a rejection",
            )

    async def _resolve_unmoved(
        self,
        onboarding_request_id: uuid.UUID,
        *,
        expected_status: OnboardingRequestStatus,
        to_status: OnboardingRequestStatus,
    ) -> OnboardingTransitionResult:
        """Explain an update that matched nothing: already applied, or a conflict."""
        current_status = await self._requests.get_status(onboarding_request_id)
        if current_status is None:
            raise OnboardingRequestNotFoundError(str(onboarding_request_id))

        if current_status == to_status:
            event = await self._events.find_transition(
                onboarding_request_id,
                event_type=STATUS_CHANGED_EVENT_TYPE,
                from_status=expected_status.value,
                to_status=to_status.value,
            )
            if event is not None:
                logger.info(
                    "onboarding_request_transition_already_applied",
                    onboarding_request_id=str(onboarding_request_id),
                    from_status=expected_status.value,
                    to_status=to_status.value,
                    event_id=str(event.id),
                )
                return OnboardingTransitionResult(
                    onboarding_request_id=onboarding_request_id,
                    from_status=expected_status,
                    to_status=to_status,
                    event_id=event.id,
                    already_applied=True,
                )

        logger.warning(
            "onboarding_request_transition_status_conflict",
            onboarding_request_id=str(onboarding_request_id),
            expected_status=expected_status.value,
            current_status=current_status.value,
            to_status=to_status.value,
        )
        raise OnboardingStatusConflictError(
            str(onboarding_request_id),
            expected_status=expected_status.value,
            current_status=current_status.value,
            to_status=to_status.value,
        )

    @staticmethod
    def _event_metadata(
        metadata: dict[str, Any] | None,
        rejection_category: OnboardingRejectionCategory | None,
        rejection_reason: str | None,
    ) -> dict[str, Any] | None:
        combined: dict[str, Any] = dict(metadata or {})
        if rejection_category is not None:
            combined["rejection_category"] = rejection_category.value
            if rejection_reason is not None:
                combined["rejection_reason"] = rejection_reason
        return combined or None
