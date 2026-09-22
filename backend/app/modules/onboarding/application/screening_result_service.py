"""process_screening_result — the S5T1 onboarding screening state transition.

This is **not** a call into Epic 3.2. Epic 3.2 (Sanctions and Screening
Orchestration) does not exist yet in this codebase, and ``onboarding`` must
not import from it. This module is only the state-transition logic for what
happens to an ``onboarding_request`` once a screening result becomes
available — from wherever that result originates: a future real Epic 3.2
call, or in the near term, RXIL-sourced data recorded elsewhere. The caller
is responsible for obtaining the result; this function only applies it.

Per the ANER-4.1-S5T1 ticket:

* ``clear``           -> ``Screening Complete``, ``screening_reference_id`` stored.
* ``hard_block``      -> ``Rejected`` directly, ``rejection_category = SCREENING_BLOCK``,
                         ``rejection_reason`` populated.
* ``review_required`` -> ``Under Review``.

A naming note inherited from S1 (now fixed)
--------------------------------------------
The Epic 4.1 data model names a dedicated ``screening_result`` enum column on
``onboarding_request``. The column actually implemented in S1
(``onboarding_0002_orchestration_schema``) was named ``kyb_result`` despite
being typed with ``onboarding_screening_result_enum`` (``CLEAR`` /
``REVIEW_REQUIRED`` / ``HARD_BLOCK``) — i.e. it was the screening-result
column, just misnamed. That naming gap has since been corrected directly: the
column was renamed to ``screening_result`` (migration
``onboarding_0004_screening_fix``), including the write-once trigger
argument that protects it. This service writes the screening outcome to that
column under its correct name.

Precondition
------------
This function only accepts a transition from ``SCREENING_IN_PROGRESS``. Story
S3 (the Temporal workflow) owns the *complete* onboarding state machine; this
is only the narrow slice S5T1 asks for. A call from any other status raises
:class:`IllegalOnboardingTransitionError` rather than silently guessing.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingScreeningResult,
)
from app.modules.onboarding.exceptions import (
    IllegalOnboardingTransitionError,
    OnboardingFieldAlreadySetError,
)
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)

#: The onboarding_event.event_type recorded for every call. onboarding_event's
#: event_type is a free-text column (no DB enum), but the Epic 4.1 data model
#: names this exact value for this transition.
_EVENT_TYPE = "screening_result_received"

_IMMUTABLE_FIELD_PATTERN = re.compile(r"[Cc]olumn (\w+) is immutable once set")

_TARGET_STATUS: dict[OnboardingScreeningResult, OnboardingRequestStatus] = {
    OnboardingScreeningResult.CLEAR: OnboardingRequestStatus.SCREENING_COMPLETE,
    OnboardingScreeningResult.HARD_BLOCK: OnboardingRequestStatus.REJECTED,
    OnboardingScreeningResult.REVIEW_REQUIRED: OnboardingRequestStatus.UNDER_REVIEW,
}

_DEFAULT_HARD_BLOCK_REASON = (
    "Your onboarding could not proceed: screening returned a hard block on the entity or a related party."
)


def _as_screening_result(value: OnboardingScreeningResult | str) -> OnboardingScreeningResult:
    return value if isinstance(value, OnboardingScreeningResult) else OnboardingScreeningResult(str(value).upper())


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def process_screening_result(
    session: AsyncSession,
    onboarding_id: uuid.UUID | str,
    screening_result: OnboardingScreeningResult | str,
    screening_reference_id: uuid.UUID | str,
    *,
    rejection_reason: str | None = None,
    actor_id: str | None = None,
) -> OnboardingRequest:
    """Apply the S5T1 screening-result transition to one ``onboarding_request``.

    Args:
        session: An active async session. This function commits.
        onboarding_id: The onboarding_request to transition.
        screening_result: ``clear`` / ``review_required`` / ``hard_block``
            (case-insensitive string or :class:`OnboardingScreeningResult`).
        screening_reference_id: The foreign screening request id to store.
        rejection_reason: Plain-language reason to record when the result is
            ``hard_block``. Falls back to a generic message if omitted — the
            real Epic 3.2 integration is expected to always supply one, taken
            from the screening evidence package's ``primary_finding``.
        actor_id: The user or service recording this transition, for the
            ``onboarding_event`` audit row.

    Returns:
        The updated, refreshed :class:`OnboardingRequest`.

    Raises:
        NotFoundError: no onboarding_request exists with this id.
        IllegalOnboardingTransitionError: the onboarding is not currently in
            ``SCREENING_IN_PROGRESS``.
        OnboardingFieldAlreadySetError: the write-once ``screening_result``
            column was already set (defense-in-depth; the precondition above
            is what normally stops a second call).
    """
    result = _as_screening_result(screening_result)
    ref_id = _as_uuid(screening_reference_id)
    request_id = _as_uuid(onboarding_id)

    stmt = select(OnboardingRequest).where(OnboardingRequest.id == request_id).with_for_update()
    execution = await session.execute(stmt)
    request = execution.scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"onboarding_request '{request_id}' does not exist")

    if request.status is not OnboardingRequestStatus.SCREENING_IN_PROGRESS:
        raise IllegalOnboardingTransitionError(
            from_status=request.status.value,
            expected_status=OnboardingRequestStatus.SCREENING_IN_PROGRESS.value,
            action="record a screening result",
        )

    from_status = request.status
    to_status = _TARGET_STATUS[result]
    now = datetime.now(UTC)

    request.screening_result = result
    request.screening_reference_id = ref_id
    request.status = to_status
    request.last_activity_at = now

    event_metadata: dict[str, object] = {
        "screening_result": result.value,
        "screening_reference_id": str(ref_id),
    }

    if result is OnboardingScreeningResult.HARD_BLOCK:
        request.rejection_category = OnboardingRejectionCategory.SCREENING_BLOCK
        request.rejection_reason = rejection_reason or _DEFAULT_HARD_BLOCK_REASON
        request.completed_at = now
        event_metadata["rejection_reason"] = request.rejection_reason
        event_metadata["rejection_category"] = OnboardingRejectionCategory.SCREENING_BLOCK.value

    session.add(request)
    session.add(
        OnboardingEvent(
            onboarding_request_id=request.id,
            event_type=_EVENT_TYPE,
            from_status=from_status.value,
            to_status=to_status.value,
            actor_id=actor_id,
            event_metadata=event_metadata,
        )
    )

    try:
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        raw_message = str(exc.orig) if exc.orig is not None else str(exc)
        match = _IMMUTABLE_FIELD_PATTERN.search(raw_message)
        if match:
            raise OnboardingFieldAlreadySetError(field=match.group(1), onboarding_id=request_id) from exc
        raise

    await session.refresh(request)
    logger.info(
        "onboarding.screening_result.processed",
        onboarding_id=str(request_id),
        screening_result=result.value,
        from_status=from_status.value,
        to_status=to_status.value,
    )
    return request


__all__ = ["process_screening_result"]
