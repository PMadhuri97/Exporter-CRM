"""assign_risk_rating — application wrapper for the S5T2 risk rating calculation.

Pulls the risk-scoring inputs off a persisted ``onboarding_request`` and its
``ubo_records``, delegates the actual composite scoring to the pure
:class:`~app.modules.onboarding.domain.policies.risk_rating_service.RiskRatingService`
(the real deliverable of ANER-4.1-S5T2), and persists the result.

Scope
-----
This function only advances ``status`` from ``RISK_RATING_IN_PROGRESS`` to
``RISK_RATED`` — mirroring the state machine row "Risk Rating In Progress ->
Risk Rated: Risk rating assigned". It does **not** decide ``Approved`` vs
``Pending Compliance Approval``: that routing, and any consequence of
``edd_required=True``, is ANER-4.1-S5T3, which is explicitly out of scope for
this build (it needs Epic 5.4's Maker-Checker, which does not exist yet). See
the risk rating service's module docstring for the full explanation of why
``edd_required`` currently has no automated consequence.

``kyb_discrepancies`` is accepted as an explicit parameter rather than read
from the database because ``kyb_vendor_result`` (as implemented in S1) has no
``discrepancies`` column — another real schema gap relative to the Epic 4.1
data model, which specifies one. The discrepancy list is expected to come
from the KYB verification result at the time it was received (the adapters'
``KYBVerificationResult.discrepancies``, e.g. in
``app/modules/kyb/infrastructure/adapters/trulioo/adapter.py``), not a
re-read of persisted state.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import OnboardingRequestStatus
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.domain.policies.risk_rating_service import RiskRatingService
from app.modules.onboarding.exceptions import (
    IllegalOnboardingTransitionError,
    OnboardingFieldAlreadySetError,
)
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)

_EVENT_TYPE = "risk_rating_assigned"
_IMMUTABLE_FIELD_PATTERN = re.compile(r"[Cc]olumn (\w+) is immutable once set")


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def assign_risk_rating(
    session: AsyncSession,
    onboarding_id: uuid.UUID | str,
    risk_rating_service: RiskRatingService,
    *,
    kyb_discrepancies: Sequence[str] | None = None,
    actor_id: str | None = None,
) -> OnboardingRequest:
    """Calculate and persist the risk rating for one ``onboarding_request``.

    Args:
        session: An active async session. This function commits.
        onboarding_id: The onboarding_request to rate.
        risk_rating_service: The config-driven calculator (see
            ``infrastructure/risk_rating_config_loader.load_risk_rating_service``
            for the GitOps-managed default).
        kyb_discrepancies: KYB discrepancy descriptions for this onboarding, if
            any (see module docstring for why this is a parameter, not a read).
        actor_id: The user or service recording this transition.

    Returns:
        The updated, refreshed :class:`OnboardingRequest`, with ``risk_rating``
        and ``risk_rating_factors`` populated.

    Raises:
        NotFoundError: no onboarding_request exists with this id.
        IllegalOnboardingTransitionError: the onboarding is not currently in
            ``RISK_RATING_IN_PROGRESS``.
        OnboardingFieldAlreadySetError: ``risk_rating_factors`` was already set
            (defense-in-depth; the precondition above is what normally stops a
            second call).
    """
    request_id = _as_uuid(onboarding_id)

    stmt = select(OnboardingRequest).where(OnboardingRequest.id == request_id).with_for_update()
    execution = await session.execute(stmt)
    request = execution.scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"onboarding_request '{request_id}' does not exist")

    if request.status is not OnboardingRequestStatus.RISK_RATING_IN_PROGRESS:
        raise IllegalOnboardingTransitionError(
            from_status=request.status.value,
            expected_status=OnboardingRequestStatus.RISK_RATING_IN_PROGRESS.value,
            action="assign a risk rating",
        )

    ubo_execution = await session.execute(
        select(UboRecord).where(UboRecord.onboarding_request_id == request_id)
    )
    ubo_records = list(ubo_execution.scalars().all())
    ubo_pep_statuses = [u.pep_status.value for u in ubo_records if u.pep_status is not None]

    rating = risk_rating_service.calculate(
        entity_type=request.entity_type.value,
        registration_country=request.incorporation_country,
        sector_code=request.industry_code,
        declared_monthly_volume_usd=request.declared_monthly_volume_usd,
        ubo_count=len(ubo_records),
        ubo_pep_statuses=ubo_pep_statuses,
        screening_result=request.screening_result,
        kyb_discrepancies=kyb_discrepancies,
    )

    from_status = request.status
    now = datetime.now(UTC)

    request.risk_rating = rating.risk_rating
    request.risk_rating_factors = rating.to_risk_rating_factors_json()
    # edd_required/edd_reason now have dedicated columns (see
    # RiskRatingResult.to_risk_rating_factors_json's docstring for why they
    # are also kept in risk_rating_factors as an audit-grade duplication).
    request.edd_required = rating.edd_required
    request.edd_reason = rating.edd_reason
    request.status = OnboardingRequestStatus.RISK_RATED
    request.last_activity_at = now

    session.add(request)
    session.add(
        OnboardingEvent(
            onboarding_request_id=request.id,
            event_type=_EVENT_TYPE,
            from_status=from_status.value,
            to_status=OnboardingRequestStatus.RISK_RATED.value,
            actor_id=actor_id,
            event_metadata={
                "score": rating.score,
                "risk_rating": rating.risk_rating.value,
                "edd_required": rating.edd_required,
                "edd_reason": rating.edd_reason,
            },
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
        "onboarding.risk_rating.assigned",
        onboarding_id=str(request_id),
        risk_rating=rating.risk_rating.value,
        score=rating.score,
        edd_required=rating.edd_required,
    )
    return request


__all__ = ["assign_risk_rating"]
