"""
Structured provider failures.

Every way an external KYC/KYB/screening provider can fail is represented here as
exactly one :class:`ProviderFailureReason`. The backlog enumerates the five reasons
and requires that a failed provider call record a *structured* reason rather than a
free-text message, so that:

* ``provider_run`` can persist the reason as a column, and
* ``normalized_result.overall_status`` can be derived from it without manual DB
  patching.

A provider failure is **never** a case decision. Raising any exception from this
module records evidence that a provider call failed; it does not approve, reject,
or otherwise move a case. Only the decision layer moves a case to a terminal state.

The registry-resolution errors (:class:`ProviderNotRegisteredError`,
:class:`ProviderNotEnabledError`, :class:`ProviderCapabilityError`) are a different
class of failure: they are raised *before* any external call is attempted, and so
before any ``provider_run`` row exists. They surface as 422 domain errors, matching
the "missing route returns a structured error before provider execution" rule.
"""
from __future__ import annotations

import enum

from app.shared.exceptions import AnerBaseException


class ProviderFailureReason(str, enum.Enum):
    """
    The complete, closed set of structured provider failure reasons.

    Persisted on ``provider_run`` once that table exists. Do not add a member
    without a corresponding migration and a normalization rule for it.
    """

    TIMEOUT = "TIMEOUT"
    """The provider did not respond within the adapter's bounded timeout."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    """The provider returned 5xx, refused the connection, or is circuit-broken."""

    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    """The provider rejected our request, or returned a response we cannot parse."""

    UNSUPPORTED_COUNTRY = "UNSUPPORTED_COUNTRY"
    """The provider does not operate in the subject's country for this check type."""

    NORMALIZATION_ERROR = "NORMALIZATION_ERROR"
    """The provider responded, but the response could not be mapped to a NormalizedResult."""


#: Failure reasons for which a bounded retry (tenacity) is worthwhile.
#: The others are deterministic: retrying an ``INVALID_PAYLOAD`` produces another
#: ``INVALID_PAYLOAD``.
RETRYABLE_FAILURE_REASONS: frozenset[ProviderFailureReason] = frozenset(
    {ProviderFailureReason.TIMEOUT, ProviderFailureReason.PROVIDER_UNAVAILABLE}
)


class ProviderError(AnerBaseException):
    """
    Base class for a failure that occurred while talking to a provider.

    Carries a :class:`ProviderFailureReason` so the caller never has to parse a
    message string. Defaults to HTTP 502 because the failure originated upstream,
    not in the caller's request.

    Args:
        detail: Human-readable description. **Must not contain PII, raw provider
            payloads, document URLs, or biometric evidence.**
        provider_name: The provider that failed, e.g. ``"mock"``.
        failure_reason: The structured reason. Subclasses set this.
        status_code: HTTP status to surface if this reaches an API boundary.
    """

    failure_reason: ProviderFailureReason = ProviderFailureReason.PROVIDER_UNAVAILABLE

    def __init__(
        self,
        detail: str,
        *,
        provider_name: str,
        failure_reason: ProviderFailureReason | None = None,
        status_code: int = 502,
    ) -> None:
        self.provider_name = provider_name
        if failure_reason is not None:
            self.failure_reason = failure_reason
        super().__init__(
            detail=detail,
            error_code=f"PROVIDER_{self.failure_reason.value}",
            status_code=status_code,
        )

    @property
    def retryable(self) -> bool:
        """True when a bounded retry with backoff could plausibly succeed."""
        return self.failure_reason in RETRYABLE_FAILURE_REASONS


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the adapter's timeout."""

    failure_reason = ProviderFailureReason.TIMEOUT


class ProviderUnavailableError(ProviderError):
    """The provider is unreachable or returned a server-side error."""

    failure_reason = ProviderFailureReason.PROVIDER_UNAVAILABLE


class InvalidProviderPayloadError(ProviderError):
    """The provider rejected our request, or its response failed validation."""

    failure_reason = ProviderFailureReason.INVALID_PAYLOAD

    def __init__(self, detail: str, *, provider_name: str) -> None:
        super().__init__(detail, provider_name=provider_name, status_code=422)


class UnsupportedCountryError(ProviderError):
    """The provider does not cover the subject's country for the requested check."""

    failure_reason = ProviderFailureReason.UNSUPPORTED_COUNTRY

    def __init__(self, detail: str, *, provider_name: str) -> None:
        super().__init__(detail, provider_name=provider_name, status_code=422)


class ProviderNormalizationError(ProviderError):
    """The provider responded, but the response could not be normalized."""

    failure_reason = ProviderFailureReason.NORMALIZATION_ERROR

    def __init__(self, detail: str, *, provider_name: str) -> None:
        super().__init__(detail, provider_name=provider_name, status_code=422)


# ── Resolution errors ────────────────────────────────────────────────────────
# Raised before any external call, therefore before any provider_run exists.


class ProviderResolutionError(AnerBaseException):
    """Base class for a provider that could not be resolved from configuration."""

    def __init__(self, detail: str, *, error_code: str) -> None:
        super().__init__(detail=detail, error_code=error_code, status_code=422)


class ProviderNotRegisteredError(ProviderResolutionError):
    """No adapter factory is registered under the requested provider name."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(
            detail=f"No provider adapter is registered under the name '{provider_name}'",
            error_code="PROVIDER_NOT_REGISTERED",
        )


class ProviderNotEnabledError(ProviderResolutionError):
    """The adapter exists but is not listed in ONBOARDING_ENABLED_PROVIDERS."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(
            detail=f"Provider '{provider_name}' is not enabled in this environment",
            error_code="PROVIDER_NOT_ENABLED",
        )


class ProviderCapabilityError(ProviderResolutionError):
    """The resolved adapter does not declare the capability the caller needs."""

    def __init__(self, provider_name: str, capability: str) -> None:
        self.provider_name = provider_name
        self.capability = capability
        super().__init__(
            detail=f"Provider '{provider_name}' does not support the '{capability}' capability",
            error_code="PROVIDER_CAPABILITY_UNSUPPORTED",
        )


class DocumentRequirementsConfigurationError(AnerBaseException):
    """Raised when document requirements configuration is missing or invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail=detail,
            error_code="DOCUMENT_REQUIREMENTS_CONFIG_ERROR",
            status_code=500,
        )


# ── ANER-4.1-S5T2: risk rating configuration ────────────────────────────────


class RiskRatingConfigurationError(AnerBaseException):
    """Raised when the risk rating GitOps configuration is missing or invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail=detail,
            error_code="RISK_RATING_CONFIG_ERROR",
            status_code=500,
        )


# ── ANER-4.1-S5T1 / S5T2: onboarding_request state transitions ─────────────


class IllegalOnboardingTransitionError(AnerBaseException):
    """An onboarding_request write was attempted from a status that forbids it.

    Raised by the S5T1 screening-result transition and the S5T2 risk-rating
    assignment when ``onboarding_request.status`` is not the single precondition
    status each expects (``SCREENING_IN_PROGRESS`` and ``RISK_RATING_IN_PROGRESS``
    respectively). This is deliberately narrower than a full state machine: the
    Temporal workflow that owns the complete state machine is Story S3, which is
    out of scope here. This guard only protects the two specific transitions this
    story implements from being applied twice or out of order.
    """

    def __init__(self, *, from_status: str, expected_status: str, action: str) -> None:
        super().__init__(
            detail=(
                f"Cannot {action}: onboarding_request status is {from_status!r}, "
                f"expected {expected_status!r}."
            ),
            error_code="ILLEGAL_ONBOARDING_TRANSITION",
            status_code=409,
        )
        self.from_status = from_status
        self.expected_status = expected_status


class OnboardingFieldAlreadySetError(AnerBaseException):
    """A write-once ``onboarding_request`` column has already been recorded.

    ``screening_result``, ``ubo_mapping`` and ``risk_rating_factors`` are protected by
    the ``trg_onboarding_request_field_immutability`` database trigger (migration
    ``onboarding_0002_orchestration_schema``), which rejects any ``UPDATE`` once
    the column holds a non-null value. Both S5T1's and S5T2's services translate
    that trigger's raw driver error into this domain exception instead of letting
    a bare ``DBAPIError`` escape. In normal operation the status precondition
    (:class:`IllegalOnboardingTransitionError`) is what stops a second call; this
    exception is the defense-in-depth path for the trigger firing directly (e.g.
    a status that was reset out-of-band while the field remained set).
    """

    def __init__(self, *, field: str, onboarding_id: object) -> None:
        super().__init__(
            detail=(
                f"onboarding_request.{field} is immutable once set "
                f"(onboarding_id={onboarding_id})."
            ),
            error_code="ONBOARDING_FIELD_ALREADY_SET",
            status_code=409,
        )
        self.field = field


# ── AL-672: OnboardingTransitionService / Temporal workflow lifecycle ──────────
#
# These are distinct from IllegalOnboardingTransitionError above: that one is
# raised by S5T1/S5T2's own direct-write precondition guards (a narrow status
# precondition per method); these are raised by OnboardingTransitionService,
# the canonical, table-driven transition gateway AL-672 built for the Temporal
# workflow. Both exist because the two call paths were built independently
# (see onboarding_request_transitions.py's module docstring for the
# reconciliation note on the two transition tables' real differences).
# ── Onboarding request lifecycle ─────────────────────────────────────────────


class OnboardingDependencyUnavailableError(AnerBaseException):
    """No implementation of an onboarding workflow dependency is configured.

    Deterministic — retrying cannot make an implementation appear — so the workflow
    treats it as non-retryable.
    """

    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(
            detail=f"No implementation is configured for onboarding dependency '{capability}'",
            error_code="ONBOARDING_DEPENDENCY_UNAVAILABLE",
            status_code=503,
        )


class OnboardingRequestNotFoundError(AnerBaseException):
    """The onboarding request a transition names does not exist."""

    def __init__(self, onboarding_request_id: str) -> None:
        self.onboarding_request_id = onboarding_request_id
        super().__init__(
            detail=f"Onboarding request {onboarding_request_id} not found",
            error_code="ONBOARDING_REQUEST_NOT_FOUND",
            status_code=404,
        )


class OnboardingTransitionNotPermittedError(AnerBaseException):
    """The lifecycle does not connect the two statuses, or the transition's details
    are not valid for it. Raised before anything is written."""

    def __init__(self, from_status: str, to_status: str, reason: str | None = None) -> None:
        self.from_status = from_status
        self.to_status = to_status
        detail = f"Onboarding request cannot move from {from_status} to {to_status}"
        super().__init__(
            detail=f"{detail}: {reason}" if reason else detail,
            error_code="ONBOARDING_TRANSITION_NOT_PERMITTED",
            status_code=409,
            extensions={"from_status": from_status, "to_status": to_status},
        )


# ── EXP-2: VerificationResult ────────────────────────────────────────────────


class VerificationResultNotFoundError(AnerBaseException):
    """No `VerificationResult` exists with the given id (or provider_reference)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, error_code="VERIFICATION_RESULT_NOT_FOUND", status_code=404)


class VerificationResultAlreadyReviewedError(AnerBaseException):
    """`reviewed_by` / `review_status` on a `VerificationResult` are already set.

    Mirrors :class:`OnboardingFieldAlreadySetError`'s role for
    `onboarding_request`'s write-once columns, for the same reason: EXP-2's
    ticket leans toward `reviewed_by`/`review_status` being immutable once
    set, for audit consistency with every other "who decided this" field in
    this codebase (`ComplianceCase.resolved_by`, the columns
    `OnboardingFieldAlreadySetError` itself guards). `VerificationService.
    record_review` raises this *before* attempting the write, as a clean
    domain exception; the DB trigger
    (`trg_verification_result_field_immutability`, migration
    `onboarding_0006_verif_result`) is the defense-in-depth path for a
    write that reaches Postgres some other way.

    Flag: unlike `resolved_by`, a real compliance review workflow may
    legitimately need to *correct* a review (escalate after acceptance, or
    reverse a mistaken rejection) — the PRD does not describe one yet. If that
    turns out to be a real requirement, this becomes an explicit override path
    (a new reviewed-by-a-more-senior-actor exception, or a supersession row)
    rather than lifting the write-once rule outright.
    """

    def __init__(self, *, verification_result_id: object) -> None:
        super().__init__(
            detail=(
                "VerificationResult.reviewed_by/review_status are immutable once set "
                f"(verification_result_id={verification_result_id})."
            ),
            error_code="VERIFICATION_RESULT_ALREADY_REVIEWED",
            status_code=409,
        )
        self.verification_result_id = verification_result_id


class OnboardingStatusConflictError(AnerBaseException):
    """The request is not in the status the transition expected, and the transition
    has not already been applied. Nothing is written."""

    def __init__(
        self,
        onboarding_request_id: str,
        *,
        expected_status: str,
        current_status: str,
        to_status: str,
    ) -> None:
        self.onboarding_request_id = onboarding_request_id
        self.expected_status = expected_status
        self.current_status = current_status
        self.to_status = to_status
        super().__init__(
            detail=(
                f"Onboarding request {onboarding_request_id} is {current_status}, "
                f"expected {expected_status} for a move to {to_status}"
            ),
            error_code="ONBOARDING_STATUS_CONFLICT",
            status_code=409,
            extensions={
                "expected_status": expected_status,
                "current_status": current_status,
                "to_status": to_status,
            },
        )


# ── EXP-1: Exporter CRM (ExporterProfile / ExporterContact / ExporterActivity) ─


class ExporterProfileNotFoundError(AnerBaseException):
    """No ``exporter_profile`` row exists for the given ``customer_id``."""

    def __init__(self, customer_id: object) -> None:
        self.customer_id = customer_id
        super().__init__(
            detail=f"Exporter profile for customer {customer_id} not found",
            error_code="EXPORTER_PROFILE_NOT_FOUND",
            status_code=404,
        )


class ExporterProfileAlreadyExistsError(AnerBaseException):
    """``create_or_get_profile`` was called for a ``customer_id`` that already
    has a profile, without an idempotency key that would make the call a
    replay. Distinct from the idempotent-replay path (which returns the
    existing profile rather than raising): this is the true race/duplicate
    case — the DB's ``uq_exporter_profile_customer_id`` constraint fired.
    """

    def __init__(self, customer_id: object) -> None:
        self.customer_id = customer_id
        super().__init__(
            detail=f"Exporter profile for customer {customer_id} already exists",
            error_code="EXPORTER_PROFILE_ALREADY_EXISTS",
            status_code=409,
        )


class ExporterSourceImmutableError(AnerBaseException):
    """``ExporterProfile.source`` was named in an ``update_profile`` call.

    ``source`` is an audit-relevant fact about how the exporter relationship
    began (same reasoning as ``ComplianceCase.resolved_by``), guarded both
    here — so the caller gets a clean domain exception, not a raw driver
    error — and by ``trg_exporter_profile_source_immutability`` at the
    database level (migration ``onboarding_0005_exporter_crm``), as defense
    in depth for any write path that bypasses this service.
    """

    def __init__(self, customer_id: object) -> None:
        self.customer_id = customer_id
        super().__init__(
            detail=(
                f"exporter_profile.source is immutable once set "
                f"(customer_id={customer_id})"
            ),
            error_code="EXPORTER_SOURCE_IMMUTABLE",
            status_code=409,
        )


class InvalidExporterLifecycleTransitionError(AnerBaseException):
    """``(from_status, to_status)`` is not in
    ``exporter_profile_service.PERMITTED_LIFECYCLE_TRANSITIONS`` — e.g.
    ``LEAD`` -> ``ACTIVE`` directly, skipping every intermediate stage.
    """

    def __init__(self, customer_id: object, from_status: object, to_status: object) -> None:
        self.customer_id = customer_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            detail=(
                f"Exporter {customer_id} cannot transition from {from_status!r} to "
                f"{to_status!r}: not a permitted lifecycle_status transition"
            ),
            error_code="INVALID_EXPORTER_LIFECYCLE_TRANSITION",
            status_code=409,
            extensions={"from_status": str(from_status), "to_status": str(to_status)},
        )
