"""
Credential-free mock adapters.

Decision D9 (``docs/project-memory.md`` §10.2) requires a real mock rather than
testing through the Sumsub setup: the acceptance criterion is that the mock
"can run through the provider_run lifecycle **without real vendor credentials**",
and CI must stay credential-free.

Two adapters, not one, because the point of the capability split is that a screening
provider does not implement ``create_subject`` or ``submit_profile``.
:class:`MockScreeningProviderAdapter` demonstrates that a provider missing those two
methods is still a first-class citizen of the contract — which is the shape
escalation E1 proposes for ComplyAdvantage.

These are test doubles. They contain no vendor business logic, make no network
calls, and are deterministic: the same input always produces the same output.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog

from app.modules.onboarding.domain.dto import (
    CheckOutcome,
    CheckRequest,
    CheckRun,
    EvidenceRef,
    FailureDetails,
    NormalizedResult,
    OverallStatus,
    ProfileInput,
    ProfileRef,
    ProviderCapability,
    ProviderCheckState,
    ProviderStatus,
    RecommendedAction,
    RiskLevel,
    SubjectInput,
    SubjectRef,
    WebhookEvent,
    WebhookRequest,
)
from app.modules.onboarding.exceptions import (
    RETRYABLE_FAILURE_REASONS,
    InvalidProviderPayloadError,
    ProviderFailureReason,
    ProviderNormalizationError,
)

logger = structlog.get_logger(__name__)

#: The mock's fake webhook signature. A request without it parses with
#: ``signature_verified=False``, so tests can exercise the reject-and-audit path.
_VALID_MOCK_SIGNATURE = "valid-mock-signature"

_RISK_BY_NAME: Mapping[str, RiskLevel] = {r.value: r for r in RiskLevel}

#: How a normalized risk band maps onto an advisory action. Mirrors the mapping
#: rules the backlog states, so the mock's output is shaped like a real provider's.
_ACTION_FOR_RISK: Mapping[RiskLevel, RecommendedAction] = {
    RiskLevel.LOW: RecommendedAction.APPROVE,
    RiskLevel.MEDIUM: RecommendedAction.MANUAL_REVIEW,
    RiskLevel.HIGH: RecommendedAction.ESCALATE,
    RiskLevel.CRITICAL: RecommendedAction.ESCALATE,
}

_STATUS_FOR_RISK: Mapping[RiskLevel, OverallStatus] = {
    RiskLevel.LOW: OverallStatus.CLEAR,
    RiskLevel.MEDIUM: OverallStatus.MANUAL_REVIEW,
    RiskLevel.HIGH: OverallStatus.MANUAL_REVIEW,
    RiskLevel.CRITICAL: OverallStatus.MANUAL_REVIEW,
}


def _evidence_ref(payload: Mapping[str, Any], kind: str) -> EvidenceRef:
    """
    Build a pointer to where the raw payload *would* live in object storage.

    Object storage will provision MinIO/GCS and persist the bytes; until then the mock
    computes the same digest and URI shape so callers can be written against the
    final contract today. The raw payload is never returned.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    return EvidenceRef(
        uri=f"evidence://mock/{kind}/{digest}",
        kind=kind,
        sha256=digest,
        captured_at=datetime.now(tz=UTC),
    )


def _parse_webhook(provider_name: str, request: WebhookRequest) -> WebhookEvent:
    """Shared webhook parsing. Both mock adapters speak the same fake wire format."""
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidProviderPayloadError(
            "Webhook body is not valid JSON", provider_name=provider_name
        ) from exc

    if not isinstance(payload, dict):
        raise InvalidProviderPayloadError(
            "Webhook body is not a JSON object", provider_name=provider_name
        )

    raw_state = payload.get("state", ProviderCheckState.PENDING.value)
    try:
        state = ProviderCheckState(raw_state)
    except ValueError as exc:
        raise InvalidProviderPayloadError(
            f"Unrecognized check state '{raw_state}'", provider_name=provider_name
        ) from exc

    # Signature is verified over the exact bytes received, never over re-serialized
    # JSON — that is why WebhookRequest carries `body` as bytes.
    signature_verified = request.headers.get("x-mock-signature") == _VALID_MOCK_SIGNATURE

    return WebhookEvent(
        provider_name=provider_name,
        event_type=str(payload.get("event_type", "check.updated")),
        provider_reference=payload.get("reference"),
        provider_subject_id=payload.get("subject_id"),
        state=state,
        occurred_at=datetime.now(tz=UTC),
        signature_verified=signature_verified,
    )


def _normalize(
    provider_name: str,
    raw_payload: Mapping[str, Any],
    provider_run_id: uuid.UUID | None,
) -> NormalizedResult:
    """
    Shared normalization. Both mocks read a fake payload of the shape::

        {"state": "COMPLETED", "risk": "LOW", "checks": {"IDENTITY": "LOW"}}

    A ``FAILED`` state normalizes to ``overall_status=FAILED`` with structured
    failure details — never to a rejection. A provider cannot reject a case.
    """
    raw_state = raw_payload.get("state")
    try:
        state = ProviderCheckState(raw_state)
    except ValueError as exc:
        raise ProviderNormalizationError(
            f"Unrecognized check state '{raw_state}'", provider_name=provider_name
        ) from exc

    evidence = (_evidence_ref(raw_payload, kind="status_response"),)

    if state is ProviderCheckState.FAILED:
        raw_reason = raw_payload.get("failure_reason", ProviderFailureReason.PROVIDER_UNAVAILABLE.value)
        try:
            reason = ProviderFailureReason(raw_reason)
        except ValueError as exc:
            raise ProviderNormalizationError(
                f"Unrecognized failure reason '{raw_reason}'", provider_name=provider_name
            ) from exc
        return NormalizedResult(
            provider_name=provider_name,
            provider_run_id=provider_run_id,
            overall_status=OverallStatus.FAILED,
            risk_level=RiskLevel.MEDIUM,
            recommended_action=RecommendedAction.MANUAL_REVIEW,
            evidence_refs=evidence,
            failure_details=FailureDetails(
                reason=reason,
                message=f"Mock provider reported {reason.value}",
                retryable=reason in RETRYABLE_FAILURE_REASONS,
            ),
        )

    raw_risk = str(raw_payload.get("risk", RiskLevel.LOW.value))
    risk = _RISK_BY_NAME.get(raw_risk)
    if risk is None:
        raise ProviderNormalizationError(
            f"Unrecognized risk level '{raw_risk}'", provider_name=provider_name
        )

    # `checks` keys are passed through as bare strings, so a check type this
    # platform has never seen round-trips without a migration.
    outcomes = tuple(
        CheckOutcome(
            check_type=str(check_type),
            status=_STATUS_FOR_RISK[_RISK_BY_NAME.get(str(band), RiskLevel.LOW)],
            risk_level=_RISK_BY_NAME.get(str(band), RiskLevel.LOW),
        )
        for check_type, band in (raw_payload.get("checks") or {}).items()
    )

    return NormalizedResult(
        provider_name=provider_name,
        provider_run_id=provider_run_id,
        overall_status=_STATUS_FOR_RISK[risk],
        risk_level=risk,
        recommended_action=_ACTION_FOR_RISK[risk],
        check_outcomes=outcomes,
        evidence_refs=evidence,
    )


class MockIdentityProviderAdapter:
    """
    Deterministic stand-in for an identity-verification vendor.

    Satisfies :class:`~...contract.IdentityVerificationProvider`. Registered under
    the name ``"mock"`` and enabled by default, so the test suite and local
    development run with no credentials and no network.
    """

    name: ClassVar[str] = "mock"
    capabilities: ClassVar[frozenset[ProviderCapability]] = frozenset(
        {ProviderCapability.IDENTITY_VERIFICATION}
    )

    async def create_subject(self, subject: SubjectInput) -> SubjectRef:
        """Derive a stable subject id from the external id, so retries are idempotent."""
        logger.info(
            "mock_provider_create_subject",
            provider=self.name,
            case_id=str(subject.case_id),
            subject_type=subject.subject_type.value,
        )
        return SubjectRef(
            provider_name=self.name,
            provider_subject_id=f"mock-subject-{subject.external_subject_id}",
            external_subject_id=subject.external_subject_id,
        )

    async def submit_profile(self, profile: ProfileInput) -> ProfileRef:
        """Accept the profile. The PII in ``profile.attributes`` is never logged."""
        logger.info(
            "mock_provider_submit_profile",
            provider=self.name,
            provider_subject_id=profile.subject_ref.provider_subject_id,
            attribute_count=len(profile.attributes),
        )
        return ProfileRef(
            provider_name=self.name,
            provider_subject_id=profile.subject_ref.provider_subject_id,
            accepted_at=datetime.now(tz=UTC),
        )

    async def start_checks(self, request: CheckRequest) -> CheckRun:
        """Accept the checks the route resolver required. Never chooses them itself."""
        reference = f"mock-run-{request.subject_ref.provider_subject_id}"
        logger.info(
            "mock_provider_start_checks",
            provider=self.name,
            case_id=str(request.case_id),
            provider_reference=reference,
            check_types=[c.value for c in request.check_types],
        )
        return CheckRun(
            provider_name=self.name,
            provider_reference=reference,
            check_types=request.check_types,
            state=ProviderCheckState.IN_PROGRESS,
            started_at=datetime.now(tz=UTC),
        )

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        """Always reports COMPLETED. Fault injection belongs in the test, not the mock."""
        return ProviderStatus(
            provider_name=self.name,
            provider_reference=provider_reference,
            state=ProviderCheckState.COMPLETED,
            checked_at=datetime.now(tz=UTC),
        )

    def parse_webhook(self, request: WebhookRequest) -> WebhookEvent:
        return _parse_webhook(self.name, request)

    def normalize_result(
        self,
        *,
        raw_payload: Mapping[str, Any],
        provider_run_id: uuid.UUID | None = None,
    ) -> NormalizedResult:
        return _normalize(self.name, raw_payload, provider_run_id)


class MockScreeningProviderAdapter:
    """
    Deterministic stand-in for a watchlist-screening vendor.

    Satisfies :class:`~...contract.ScreeningProvider`. Note what is absent:
    ``create_subject`` and ``submit_profile``. Screening takes the subject's
    attributes as arguments to the check itself, so there is nothing to open and
    nothing to submit. This adapter exists to prove the contract admits such a
    provider without forcing it to no-op two methods.

    It does **not** produce screening hits — ``screening_hit`` is separate work and
    belongs to Tejasvi. This adapter only proves the shape of the contract.
    """

    name: ClassVar[str] = "mock_screening"
    capabilities: ClassVar[frozenset[ProviderCapability]] = frozenset({ProviderCapability.SCREENING})

    async def start_checks(self, request: CheckRequest) -> CheckRun:
        reference = f"mock-screening-{request.subject_ref.provider_subject_id}"
        logger.info(
            "mock_screening_start_checks",
            provider=self.name,
            case_id=str(request.case_id),
            provider_reference=reference,
            check_types=[c.value for c in request.check_types],
        )
        return CheckRun(
            provider_name=self.name,
            provider_reference=reference,
            check_types=request.check_types,
            state=ProviderCheckState.IN_PROGRESS,
            started_at=datetime.now(tz=UTC),
        )

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self.name,
            provider_reference=provider_reference,
            state=ProviderCheckState.COMPLETED,
            checked_at=datetime.now(tz=UTC),
        )

    def parse_webhook(self, request: WebhookRequest) -> WebhookEvent:
        return _parse_webhook(self.name, request)

    def normalize_result(
        self,
        *,
        raw_payload: Mapping[str, Any],
        provider_run_id: uuid.UUID | None = None,
    ) -> NormalizedResult:
        return _normalize(self.name, raw_payload, provider_run_id)
