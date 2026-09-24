"""`SumsubVerificationAdapter` — Sumsub KYC for directors and UBOs (B5).

Sumsub has a working provider (`app.integrations.identity_providers.sumsub.
SumsubProvider`) and a working webhook route, but neither is reachable from the
Exporter CRM: the provider is resolved only by `resolve_identity_provider()`,
which serves the legacy `/register` flow, and `SUMSUB_ENABLED` is false by
default. This wraps it as a `VerificationAdapter` so a director or UBO check
runs through the same `trigger_verification` call as every other check and lands
in `verification_result` with `provider = "sumsub"`.

The flag is honoured, not bypassed. `SUMSUB_ENABLED=false` (the default, and
what CI runs) makes every call raise `ProviderNotEnabledError`; nothing here
falls back to the mock, because a mock answer persisted into
`verification_result` would be a fabricated KYC record.

**Why this adapter does not call Sumsub**
`BaseIdentityProvider` is asynchronous where it does I/O
(`create_applicant`, `generate_sdk_token` are `async`; only `parse_webhook` is
synchronous) and `VerificationAdapter.verify()` is synchronous, constructed
zero-argument by `verification_service.trigger_verification`. There is no
supported way to await from inside `verify()`.

That is not the obstacle it looks like, because Sumsub is not a request/response
vendor in the first place: creating an applicant does not verify anybody. A
human then completes a flow in the Sumsub SDK — minutes or days later — and the
answer arrives as a webhook. A synchronous `verify()` could never have returned
a real result.

So `verify()` handles the two things that *are* synchronous, and refuses
clearly for the third:

* `payload["webhook"]` — a raw Sumsub webhook body. Parsed through the
  provider's own `parse_webhook()` and translated into a terminal outcome. This
  is the path that gets a Sumsub answer into `verification_result`.
* `payload["applicant_id"]` — an applicant already created out of band. Returns
  `PENDING` carrying that id as `provider_reference`, which is the honest
  answer: submitted, not yet decided.
* Neither — `InvalidProviderPayloadError` naming `create_applicant_for()`, the
  async helper below that an async caller uses to create the applicant first.

Directors and UBOs
------------------
`VerificationEntityType` has `DIRECTOR` but no `UBO` member, and adding one is
an enum change this lane may not make. A UBO is therefore recorded as
`DIRECTOR` — both are natural persons behind an exporter, and `_VALID_ENTITY_
TYPES_FOR_CHECK` already pairs `KYC` with `DIRECTOR`. Which of the two a row
describes is preserved in `normalized_result["subject_role"]` when the caller
says so, so the distinction is not lost even though the enum cannot carry it.
Flagged in this phase's report rather than worked around silently.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    VerificationRequest,
    register_adapter,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
    ProviderNotEnabledError,
)
from app.platform.configuration.config import get_settings
from app.shared.contracts.identity import WebhookParseResult
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum

logger = structlog.get_logger(__name__)

#: Registry name and reported provider. One constant, following
#: `ManualEntryAdapter`: unlike the KYB adapter, this one fronts a single vendor,
#: so the registry name and the persisted provenance genuinely are the same
#: thing and must not drift.
PROVIDER_NAME = "sumsub"

#: KYC against a natural person. `DIRECTOR` covers UBOs too — see the module
#: docstring. `BUYER` is offered because `_VALID_ENTITY_TYPES_FOR_CHECK` pairs
#: `KYC` with it and a buyer may be an individual.
_SUPPORTED_VERIFICATION_TYPES: tuple[VerificationType, ...] = (VerificationType.KYC,)
_SUPPORTED_ENTITY_TYPES: tuple[VerificationEntityType, ...] = (
    VerificationEntityType.DIRECTOR,
    VerificationEntityType.BUYER,
)


def _require_enabled() -> None:
    """Refuse unless Sumsub is switched on *and* has credentials.

    Three separate checks because they fail for different reasons and a
    deployment can get any one of them wrong on its own. All three raise the
    same 422 `ProviderNotEnabledError`; none of them falls through to a mock or
    to a default-pass. A KYC record that says "verified" because a credential
    was missing is the single worst outcome available here.
    """
    settings = get_settings()
    if not getattr(settings, "SUMSUB_ENABLED", False):
        raise ProviderNotEnabledError(PROVIDER_NAME)
    if not (getattr(settings, "SUMSUB_APP_TOKEN", "") or "").strip():
        raise ProviderNotEnabledError(PROVIDER_NAME)
    if not (getattr(settings, "SUMSUB_SECRET_KEY", "") or "").strip():
        raise ProviderNotEnabledError(PROVIDER_NAME)


def _live_provider() -> Any:
    """The real `SumsubProvider`, imported lazily.

    Deliberately not `resolve_identity_provider()`: that returns
    `MockIdentityProvider` whenever `SUMSUB_ENABLED` is false, and a mock's
    answer must never reach `verification_result` through this adapter.
    `_require_enabled()` has already established the flag is on by the time
    anything calls this.
    """
    from app.integrations.identity_providers.sumsub import SumsubProvider

    return SumsubProvider()


async def create_applicant_for(
    external_user_id: str,
    *,
    level_name: str | None = None,
) -> str:
    """Create the Sumsub applicant and return its id, for an async caller.

    The asynchronous half of this integration, which `verify()` cannot perform.
    A caller runs this, then passes the returned id as
    `payload["applicant_id"]` to record a `PENDING` row — or hands it to the
    frontend to launch the SDK flow, and lets the webhook supply the answer.
    """
    _require_enabled()
    settings = get_settings()
    provider = _live_provider()
    result = await provider.create_applicant(
        external_user_id,
        level_name or getattr(settings, "SUMSUB_LEVEL_NAME", "basic-kyc-level"),
    )
    logger.info(
        "sumsub_verification.applicant_created",
        applicant_id=result.applicant_id,
        external_user_id=result.external_user_id,
    )
    return str(result.applicant_id)


def _status_from_webhook(parsed: WebhookParseResult) -> VerificationResultStatus:
    """Sumsub's review answer → this platform's status.

    `WebhookParseResult` exposes `approved`/`rejected` as GREEN/RED properties.
    Anything else — a review still open, an answer Sumsub has not given yet, a
    value neither GREEN nor RED — is `REVIEW`. There is deliberately no branch
    that turns an unrecognised answer into `PASSED`.
    """
    if parsed.approved:
        return VerificationResultStatus.PASSED
    if parsed.rejected:
        return VerificationResultStatus.FAILED
    return VerificationResultStatus.REVIEW


def _outcome_from_webhook(
    parsed: WebhookParseResult,
    *,
    subject_role: str | None,
) -> VerificationOutcome:
    status = _status_from_webhook(parsed)
    return VerificationOutcome(
        provider=PROVIDER_NAME,
        provider_reference=parsed.applicant_id,
        status=status,
        normalized_result={
            "event_type": parsed.event_type,
            "applicant_id": parsed.applicant_id,
            "external_user_id": parsed.external_user_id,
            "review_status": parsed.review_status,
            "review_answer": parsed.review_answer,
            "subject_role": subject_role,
        },
        # A rejected KYC on a director is a real risk signal; Sumsub gives no
        # numeric score through this contract, so HIGH is the honest band and
        # anything else stays unbanded (the column is nullable for this).
        risk_level=VerificationRiskLevel.HIGH
        if status is VerificationResultStatus.FAILED
        else None,
    )


class SumsubVerificationAdapter:
    """A `VerificationAdapter` fronting Sumsub, behind `SUMSUB_ENABLED`."""

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        """Asynchronous: the answer arrives by webhook, never from `verify()`."""
        return VerificationCapabilityDeclaration(
            provider=PROVIDER_NAME,
            supported_verification_types=_SUPPORTED_VERIFICATION_TYPES,
            supported_entity_types=_SUPPORTED_ENTITY_TYPES,
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Record a Sumsub KYC outcome, or the fact that one is pending.

        See the module docstring for why this does not itself call Sumsub.
        Raises `ProviderNotEnabledError` (422) when the flag or credentials are
        absent, and `InvalidProviderPayloadError` (422) when the payload
        carries neither a webhook body nor an applicant id.
        """
        _require_enabled()

        payload = dict(request.payload or {})
        subject_role = payload.get("subject_role")

        webhook = payload.get("webhook")
        if webhook is not None:
            if not isinstance(webhook, dict):
                raise InvalidProviderPayloadError(
                    "sumsub payload's 'webhook' must be the raw webhook body as an object",
                    provider_name=PROVIDER_NAME,
                )
            parsed = _live_provider().parse_webhook(webhook)
            logger.info(
                "sumsub_verification.webhook_translated",
                applicant_id=parsed.applicant_id,
                review_answer=parsed.review_answer,
            )
            return _outcome_from_webhook(parsed, subject_role=subject_role)

        applicant_id = payload.get("applicant_id")
        if applicant_id:
            return VerificationOutcome(
                provider=PROVIDER_NAME,
                provider_reference=str(applicant_id),
                status=VerificationResultStatus.PENDING,
                normalized_result={
                    "applicant_id": str(applicant_id),
                    "external_user_id": payload.get("external_user_id"),
                    "subject_role": subject_role,
                    "awaiting": "sumsub_webhook",
                },
                risk_level=None,
            )

        raise InvalidProviderPayloadError(
            "sumsub verification needs either 'webhook' (a raw Sumsub webhook body) "
            "or 'applicant_id' (an applicant already created). Sumsub answers "
            "asynchronously, so there is no synchronous check to run: create the "
            "applicant first with "
            "sumsub_verification_adapter.create_applicant_for(external_user_id).",
            provider_name=PROVIDER_NAME,
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Not available: `SumsubProvider` exposes no status-fetch method.

        Its contract is `create_applicant` / `generate_sdk_token` /
        `parse_webhook` — there is no "get applicant status" call to make, so
        there is nothing to poll even setting the sync/async problem aside.
        Sumsub results arrive by webhook; that is the delivery mechanism, and
        this phase's TASK 4 report says what wiring it into
        `verification_result` needs.

        Raises `ProviderCapabilityError` (422) rather than returning a status
        that would misrepresent an unknown as an answer.
        """
        raise ProviderCapabilityError(PROVIDER_NAME, "get_verification_status")

    def get_vendor_health(self) -> VendorHealthStatus:
        """Configuration health only — no network call.

        `SumsubProvider` has no health endpoint in its contract, and a health
        check is called often enough that it must not become an unbounded
        outbound request. `DOWN` when disabled or uncredentialled is the
        actionable answer: those are the states that stop verification working,
        and they are knowable locally.
        """
        started = time.monotonic()
        try:
            _require_enabled()
        except ProviderNotEnabledError:
            return VendorHealthStatus(
                status=VendorHealthStatusEnum.DOWN,
                response_time_ms=int((time.monotonic() - started) * 1000),
                known_issues=(
                    "sumsub is disabled or has no credentials "
                    "(SUMSUB_ENABLED / SUMSUB_APP_TOKEN / SUMSUB_SECRET_KEY)"
                ),
            )
        return VendorHealthStatus(
            status=VendorHealthStatusEnum.HEALTHY,
            response_time_ms=int((time.monotonic() - started) * 1000),
        )


# See the note on `register_adapter` in `kyb_verification_adapter`: the adapters
# package does not import this module, so the short name resolves only once
# something has imported it — which resolving the full dotted path does.
register_adapter(PROVIDER_NAME, SumsubVerificationAdapter)

__all__ = [
    "PROVIDER_NAME",
    "SumsubVerificationAdapter",
    "create_applicant_for",
]
