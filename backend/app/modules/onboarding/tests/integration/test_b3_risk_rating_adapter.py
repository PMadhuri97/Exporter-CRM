"""Integration tests for B3: `RiskRatingAdapter` and the RISK_RATING check type.

Follows `test_exp3_stub_rxil_adapter.py`'s conventions: real Postgres, no
per-test rollback, each test mints its own fresh ids.

The database matters here in a way it does not for a pure adapter test. The
whole point of `onboarding_0013_risk_check` is that
`verification_result.verification_type` is a *native* Postgres enum, so
"`VerificationType.RISK_RATING` exists in Python" and "a RISK_RATING row can be
written" are two different claims. Only a round trip through
`VerificationService` proves the second one.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRiskRating,
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.workflow_dependencies import (
    DECLARED_ADAPTER_PATHS,
    VERIFICATION_ADAPTER_REGISTRY,
    VerificationAdapter,
    VerificationRequest,
    get_adapter,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
)
from app.modules.onboarding.infrastructure.adapters.risk_rating_adapter import (
    _RATING_TO_RISK_LEVEL,
    PROVIDER_NAME,
    REGISTRY_KEY,
    RiskRatingAdapter,
)
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


def _actor() -> str:
    return f"officer-{uuid.uuid4().hex[:8]}"


#: The minimum a caller must supply. Everything else the calculator treats as
#: not-yet-declared rather than failing on.
_MINIMAL_PAYLOAD = {"entity_type": "CORPORATION", "registration_country": "GB"}

#: Chosen to clear the config's `thresholds.high_max` on its own — a DNFBP
#: sector, a PEP among the UBOs and a screening result that already asked for
#: review. Asserted below to land on CRITICAL, which is the band that did not
#: exist before Phase A.
_CRITICAL_PAYLOAD = {
    "entity_type": "CORPORATION",
    "registration_country": "IN",
    "sector_code": "DNFBP",
    "declared_monthly_volume_usd": 750000,
    "ubo_count": 2,
    "ubo_pep_statuses": ["PEP", "NOT_PEP"],
    "screening_result": "REVIEW_REQUIRED",
}


def _request(payload: dict) -> VerificationRequest:
    return VerificationRequest(
        verification_type=VerificationType.RISK_RATING,
        entity_type=VerificationEntityType.EXPORTER,
        entity_reference=str(uuid.uuid4()),
        payload=payload,
    )


# ── Registry / Protocol shape (TASK 1) ────────────────────────────────────────


async def test_risk_rating_adapter_is_registered_under_its_published_key():
    assert REGISTRY_KEY in VERIFICATION_ADAPTER_REGISTRY
    assert get_adapter(REGISTRY_KEY) is RiskRatingAdapter


async def test_declared_path_and_registry_key_resolve_to_the_same_class():
    """The two halves of the published contract must not drift.

    `DECLARED_ADAPTER_PATHS` fixes the name before the adapter exists; the
    adapter's own `register_adapter` call claims it afterwards. If they ever
    named different classes, a caller resolving the name and a caller resolving
    the path would get different adapters and nothing would say so.
    """
    assert get_adapter(DECLARED_ADAPTER_PATHS[REGISTRY_KEY]) is RiskRatingAdapter
    assert get_adapter(REGISTRY_KEY) is get_adapter(DECLARED_ADAPTER_PATHS[REGISTRY_KEY])


async def test_a_published_but_unbuilt_name_says_so_rather_than_500ing():
    """`kyb` and `sumsub` are published (so the schema boundary admits them)
    before their adapters exist. That combination puts a name straight from a
    request body into `get_adapter`, so the "not yet" answer has to be an
    HTTP-mapped error, not the bare `ValueError` the other branches raise."""
    from app.modules.onboarding.exceptions import ProviderResolutionError

    unbuilt = [
        name
        for name in DECLARED_ADAPTER_PATHS
        if name not in VERIFICATION_ADAPTER_REGISTRY
    ]
    for name in unbuilt:
        with pytest.raises(ProviderResolutionError) as excinfo:
            get_adapter(name)
        assert excinfo.value.error_code == "PROVIDER_NOT_YET_BUILT"
        assert excinfo.value.status_code == 422


async def test_risk_rating_adapter_satisfies_the_protocol():
    adapter = RiskRatingAdapter()
    assert isinstance(adapter, VerificationAdapter)

    declaration = adapter.declare_capabilities()
    assert declaration.provider == PROVIDER_NAME
    assert declaration.supported_verification_types == (VerificationType.RISK_RATING,)
    assert VerificationEntityType.EXPORTER in declaration.supported_entity_types


async def test_every_rating_band_maps_onto_a_verification_risk_level():
    """Including CRITICAL — the band Phase A added. Before it, a CRITICAL
    rating had to be flattened onto HIGH."""
    assert set(_RATING_TO_RISK_LEVEL) == set(OnboardingRiskRating)
    assert _RATING_TO_RISK_LEVEL[OnboardingRiskRating.CRITICAL] is VerificationRiskLevel.CRITICAL


# ── The calculation (TASK 3) ──────────────────────────────────────────────────


async def test_a_clean_profile_passes_with_a_low_band():
    outcome = RiskRatingAdapter().verify(_request(_MINIMAL_PAYLOAD))

    assert outcome.status is VerificationResultStatus.PASSED
    assert outcome.risk_level is VerificationRiskLevel.LOW
    assert outcome.normalized_result["risk_rating"] == "LOW"


async def test_a_critical_profile_lands_on_critical_and_asks_for_review():
    outcome = RiskRatingAdapter().verify(_request(_CRITICAL_PAYLOAD))

    assert outcome.risk_level is VerificationRiskLevel.CRITICAL
    # Not FAILED: the calculator bands, it does not reject. The accept/reject
    # call is a compliance decision recorded against this row afterwards.
    assert outcome.status is VerificationResultStatus.REVIEW
    assert outcome.normalized_result["edd_required"] is True


async def test_the_same_signals_always_produce_the_same_band():
    adapter = RiskRatingAdapter()
    first = adapter.verify(_request(_CRITICAL_PAYLOAD))
    second = adapter.verify(_request(_CRITICAL_PAYLOAD))

    assert first.risk_level == second.risk_level
    assert first.normalized_result["score"] == second.normalized_result["score"]


async def test_a_payload_missing_a_required_signal_is_refused():
    with pytest.raises(InvalidProviderPayloadError):
        RiskRatingAdapter().verify(_request({"entity_type": "CORPORATION"}))


async def test_an_unknown_payload_key_is_refused_rather_than_ignored():
    """A typo'd key silently dropped would change the band without saying so."""
    with pytest.raises(InvalidProviderPayloadError, match="unknown key"):
        RiskRatingAdapter().verify(
            _request({**_MINIMAL_PAYLOAD, "sector": "DNFBP"}),
        )


async def test_polling_is_refused_because_the_check_is_synchronous():
    with pytest.raises(ProviderCapabilityError):
        RiskRatingAdapter().get_verification_status("anything")


# ── End to end through the service and the database (TASK 2 + TASK 3) ─────────


async def test_a_risk_rating_persists_as_a_verification_result_row():
    entity_reference = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.RISK_RATING,
            VerificationEntityType.EXPORTER,
            entity_reference,
            provider=REGISTRY_KEY,
            payload=dict(_CRITICAL_PAYLOAD),
            actor_id=_actor(),
        )
        result_id = result.id

    async with db_services.AsyncSessionLocal() as db:
        stored = (
            await db.execute(
                select(VerificationResult).where(VerificationResult.id == result_id)
            )
        ).scalar_one()

        # The native enum accepted the new label — which is the whole of what
        # `onboarding_0013_risk_check` exists to make true.
        assert stored.verification_type is VerificationType.RISK_RATING
        assert stored.risk_level is VerificationRiskLevel.CRITICAL
        assert stored.status is VerificationResultStatus.REVIEW


async def test_the_stored_provider_names_the_rater_and_is_never_rewritten():
    """The EXP-2 provenance guarantee, for a producer that is not a human.

    The caller asks for the registry key (`risk_rating`); what lands on the row
    is the adapter's own self-reported name (`aner-risk-rating`). Neither is
    `"manual"`, and the service substitutes neither.
    """
    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.RISK_RATING,
            VerificationEntityType.EXPORTER,
            uuid.uuid4(),
            provider=REGISTRY_KEY,
            payload=dict(_MINIMAL_PAYLOAD),
            actor_id=_actor(),
        )

        assert result.provider == PROVIDER_NAME
        assert result.provider != REGISTRY_KEY
        assert result.provider != "manual"


async def test_a_risk_rating_cannot_be_run_against_a_trade_object():
    """`_VALID_ENTITY_TYPES_FOR_CHECK` gained a RISK_RATING entry with the
    check type; a composite rating about an invoice is uninterpretable."""
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await VerificationService(db).trigger_verification(
                VerificationType.RISK_RATING,
                VerificationEntityType.INVOICE,
                uuid.uuid4(),
                provider=REGISTRY_KEY,
                payload=dict(_MINIMAL_PAYLOAD),
                actor_id=_actor(),
            )
