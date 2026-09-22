"""`ManualEntryAdapter` — the one real `VerificationAdapter` this ticket ships.

Satisfies the Protocol by accepting a manually-supplied result rather than
calling any vendor: a compliance operator who has, say, phoned a bank to
confirm an account number, or read a physical passport, records what they
found through the exact same `trigger_verification` call and the exact same
registry lookup any future real vendor adapter (RxilAdapter, ...) will use —
there is no separate "manual verification" code path anywhere in the service
layer. This is the PRD's explicit "manual verification entry" MVP
requirement, and it proves the `VerificationAdapter` Protocol end-to-end
before any real vendor integration exists.

Where the manually-observed result comes from
-----------------------------------------------
`VerificationRequest.payload` carries it. There is no vendor response to
normalize here — the operator's own input *is* the outcome — so this
adapter's whole job is validating that `payload` and repackaging it as a
`VerificationOutcome`, never deciding anything on its own:

* ``status`` (required): one of `VerificationResultStatus`'s values.
* ``normalized_result`` (optional, default ``{}``): whatever structured
  detail the operator captured (e.g. ``{"account_holder_name": "..."}"``).
* ``provider_reference`` (optional): an operator-chosen reference, e.g. a
  ticket number for the manual check, so a later `get_verification_status`
  call can be told which record was meant (see below for why this adapter
  answers that with a capability error).
* ``risk_level`` (optional): one of `VerificationRiskLevel`'s values.
* ``valid_until`` (optional): a `datetime`, for checks that expire.
"""

from __future__ import annotations

from datetime import datetime

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
from app.modules.onboarding.exceptions import InvalidProviderPayloadError, ProviderCapabilityError
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum

#: The registry name and the `VerificationOutcome.provider` value this adapter
#: reports. Kept as one constant rather than two so the two can never drift
#: apart — the whole point of the "provider is never rewritten" acceptance
#: criterion is that what a caller asked for and what gets persisted agree.
PROVIDER_NAME = "manual"


class ManualEntryAdapter:
    """A `VerificationAdapter` backed by a human, not a vendor API call."""

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=PROVIDER_NAME,
            supported_verification_types=tuple(VerificationType),
            supported_entity_types=tuple(VerificationEntityType),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Repackage `request.payload` (the manually-observed result) as an
        outcome. Raises `InvalidProviderPayloadError` if `payload["status"]`
        is missing or not a valid `VerificationResultStatus` — the one thing
        this adapter cannot proceed without.
        """
        payload = request.payload

        raw_status = payload.get("status")
        if raw_status is None:
            raise InvalidProviderPayloadError(
                "manual verification entry requires a 'status' field in payload "
                f"(one of {[s.value for s in VerificationResultStatus]})",
                provider_name=PROVIDER_NAME,
            )
        try:
            status = (
                raw_status
                if isinstance(raw_status, VerificationResultStatus)
                else VerificationResultStatus(raw_status)
            )
        except ValueError as exc:
            raise InvalidProviderPayloadError(
                f"manual verification entry payload has an invalid status {raw_status!r}",
                provider_name=PROVIDER_NAME,
            ) from exc

        raw_risk_level = payload.get("risk_level")
        risk_level: VerificationRiskLevel | None = None
        if raw_risk_level is not None:
            try:
                risk_level = (
                    raw_risk_level
                    if isinstance(raw_risk_level, VerificationRiskLevel)
                    else VerificationRiskLevel(raw_risk_level)
                )
            except ValueError as exc:
                raise InvalidProviderPayloadError(
                    f"manual verification entry payload has an invalid risk_level {raw_risk_level!r}",
                    provider_name=PROVIDER_NAME,
                ) from exc

        valid_until = payload.get("valid_until")
        if valid_until is not None and not isinstance(valid_until, datetime):
            raise InvalidProviderPayloadError(
                "manual verification entry payload's valid_until must be a datetime",
                provider_name=PROVIDER_NAME,
            )

        return VerificationOutcome(
            provider=PROVIDER_NAME,
            provider_reference=payload.get("provider_reference"),
            status=status,
            normalized_result=dict(payload.get("normalized_result") or {}),
            risk_level=risk_level,
            valid_until=valid_until,
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Not applicable: a manual entry resolves synchronously in `verify()`.

        Mirrors `kyb.infrastructure.adapters.trulioo.adapter.TruliooAdapter.
        get_verification_status`'s precedent for a synchronous vendor — except
        `VerificationResultStatus` (unlike `NormalisedResult`) has no
        `NOT_SUPPORTED` member to return gracefully (the PRD's field list is
        fixed to PENDING/PASSED/FAILED/REVIEW), so this raises
        `ProviderCapabilityError` instead: the same 422 "adapter does not
        support this capability" the registry itself raises for a declared-
        but-unimplemented capability, rather than returning a status value
        that would misrepresent what happened.
        """
        raise ProviderCapabilityError(PROVIDER_NAME, "get_verification_status")

    def get_vendor_health(self) -> VendorHealthStatus:
        """Always healthy: this adapter has no external dependency to fail."""
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=0)


register_adapter(PROVIDER_NAME, ManualEntryAdapter)

__all__ = ["PROVIDER_NAME", "ManualEntryAdapter"]
