"""`StubRxilAdapter` — proves the "one payload produces many
`VerificationResult` rows" batch shape (EXP-2 plan point 6 / Exporter CRM
Piece 3) end-to-end, **without assuming anything about RXIL's real
integration mechanism**.

This is explicitly a stub to de-risk the architecture, not a real vendor
integration. As of this writing, how RXIL actually hands over a batch of
checks — a synchronous API call, a file drop, an event stream — is genuinely
unknown; nothing below guesses at one. `verify_batch` accepts plain
`VerificationRequest`s whose `payload` already carries the check's outcome
(`status`, optionally `normalized_result`/`risk_level`/`valid_until`/
`provider_reference`) — the same "the input already is the answer"
convention `ManualEntryAdapter` established for exactly the same underlying
reason: RXIL, like a manual operator, is *reporting* checks it already ran
upstream (per the confirmed plan: RXIL-originated exporters have already had
KYC/KYB/AML/CFT/invoice-duplication/vessel-tracking/... run against them by
RXIL itself — this platform ingests those results, it never recomputes them),
not asking this stub to compute anything from raw inputs. No RXIL field name,
endpoint shape, or file format appears anywhere in this file.

When RXIL's real technical integration spec is confirmed, only this one file
(and its registration below) is expected to change — `RxilAdapter` will
implement the exact same `VerificationAdapter` +
`BatchVerificationAdapter` Protocols this stub already proves work, wired to
whatever RXIL's real mechanism turns out to be. Nothing in
`VerificationService`, the registry, or `VerificationResult` needs to change
for that swap.
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

#: What this stub reports as `VerificationOutcome.provider` — persisted
#: verbatim onto `VerificationResult.provider` by `VerificationService`,
#: never rewritten (the same guarantee EXP-2 already proved for the
#: single-result case; `test_stub_rxil_adapter.py`'s
#: `test_batch_provider_is_never_rewritten` extends it to the batch case).
PROVIDER_NAME = "RXIL"

#: The registry key this stub is looked up by. Deliberately lower-case and
#: distinct from `PROVIDER_NAME`: a registry key is a caller-facing routing
#: string ("which adapter do I want"), not the provider's own self-reported
#: identity — `tests/integration/test_exp2_verification_service.py`'s
#: `_FakeRxilAdapter` already established that the two need not (and for a
#: real vendor, generally won't) coincide.
REGISTRY_KEY = "rxil"


class StubRxilAdapter:
    """A stub `VerificationAdapter` + `BatchVerificationAdapter` for RXIL.

    Implements both Protocols (see `workflow_dependencies.
    BatchVerificationAdapter`'s docstring for why batch is a second,
    independent Protocol rather than a method on `VerificationAdapter`
    itself): `verify` and `verify_batch` share one private helper
    (`_outcome_from_payload`) so the single-check and batch paths can never
    diverge in how they interpret a payload.
    """

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=PROVIDER_NAME,
            supported_verification_types=tuple(VerificationType),
            supported_entity_types=tuple(VerificationEntityType),
            # Unknown until RXIL's real mechanism is confirmed; ASYNCHRONOUS
            # is the safer default (a caller that assumes SYNCHRONOUS and is
            # wrong gets a silently-stale result, a caller that assumes
            # ASYNCHRONOUS and is wrong just polls once and gets its answer
            # immediately).
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Single-check path — proves this stub is a normal
        `VerificationAdapter` too, not solely a batch-only special case."""
        return _outcome_from_payload(request)

    def verify_batch(self, requests: list[VerificationRequest]) -> list[VerificationOutcome]:
        """The batch capability this stub exists to prove: one payload (a
        list of checks, each possibly a different `verification_type`/
        `entity_type`) becomes one `VerificationOutcome` per check, in order.
        """
        return [_outcome_from_payload(item) for item in requests]

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Not applicable: every check this stub reports resolves
        synchronously in `verify`/`verify_batch`, mirroring
        `ManualEntryAdapter.get_verification_status`'s precedent exactly, for
        the same reason (see that method's docstring)."""
        raise ProviderCapabilityError(PROVIDER_NAME, "get_verification_status")

    def get_vendor_health(self) -> VendorHealthStatus:
        """Always healthy: this stub has no external dependency to fail."""
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=0)


def _outcome_from_payload(request: VerificationRequest) -> VerificationOutcome:
    """Repackage one `VerificationRequest.payload` (an already-known check
    result) as a `VerificationOutcome`, tagged `provider=PROVIDER_NAME`.
    Shared by `verify` and `verify_batch` — see class docstring.

    Validates exactly what `ManualEntryAdapter.verify` validates, for the
    same reason: the caller's own input *is* the outcome, so the only thing
    this stub can get wrong is failing to notice a malformed one.
    """
    payload = request.payload

    raw_status = payload.get("status")
    if raw_status is None:
        raise InvalidProviderPayloadError(
            "RXIL batch check requires a 'status' field in payload "
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
            f"RXIL batch check payload has an invalid status {raw_status!r}",
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
                f"RXIL batch check payload has an invalid risk_level {raw_risk_level!r}",
                provider_name=PROVIDER_NAME,
            ) from exc

    valid_until = payload.get("valid_until")
    if valid_until is not None and not isinstance(valid_until, datetime):
        raise InvalidProviderPayloadError(
            "RXIL batch check payload's valid_until must be a datetime",
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


register_adapter(REGISTRY_KEY, StubRxilAdapter)

__all__ = ["PROVIDER_NAME", "REGISTRY_KEY", "StubRxilAdapter"]
