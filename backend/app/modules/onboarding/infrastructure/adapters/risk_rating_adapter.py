"""`RiskRatingAdapter` — the composite risk rating, recorded as a verification
check (B3).

Before this, `ConfigDrivenRiskRater` and `assign_risk_rating` were the only two
callers of the S5T2 scoring algorithm, and both write their answer onto
`onboarding_request.risk_rating`. Neither produces a `VerificationResult`, so a
risk rating was invisible to every surface built on that table: the exporter's
screening workspace, the compliance review path, and the provenance guarantee
that every recorded finding names the thing that produced it. This adapter
closes that: a rating now lands on `verification_result` as a
`VerificationType.RISK_RATING` row like any other check, carrying its band in
`risk_level` and its full factor breakdown in `normalized_result`.

The first wiring with no vendor behind it
-----------------------------------------
Every other adapter in this registry is waiting on a credential or an
integration spec. This one is not: the scoring is a pure function of its inputs
and a GitOps-managed YAML (`deployments/gitops/reference-data/compliance/
risk-rating/risk-rating-config.yaml`), so it works end to end the moment it is
registered — which is exactly why it is the phase's proof that the
`VerificationAdapter` pattern holds.

Why this reuses the calculator rather than calling `ConfigDrivenRiskRater`
--------------------------------------------------------------------------
This is a deliberate, documented divergence from "wrap `ConfigDrivenRiskRater`",
and it is forced by the Protocol, not chosen for convenience.
`VerificationAdapter.verify` is **synchronous** — `VerificationService.
trigger_verification` calls `adapter.verify(request)` with no `await`, on the
request's own event loop. `ConfigDrivenRiskRater.rate` is `async` and opens its
own `AsyncSessionLocal()` against the process-wide async engine. There is no
sound way to drive an `async` call that uses that engine from inside a
synchronous function already running on the loop that owns it: bridging it to a
worker thread would hand asyncpg connections created on one event loop to
another, which is exactly the failure mode `pool_pre_ping` cannot save you from.

So the two stay as two adapters over *one* calculator, which is the thing that
actually matters — there is no second scoring algorithm anywhere:

* `ConfigDrivenRiskRater` — the **async** adapter, for AL-672's Temporal
  workflow. Keyed by `onboarding_request_id`, loads its own inputs, persists
  onto `onboarding_request` (write-once, hence idempotent).
* `RiskRatingAdapter` (this file) — the **synchronous** adapter, for the
  `VerificationAdapter` registry. Takes its inputs from `request.payload`,
  persists nothing itself (`VerificationService` writes the row).

Both call `load_risk_rating_service()` and `RiskRatingService.calculate` — the
same loader, the same config file, the same method. A rating computed here and
a rating computed by the workflow for the same signals are identical by
construction.

Where the inputs come from
--------------------------
`request.payload`, under the exact parameter names
`RiskRatingService.calculate` uses. This is the convention `ManualEntryAdapter`
established and `StubRxilAdapter` followed: the caller and the adapter agree on
the payload's shape, and the service layer in between stays ignorant of it. The
alternative — the adapter reading `onboarding_request` itself — is the async
problem above.

Only `entity_type` and `registration_country` are required; every other signal
is genuinely optional in the calculator (`sector_code`, volume, screening and
UBO data are all nullable on `onboarding_request`, and the calculator bands a
missing value rather than failing on it).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRiskRating,
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.policies.risk_rating_service import (
    RiskRatingResult,
    RiskRatingService,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    DECLARED_ADAPTER_PATHS,
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    VerificationRequest,
    register_adapter,
)
from app.modules.onboarding.exceptions import InvalidProviderPayloadError, ProviderCapabilityError
from app.modules.onboarding.infrastructure.risk_rating_config_loader import (
    load_risk_rating_service,
)
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum

#: What this adapter reports as `VerificationOutcome.provider`, persisted
#: verbatim onto `VerificationResult.provider` and never rewritten.
#:
#: Deliberately *not* `"manual"`. The provenance guarantee EXP-2 was built
#: around is that a result names what produced it, and a rating produced by
#: this platform's own config-driven calculator is not a human's observation.
#: A reader (and the UI's "Source: {provider}" line) can tell the two apart.
PROVIDER_NAME = "aner-risk-rating"

#: The registry key callers pass as `provider`. Lower-case, matching the
#: convention at the schema boundary (`api/schemas/verification.py`'s
#: `VerificationProvider`), and distinct from `PROVIDER_NAME` for the same
#: reason `StubRxilAdapter`'s is: a registry key is a caller-facing routing
#: string, not the provider's own identity.
REGISTRY_KEY = "risk_rating"

#: `OnboardingRiskRating` (what the calculator returns) -> `VerificationRiskLevel`
#: (what a `VerificationResult` row records). The two vocabularies have the same
#: four members, but they are different enums for different tables, so the
#: mapping is written out rather than assumed — and `CRITICAL` only has a target
#: at all because of the `VerificationRiskLevel.CRITICAL` member added in Phase A
#: (`onboarding_0012_risk_critical`). Before it, a CRITICAL rating had to be
#: flattened onto HIGH, losing the distinction the band exists to make.
_RATING_TO_RISK_LEVEL: dict[OnboardingRiskRating, VerificationRiskLevel] = {
    OnboardingRiskRating.LOW: VerificationRiskLevel.LOW,
    OnboardingRiskRating.MEDIUM: VerificationRiskLevel.MEDIUM,
    OnboardingRiskRating.HIGH: VerificationRiskLevel.HIGH,
    OnboardingRiskRating.CRITICAL: VerificationRiskLevel.CRITICAL,
}

_UNMAPPED_RATINGS = set(OnboardingRiskRating) - set(_RATING_TO_RISK_LEVEL)
if _UNMAPPED_RATINGS:  # pragma: no cover — guards a source edit, not input
    raise RuntimeError(
        "_RATING_TO_RISK_LEVEL is missing an entry for: "
        + ", ".join(sorted(r.value for r in _UNMAPPED_RATINGS))
    )

#: Bands that mean a human has to look. A rating is never `FAILED`: the
#: calculator does not reject anyone, it bands them — the reject/approve call is
#: a compliance decision, recorded through `record_review` on the row this
#: adapter produces. `PENDING` would be wrong too: the check has run and
#: produced its final answer, synchronously.
_REVIEW_BANDS = frozenset({VerificationRiskLevel.HIGH, VerificationRiskLevel.CRITICAL})

#: Payload keys this adapter reads, i.e. `RiskRatingService.calculate`'s own
#: parameter names. An unknown key is a caller mistake worth surfacing rather
#: than a value silently ignored — the same stance `TriggerVerificationRequest`
#: takes with `extra="forbid"`.
_REQUIRED_PAYLOAD_KEYS = frozenset({"entity_type", "registration_country"})
_OPTIONAL_PAYLOAD_KEYS = frozenset(
    {
        "sector_code",
        "declared_monthly_volume_usd",
        "ubo_count",
        "ubo_pep_statuses",
        "screening_result",
        "kyb_discrepancies",
    }
)
_ALLOWED_PAYLOAD_KEYS = _REQUIRED_PAYLOAD_KEYS | _OPTIONAL_PAYLOAD_KEYS


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidProviderPayloadError(
            f"risk rating payload requires a non-empty '{key}'",
            provider_name=PROVIDER_NAME,
        )
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidProviderPayloadError(
            f"risk rating payload's '{key}' must be a non-empty string when present",
            provider_name=PROVIDER_NAME,
        )
    return value.strip()


def _optional_number(payload: dict[str, Any], key: str) -> int | float | None:
    value = payload.get(key)
    if value is None:
        return None
    # `bool` is an `int` subclass; a boolean here is a caller mistake, not a
    # volume of 1.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidProviderPayloadError(
            f"risk rating payload's '{key}' must be a number when present",
            provider_name=PROVIDER_NAME,
        )
    if value < 0:
        raise InvalidProviderPayloadError(
            f"risk rating payload's '{key}' must not be negative",
            provider_name=PROVIDER_NAME,
        )
    return value


def _optional_str_list(payload: dict[str, Any], key: str) -> Sequence[str] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvalidProviderPayloadError(
            f"risk rating payload's '{key}' must be a list of strings when present",
            provider_name=PROVIDER_NAME,
        )
    return value


class RiskRatingAdapter:
    """A `VerificationAdapter` over this platform's own risk-rating calculator."""

    def __init__(self, risk_rating_service: RiskRatingService | None = None) -> None:
        # Lazy default, matching `ConfigDrivenRiskRater`: the GitOps YAML is
        # only read if the caller does not inject a service. `VerificationService`
        # constructs adapters with no arguments (`adapter_cls()`), so the
        # injected form exists for tests, which build one from an in-memory
        # config rather than the filesystem.
        self._risk_rating_service = risk_rating_service

    def _service(self) -> RiskRatingService:
        if self._risk_rating_service is None:
            self._risk_rating_service = load_risk_rating_service()
        return self._risk_rating_service

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=PROVIDER_NAME,
            supported_verification_types=(VerificationType.RISK_RATING,),
            # Matches `verification_service._VALID_ENTITY_TYPES_FOR_CHECK`'s
            # entry for RISK_RATING: a composite rating is about a
            # counterparty, never a trade object.
            supported_entity_types=(
                VerificationEntityType.EXPORTER,
                VerificationEntityType.BUYER,
            ),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Score `request.payload` and return the band as a `VerificationOutcome`.

        Raises:
            InvalidProviderPayloadError: the payload is missing a required
                signal, carries an unknown key, or carries one of the wrong type.
        """
        payload = request.payload

        unknown = set(payload) - _ALLOWED_PAYLOAD_KEYS
        if unknown:
            raise InvalidProviderPayloadError(
                f"risk rating payload has unknown key(s) {sorted(unknown)}; "
                f"allowed keys are {sorted(_ALLOWED_PAYLOAD_KEYS)}",
                provider_name=PROVIDER_NAME,
            )

        ubo_count = _optional_number(payload, "ubo_count")
        if ubo_count is not None and not isinstance(ubo_count, int):
            raise InvalidProviderPayloadError(
                "risk rating payload's 'ubo_count' must be a whole number",
                provider_name=PROVIDER_NAME,
            )

        rating = self._service().calculate(
            entity_type=_require_text(payload, "entity_type"),
            registration_country=_require_text(payload, "registration_country"),
            sector_code=_optional_text(payload, "sector_code"),
            declared_monthly_volume_usd=_optional_number(
                payload, "declared_monthly_volume_usd"
            ),
            ubo_count=int(ubo_count or 0),
            ubo_pep_statuses=_optional_str_list(payload, "ubo_pep_statuses"),
            screening_result=_optional_text(payload, "screening_result"),
            kyb_discrepancies=_optional_str_list(payload, "kyb_discrepancies"),
        )
        return self._outcome_from_rating(rating)

    def _outcome_from_rating(self, rating: RiskRatingResult) -> VerificationOutcome:
        risk_level = _RATING_TO_RISK_LEVEL[rating.risk_rating]
        needs_review = risk_level in _REVIEW_BANDS or rating.edd_required
        return VerificationOutcome(
            provider=PROVIDER_NAME,
            # Synchronous and self-contained: there is no vendor-side record to
            # poll for later, so there is no reference to hand back. Leaving it
            # `None` is also what keeps `get_verification_status` unreachable
            # for these rows (it looks a row up *by* provider_reference).
            provider_reference=None,
            status=(
                VerificationResultStatus.REVIEW
                if needs_review
                else VerificationResultStatus.PASSED
            ),
            # The full, human-readable factor breakdown — the same JSON shape
            # `onboarding_request.risk_rating_factors` stores, so a reader does
            # not have to learn two formats for the same computation.
            normalized_result=rating.to_risk_rating_factors_json(),
            risk_level=risk_level,
            # A rating is a point-in-time judgement that goes stale as the
            # signals behind it change, not a credential with a vendor-issued
            # expiry. Nothing here can honestly claim a validity window, so it
            # claims none.
            valid_until=None,
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Not applicable: a rating resolves synchronously in `verify()`.

        Same answer, and the same reasoning, as `ManualEntryAdapter`'s: there
        is no `NOT_SUPPORTED` member on `VerificationResultStatus` to return
        gracefully, so this raises rather than returning a status that would
        misrepresent what happened.
        """
        raise ProviderCapabilityError(PROVIDER_NAME, "get_verification_status")

    def get_vendor_health(self) -> VendorHealthStatus:
        """Always healthy: a pure calculator over a GitOps file has no external
        dependency that can be down. A malformed config is a startup-time
        `RiskRatingConfigurationError` from the loader, not a health state."""
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=0)


register_adapter(REGISTRY_KEY, RiskRatingAdapter)

# The registry key and the path published in `DECLARED_ADAPTER_PATHS` must
# describe the same class, or a caller resolving the name and a caller
# resolving the path get different adapters. Checked here, at import, because
# this is the file that owns both halves of the claim.
_DECLARED = DECLARED_ADAPTER_PATHS[REGISTRY_KEY]
if _DECLARED != f"{__name__}.{RiskRatingAdapter.__name__}":  # pragma: no cover
    raise RuntimeError(
        f"DECLARED_ADAPTER_PATHS[{REGISTRY_KEY!r}] is {_DECLARED!r}, but this "
        f"module registers {__name__}.{RiskRatingAdapter.__name__}"
    )

__all__ = ["PROVIDER_NAME", "REGISTRY_KEY", "RiskRatingAdapter"]
