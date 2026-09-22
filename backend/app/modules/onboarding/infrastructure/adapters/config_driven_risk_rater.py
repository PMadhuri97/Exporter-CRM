"""
:class:`ConfigDrivenRiskRater` — adapts Epic 4.1 S5T2's risk rating calculator to
AL-672's :class:`~app.modules.onboarding.domain.workflow_dependencies.RiskRater`
Protocol.

Story S5T2 built the actual composite-scoring algorithm
(:class:`~app.modules.onboarding.domain.policies.risk_rating_service.RiskRatingService`,
verified against the Epic 4.1 spec's three worked examples) and an application
function, ``assign_risk_rating``, that read an ``onboarding_request`` and its
``ubo_record`` rows, called the calculator, and persisted + transitioned the
request directly. AL-672's Temporal workflow needs the same calculation behind
a narrower interface: ``RiskRater.rate(onboarding_request_id) -> RiskRatingOutcome``,
with no status transition of its own — ``OnboardingActivities.rate_risk`` calls
this, then the workflow separately calls ``transition_onboarding_request`` (backed
by ``OnboardingTransitionService``) once it has the outcome. This class is that
adapter: it reuses ``RiskRatingService`` and the GitOps config loader unchanged,
and does not re-implement or fork the scoring algorithm.

**Idempotency.** ``risk_rating_factors`` is a write-once column (the
``trg_onboarding_request_field_immutability`` trigger — see
``onboarding_0002_orchestration_schema``). If it is already set for this request,
:meth:`rate` returns the previously computed outcome rather than recomputing —
satisfying the Protocol's "calling this again for the same request must return
the same reference, not start a second piece of work" rule for free, using the
same write-once column ``assign_risk_rating`` already relied on.

**One remaining, unresolved gap this adapter inherits rather than papers over**
(documented in the Epic 4.1 combined-branch reconciliation report — flagged
there for an explicit decision, not silently fixed here):

``kyb_discrepancies`` has no persisted source. ``kyb_vendor_result`` (as
implemented in S1) has no ``discrepancies`` column, so this adapter — like
``assign_risk_rating`` before it — always calls the calculator with
``kyb_discrepancies=None``. Nothing in AL-672 populates this either.

(The previously-documented ``screening_result``/``kyb_result`` naming gap was
fixed directly: the column is now named ``onboarding_request.screening_result``
— see ``screening_result_service.py``'s module docstring and the
``onboarding_0004_screening_fix`` migration.)
"""
from __future__ import annotations

import uuid

from app.modules.onboarding.domain.entities.orchestration_enums import OnboardingRiskRating
from app.modules.onboarding.domain.policies.risk_rating_service import RiskRatingService
from app.modules.onboarding.domain.workflow_dependencies import RiskRatingOutcome
from app.modules.onboarding.exceptions import OnboardingRequestNotFoundError
from app.modules.onboarding.infrastructure.repositories.onboarding_request_repository import (
    OnboardingRequestRepository,
)
from app.modules.onboarding.infrastructure.repositories.ubo_record_repository import (
    UboRecordRepository,
)
from app.modules.onboarding.infrastructure.risk_rating_config_loader import (
    load_risk_rating_service,
)
from app.platform.database import services as database


def _rating_reference(onboarding_request_id: uuid.UUID) -> str:
    """A stable per-request reference. ``risk_rating_factors`` is write-once, so a
    request is rated at most once — the id itself is already a unique, stable
    handle for "the rating computed for this request"."""
    return f"onboarding-risk-rating:{onboarding_request_id}"


class ConfigDrivenRiskRater:
    """``RiskRater`` backed by the GitOps-configured :class:`RiskRatingService`."""

    def __init__(self, risk_rating_service: RiskRatingService | None = None) -> None:
        # Lazy default, matching OnboardingRequestService's pattern for
        # DocumentRequirementsService: only touches the filesystem if the
        # caller does not inject one (tests inject one built from an
        # in-memory config).
        self._risk_rating_service = risk_rating_service

    def _service(self) -> RiskRatingService:
        if self._risk_rating_service is None:
            self._risk_rating_service = load_risk_rating_service()
        return self._risk_rating_service

    async def rate(self, onboarding_request_id: str) -> RiskRatingOutcome:
        request_id = uuid.UUID(onboarding_request_id)

        async with database.AsyncSessionLocal() as session:
            requests = OnboardingRequestRepository(session)
            request = await requests.get_by_id(request_id)
            if request is None:
                raise OnboardingRequestNotFoundError(onboarding_request_id)

            if request.risk_rating_factors is not None and request.risk_rating is not None:
                # Already computed on a previous attempt — idempotent replay.
                return RiskRatingOutcome(
                    rating_reference=_rating_reference(request_id),
                    rating=request.risk_rating.value,
                )

            ubos = await UboRecordRepository(session).list_by_onboarding_request(request_id)
            ubo_pep_statuses = [u.pep_status.value for u in ubos if u.pep_status is not None]

            rating = self._service().calculate(
                entity_type=request.entity_type.value,
                registration_country=request.incorporation_country,
                sector_code=request.industry_code,
                declared_monthly_volume_usd=request.declared_monthly_volume_usd,
                ubo_count=len(ubos),
                ubo_pep_statuses=ubo_pep_statuses,
                screening_result=request.screening_result,
                # Gap above: no persisted source for KYB discrepancies yet.
                kyb_discrepancies=None,
            )

            request.risk_rating = rating.risk_rating
            request.risk_rating_factors = rating.to_risk_rating_factors_json()
            # edd_required/edd_reason have dedicated columns as of migration
            # onboarding_0004_screening_fix; kept in risk_rating_factors too
            # (see RiskRatingResult.to_risk_rating_factors_json).
            request.edd_required = rating.edd_required
            request.edd_reason = rating.edd_reason
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                # Lost a race with another attempt computing the same
                # write-once fields: re-read and treat it as an idempotent
                # replay rather than surfacing a retryable-looking failure.
                refreshed = await requests.get_by_id(request_id)
                if (
                    refreshed is not None
                    and refreshed.risk_rating_factors is not None
                    and refreshed.risk_rating is not None
                ):
                    return RiskRatingOutcome(
                        rating_reference=_rating_reference(request_id),
                        rating=refreshed.risk_rating.value,
                    )
                raise

            assert isinstance(request.risk_rating, OnboardingRiskRating)
            return RiskRatingOutcome(
                rating_reference=_rating_reference(request_id),
                rating=request.risk_rating.value,
            )


__all__ = ["ConfigDrivenRiskRater"]
