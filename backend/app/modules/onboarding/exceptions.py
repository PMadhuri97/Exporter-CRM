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


class VerificationReviewStaleError(AnerBaseException):
    """A review did not name the result's **current** review as the one it supersedes.

    Replaces the one-review-only rule (Dev4B 4B-2, 4b-task.md §5.1): a verdict now
    changes by adding a review that supersedes the current one, never by editing
    one. The caller must name the chain head it saw — like a compare-and-set — so a
    reviewer who acted on a stale view gets 409 instead of silently overruling a
    review they never saw. Raised for: a first review that names a
    ``supersedes_review_id``; a later review that names none, or names a review that
    is not the head; and a concurrent review that lost the race
    (``uq_verification_review_supersedes`` / ``uq_verification_review_first``).
    ``current_review_id`` is the head to retry against (``None``: not yet reviewed).
    """

    def __init__(
        self, *, verification_result_id: object, current_review_id: object | None
    ) -> None:
        super().__init__(
            detail=(
                "A review must supersede the result's current review "
                f"(verification_result_id={verification_result_id}, "
                f"current_review_id={current_review_id}). Reload and try again."
            ),
            error_code="VERIFICATION_REVIEW_STALE",
            status_code=409,
            extensions={
                "current_review_id": (
                    str(current_review_id) if current_review_id is not None else None
                )
            },
        )
        self.verification_result_id = verification_result_id
        self.current_review_id = current_review_id


class VerificationResultNotReviewableError(AnerBaseException):
    """The `VerificationResult` is still `PENDING`: no finding exists yet to
    accept, reject or escalate.

    A recorded review is permanent (reviews are only ever superseded, never
    removed), so reviewing a check that has not produced a result would put a
    decision about nothing on the record — and placeholder rows created without
    a provider stay `PENDING` forever. The UI hides the review controls for
    these rows; this is the server-side rule, so an API client cannot do it
    either. 422 (4b-task.md §5.1): the request is well-formed but the result is
    not in a reviewable state.
    """

    def __init__(self, *, verification_result_id: object) -> None:
        super().__init__(
            detail=(
                "VerificationResult is still PENDING and cannot be reviewed until it "
                f"resolves (verification_result_id={verification_result_id})."
            ),
            error_code="VERIFICATION_RESULT_NOT_REVIEWABLE",
            status_code=422,
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


class MachineTransitionSourceNotPermittedError(AnerBaseException):
    """A machine attribution (``SYSTEM`` / ``PROVIDER_CALLBACK``) on a case
    transition that did not come through the internal path.

    ``TransitionSource`` answers "what caused this move"; ``ActorType`` and
    ``actor_id`` answer "who acted". A caller that may choose the first can
    make its own decision look like the platform's, which is why
    ``CaseTransitionRequest`` refuses these two values outright (422 at the
    boundary) and why ``CaseService.transition`` refuses them again unless the
    caller explicitly passed ``allow_machine_source=True`` — a keyword no HTTP
    route supplies.

    Two independent defences on purpose, matching this module's existing
    pattern (see ``get_adapter``'s registry check *and* its module allowlist):
    the schema stops it at the edge, and the service stops it even if a future
    route forgets to use that schema.
    """

    def __init__(self, source: object) -> None:
        self.source = source
        super().__init__(
            detail=(
                f"Transition source {source!r} attributes the move to the platform "
                f"itself and cannot be chosen by a caller; use USER_ACTION or "
                f"ADMIN_OVERRIDE"
            ),
            error_code="MACHINE_TRANSITION_SOURCE_NOT_PERMITTED",
            status_code=422,
            extensions={"source": str(source)},
        )


class IdentifierSearchNotPermittedError(AnerBaseException):
    """An exact tax-identifier search filter used by a role that may not see
    raw identifiers.

    Masking the response body is not enough on its own. ``GET /exporters?pan=``
    matches exactly, so whether a row comes back answers "does a company with
    this PAN exist, and which one" no matter how the body is rendered — an
    existence oracle over the most sensitive column in the CRM. DEVELOPER is
    read-only and never permitted to reveal an identifier
    (``can_reveal_identifiers``), so it must not be able to ask the question
    either.

    403 naming the parameter, rather than a silently empty result: an empty
    result is still an answer ("no such company"), and it would send anyone
    debugging a search looking for missing data.
    """

    def __init__(self, *, role: str, parameters: list[str]) -> None:
        self.role = role
        self.parameters = parameters
        named = ", ".join(parameters)
        super().__init__(
            detail=(
                f"Role {role} may not search by exact tax identifier "
                f"({named}): an exact match reveals which company holds it. "
                f"Search by legal_name instead."
            ),
            error_code="FORBIDDEN",
            status_code=403,
            extensions={"role": role, "parameters": parameters},
        )


class DuplicatePanError(AnerBaseException):
    """A PAN already held by another company (architecture decision 4: a
    duplicate PAN is refused, never merged). Names the company that holds it,
    so the person entering the duplicate can open that one instead. The PAN
    itself is not repeated: the caller sent it, and the response may be read
    by roles that see it masked."""

    def __init__(self, existing_customer_id: object) -> None:
        self.existing_customer_id = existing_customer_id
        super().__init__(
            detail=(
                f"This PAN is already held by company {existing_customer_id}; "
                "a PAN belongs to one company only"
            ),
            error_code="DUPLICATE_PAN",
            status_code=409,
            extensions={"existing_customer_id": str(existing_customer_id)},
        )


class InvalidMarkerTransitionError(AnerBaseException):
    """A marker move the company-record contract (§3.3) does not allow:
    ``ENDED`` -> ``PAUSED`` (clear first), or a move to the value the marker
    already has."""

    def __init__(self, customer_id: object, from_marker: object, to_marker: object) -> None:
        super().__init__(
            detail=(
                f"Company {customer_id}'s marker cannot move from {from_marker!r} "
                f"to {to_marker!r}"
            ),
            error_code="INVALID_MARKER_TRANSITION",
            status_code=409,
            extensions={"from_marker": str(from_marker), "to_marker": str(to_marker)},
        )


class QualificationCriterionNotFoundError(AnerBaseException):
    """No criterion has this key."""

    def __init__(self, key: str) -> None:
        super().__init__(
            detail=f"No qualification criterion has the key {key!r}",
            error_code="QUALIFICATION_CRITERION_NOT_FOUND",
            status_code=404,
            extensions={"key": key},
        )


class QualificationCriterionExistsError(AnerBaseException):
    """A criterion with this key already exists — change it by adding a
    version, not by creating it again."""

    def __init__(self, key: str) -> None:
        super().__init__(
            detail=(
                f"A qualification criterion with the key {key!r} already exists; "
                "add a version to change it"
            ),
            error_code="QUALIFICATION_CRITERION_EXISTS",
            status_code=409,
            extensions={"key": key},
        )


class QualificationCriterionChangedError(AnerBaseException):
    """Another change to this criterion landed first: the version this one
    would have become already exists. Nothing was saved; read the criterion
    again and re-apply the change on top of the current version."""

    def __init__(self, key: str, version: int) -> None:
        super().__init__(
            detail=(
                f"Version {version} of the qualification criterion {key!r} was added "
                "by someone else first; nothing was saved — reload it and try again"
            ),
            error_code="QUALIFICATION_CRITERION_CHANGED",
            status_code=409,
            extensions={"key": key, "version": version},
        )


class QualificationClosedError(AnerBaseException):
    """The company is already QUALIFIED. In the prototype that is final
    (assumption A2): no further results or outcomes are recorded; re-review is
    for NOT_QUALIFIED companies."""

    def __init__(self, customer_id: object) -> None:
        super().__init__(
            detail=(
                f"Company {customer_id} is already QUALIFIED; qualification is final "
                "once QUALIFIED (re-review applies to NOT_QUALIFIED companies)"
            ),
            error_code="QUALIFICATION_CLOSED",
            status_code=409,
        )


class PartnerPackageInvalidError(AnerBaseException):
    """A partner delivery (RXIL today) could not be read into the CRM's terms:
    a required field is missing, a value is malformed, or an identifier breaks
    the company rules. Lists every problem found, each with a code."""

    def __init__(self, partner: str, reasons: list[dict[str, str]]) -> None:
        super().__init__(
            detail=f"The {partner} delivery cannot be accepted: "
            + "; ".join(r["message"] for r in reasons),
            error_code="PARTNER_PACKAGE_INVALID",
            status_code=422,
            extensions={"reasons": reasons},
        )


class IntakeNeedsReviewError(AnerBaseException):
    """A delivered company resembles, or conflicts with, companies the CRM
    already has, and no PAN settles which one it is. It is neither merged into
    one of them nor created as another: a person decides."""

    def __init__(self, reasons: list[dict[str, str]], candidates: list[str]) -> None:
        super().__init__(
            detail="This company matches existing companies ambiguously and needs a "
            "person to decide: "
            + "; ".join(r["message"] for r in reasons),
            error_code="INTAKE_NEEDS_REVIEW",
            status_code=409,
            extensions={"reasons": reasons, "candidates": candidates},
        )


# ══════════════════════════════════════════════════════════════════════════════
# Section 9.3 — anchor blocks for Developers 3A and 3B
#
# This file is Developer 1's (architecture §8.1): additions only, owner reviews.
# Three people append exceptions to it — 3A in each of its two phases, and 3B —
# and a single shared append point means the same conflicting hunk every time.
# So the tail is cut into owned blocks in one commit (the seam commit), and from
# then on each owner adds classes inside their own block and nowhere else.
#
# The blocks are separated by their own comment headers, which is what keeps two
# owners' additions in different diff hunks: git's three lines of context reach
# the header rather than the neighbouring owner's last class.
# ══════════════════════════════════════════════════════════════════════════════

# ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ──
# (3A appends here; 3B does not.)
# Cut into the two phase sub-anchors below — phase agreement §6.3.


# ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──


class ConversationNotAvailableError(AnerBaseException):
    """The conversation gauge does not apply to this company yet.

    Assumption A4: the gauge applies **from ``PROSPECT`` onward**. A ``LEAD``
    carries the column — it is ``NOT NULL`` — reading ``NOT_CONTACTED``, but
    nobody has judged its conversation and nobody may: a ``LEAD`` becomes a
    ``PROSPECT`` when a qualification outcome says ``QUALIFIED``, and tracking
    how the sales conversation is going before we have decided we would finance
    them at all records an opinion about a company we may never call.

    409 rather than 422: the request is well formed, and the answer depends on
    the company's current journey rather than on anything the caller sent.
    """

    def __init__(self, customer_id: object, journey: object) -> None:
        super().__init__(
            detail=(
                f"Company {customer_id} is a {journey!s} — the conversation gauge "
                "applies from PROSPECT onward (assumption A4); qualify the company first"
            ),
            error_code="CONVERSATION_NOT_AVAILABLE",
            status_code=409,
            extensions={"journey": str(journey)},
        )


class InvalidConversationTransitionError(AnerBaseException):
    """A move to the value the conversation already has.

    The only conversation move that is refused. Any value may follow any other
    (``docs/contracts/engagement.md`` §1.1) — a conversation is a judgement, not
    a pipeline — but a move to the current value records nothing and would put a
    row whose ``from_value`` equals its ``to_value`` in the history log.
    """

    def __init__(self, customer_id: object, conversation: object) -> None:
        super().__init__(
            detail=(
                f"Company {customer_id}'s conversation is already {conversation!s}; "
                "a move to the current value records nothing"
            ),
            error_code="INVALID_CONVERSATION_TRANSITION",
            status_code=409,
            extensions={"conversation": str(conversation)},
        )


class ConversationCheckBackRequiredError(AnerBaseException):
    """``NOT_NOW`` without a check-back date.

    A conversation parked with no date is a conversation dropped, and the date is
    what puts the company on the Follow-ups list (``engagement.md`` §4). Stored on
    the company as ``conversation_check_back_on``; the database refuses the
    combination too (``ck_exporter_profile_conversation_check_back``).
    """

    def __init__(self, customer_id: object) -> None:
        super().__init__(
            detail=(
                f"Moving company {customer_id} to NOT_NOW needs a check-back date: "
                "a conversation parked with no date is a conversation dropped"
            ),
            error_code="CONVERSATION_CHECK_BACK_REQUIRED",
            status_code=422,
        )


class ConversationCheckBackNotAllowedError(AnerBaseException):
    """A check-back date on a move that is not to ``NOT_NOW``.

    Refused rather than ignored. Silently dropping the date would leave the
    operator believing one was stored, and the database would refuse the row
    anyway (``ck_exporter_profile_conversation_check_back``): a check-back date
    exists exactly when the conversation is ``NOT_NOW``.
    """

    def __init__(self, customer_id: object, conversation: object) -> None:
        super().__init__(
            detail=(
                f"A check-back date belongs only to NOT_NOW, and company {customer_id} "
                f"is being moved to {conversation!s}"
            ),
            error_code="CONVERSATION_CHECK_BACK_NOT_ALLOWED",
            status_code=422,
            extensions={"conversation": str(conversation)},
        )


class ConversationCheckBackInPastError(AnerBaseException):
    """A check-back date before today.

    A date in the past is a typo — 2025 for 2026 is the common one — and a
    Follow-ups list seeded with dates already overdue on the day they were
    entered is a list nobody trusts. Today is accepted: "check back later today"
    is a real thing to promise.
    """

    def __init__(self, customer_id: object, check_back_on: object, today: object) -> None:
        super().__init__(
            detail=(
                f"The check-back date for company {customer_id} is {check_back_on!s}, "
                f"which is before today ({today!s})"
            ),
            error_code="CONVERSATION_CHECK_BACK_IN_PAST",
            status_code=422,
            extensions={"check_back_on": str(check_back_on), "today": str(today)},
        )



# ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──


class FollowUpNotFoundError(AnerBaseException):
    """No ``exporter_activity`` row has this id.

    Distinct from ``ActivityIsNotAFollowUpError`` below on purpose: "there is no such
    activity" and "that activity is not something anyone promised to do" send a person
    looking in completely different places.
    """

    def __init__(self, activity_id: object) -> None:
        super().__init__(
            detail=f"No activity {activity_id} exists to complete",
            error_code="FOLLOW_UP_NOT_FOUND",
            status_code=404,
        )


class ActivityIsNotAFollowUpError(AnerBaseException):
    """The activity exists but carries no ``due_at``, so it is not a follow-up.

    A due date is the append-only activity log's own stand-in for "somebody promised
    to do this" (``docs/contracts/engagement.md`` §5.1). A logged call with no due
    date is a record of something that already happened; there is nothing outstanding
    to complete, and a completion row against it would put a row on the Follow-ups
    list that was never on it.
    """

    def __init__(self, activity_id: object) -> None:
        super().__init__(
            detail=(
                f"Activity {activity_id} has no due date, so it is not a follow-up; "
                "only an activity somebody promised to do can be completed"
            ),
            error_code="ACTIVITY_IS_NOT_A_FOLLOW_UP",
            status_code=409,
        )


class FollowUpAlreadyCompletedError(AnerBaseException):
    """This follow-up already has a completion row.

    A refusal, never an upsert: ``uq_follow_up_completion_activity_id`` allows exactly
    one (contract §5.4), and a reschedule is a **new** activity, so nothing
    legitimate completes the same one twice. Correcting a completion is a new activity
    plus its own completion, because both tables are append-only.

    Carries the existing completion's id and outcome, so a screen can say what is
    already recorded rather than only that the write failed.
    """

    def __init__(self, activity_id: object, completion_id: object, outcome: object) -> None:
        super().__init__(
            detail=(
                f"Follow-up {activity_id} was already completed as {outcome!s}; "
                "a completion is never edited — log a new follow-up instead"
            ),
            error_code="FOLLOW_UP_ALREADY_COMPLETED",
            status_code=409,
            extensions={"completion_id": str(completion_id), "outcome": str(outcome)},
        )


class FollowUpRescheduleNeedsDateError(AnerBaseException):
    """``RESCHEDULED`` without a new due date.

    ``ck_follow_up_completion_next_due`` refuses the row too. Rescheduling to nowhere
    is how a follow-up gets quietly dropped, which is the thing the Follow-ups list
    exists to prevent — so it is refused here with a code a screen can act on rather
    than left to the constraint.

    Phase 1 reserved ``CONVERSATION_CHECK_BACK_REQUIRED`` for reuse on this path
    (``engagement.md`` §7). It is not reused: that code names the *conversation*
    gauge's check-back date, on the company record, and this is a follow-up's next due
    moment, on an activity. One code covering both would tell a caller the wrong place
    to look. Recorded as a decision in ``engagement.md`` §7.1.
    """

    def __init__(self, activity_id: object) -> None:
        super().__init__(
            detail=(
                f"Rescheduling follow-up {activity_id} needs a new due date: "
                "a follow-up moved to no date is a follow-up dropped"
            ),
            error_code="FOLLOW_UP_RESCHEDULE_NEEDS_DATE",
            status_code=422,
        )


class FollowUpNextDueNotAllowedError(AnerBaseException):
    """A next due date on an outcome that is not ``RESCHEDULED``.

    Refused rather than ignored, for the same reason a check-back date on a move that
    is not ``NOT_NOW`` is refused (``engagement.md`` §4): silently dropping it would
    leave the operator believing the follow-up had been moved rather than closed.
    """

    def __init__(self, activity_id: object, outcome: object) -> None:
        super().__init__(
            detail=(
                f"A next due date belongs only to a RESCHEDULED follow-up, and "
                f"{activity_id} is being completed as {outcome!s}"
            ),
            error_code="FOLLOW_UP_NEXT_DUE_NOT_ALLOWED",
            status_code=422,
            extensions={"outcome": str(outcome)},
        )


class FollowUpRescheduleInPastError(AnerBaseException):
    """A reschedule to a moment that has already passed.

    A follow-up rescheduled into the past arrives on the list already overdue, which
    is never what the person meant and makes the overdue count untrustworthy — the
    same reasoning as ``CONVERSATION_CHECK_BACK_IN_PAST``.
    """

    def __init__(self, activity_id: object, next_due_at: object) -> None:
        super().__init__(
            detail=(
                f"Follow-up {activity_id} cannot be rescheduled to {next_due_at!s}, "
                "which is in the past"
            ),
            error_code="FOLLOW_UP_RESCHEDULE_IN_PAST",
            status_code=422,
            extensions={"next_due_at": str(next_due_at)},
        )


class FollowUpCompletionIsImmutableError(AnerBaseException):
    """Something tried to change or remove a completion.

    Both layers refuse it: ``FollowUpCompletionRepository`` extends
    ``AppendOnlyRepository``, which exposes no ``update`` and no ``delete``, and
    ``trg_follow_up_completion_append_only`` raises at the database whatever code
    tries. This exception exists so that an attempt through the service is a 409
    naming the rule rather than a 500 carrying a Postgres message — which is what
    Phase 2 owes in place of a new direct-SQL constraint test (prompt §3).
    """

    def __init__(self, completion_id: object) -> None:
        super().__init__(
            detail=(
                f"Follow-up completion {completion_id} cannot be changed or removed: "
                "completions are append-only, and a correction is a new record"
            ),
            error_code="FOLLOW_UP_COMPLETION_IMMUTABLE",
            status_code=409,
        )



# ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
# (3B appends here; 3A does not.)


class DealNotFoundError(AnerBaseException):
    """No deal with that id."""

    def __init__(self, deal_id: object) -> None:
        super().__init__(
            detail=f"Deal {deal_id} was not found",
            error_code="DEAL_NOT_FOUND",
            status_code=404,
        )


class DealCompanyNotFoundError(AnerBaseException):
    """A deal was opened for a company that does not exist.

    Distinct from ``DEAL_NOT_FOUND`` so the screen can say which of the two is
    missing; the database would refuse the row anyway through
    ``fk_deal_company_id``, and this turns that into a 404 naming the company
    rather than a 500 carrying a Postgres message.
    """

    def __init__(self, company_id: object) -> None:
        super().__init__(
            detail=f"Company {company_id} was not found, so no deal can be opened for it",
            error_code="DEAL_COMPANY_NOT_FOUND",
            status_code=404,
        )


class DealCompanyNotReadyError(AnerBaseException):
    """A deal was opened for a company that is still a ``LEAD``.

    A deal follows a sales conversation, and the conversation gauge applies from
    ``PROSPECT`` onward (assumption A4, ``engagement.md`` §2.2). Opening a deal also
    sets the conversation to ``READY_NOW`` (seam S1), so without this refusal a lead
    that was never qualified would end up with a conversation value it may not
    hold. 409 rather than 422: the request is well formed; the company is not there
    yet.
    """

    def __init__(self, company_id: object, journey: object) -> None:
        super().__init__(
            detail=(
                f"Company {company_id} is a {journey!s}: a deal can be opened only for a "
                "PROSPECT or a CUSTOMER. Record its qualification first."
            ),
            error_code="DEAL_COMPANY_NOT_READY",
            status_code=409,
            extensions={"journey": str(journey)},
        )


class DealTransitionNotAllowedError(AnerBaseException):
    """A stage move that is not in the deal contract's §1.1 table.

    Unlike the conversation gauge, a deal's stages are a fixed graph: a stage is a
    claim about what has happened to a deal, not a judgement about a relationship,
    so an unlisted move is refused rather than recorded.
    """

    def __init__(self, deal_id: object, from_stage: object, to_stage: object) -> None:
        super().__init__(
            detail=(
                f"Deal {deal_id} cannot move from {from_stage!s} to {to_stage!s}"
            ),
            error_code="DEAL_TRANSITION_NOT_ALLOWED",
            status_code=422,
            extensions={"from_stage": str(from_stage), "to_stage": str(to_stage)},
        )


class DealTerminalError(AnerBaseException):
    """A move out of ``HANDED_OVER`` or ``WITHDRAWN``.

    A deal withdrawn in error is a **new deal**, not a reopened one: a record of
    what was decided must not be editable into a different decision (deal
    contract §1.1). Separate from ``DEAL_TRANSITION_NOT_ALLOWED`` because the
    answer is different — not "not that move" but "not this deal, ever again".
    """

    def __init__(self, deal_id: object, stage: object) -> None:
        super().__init__(
            detail=(
                f"Deal {deal_id} is {stage!s} and cannot move again; open a new deal instead"
            ),
            error_code="DEAL_TERMINAL",
            status_code=409,
            extensions={"stage": str(stage)},
        )


class DealWithdrawalReasonRequiredError(AnerBaseException):
    """``WITHDRAWN`` without a reason (assumption A7).

    ``ck_deal_withdrawal_reason`` refuses the row as well, so this is the service
    saying the same thing first, with the deal's id in it.
    """

    def __init__(self, deal_id: object) -> None:
        super().__init__(
            detail=f"Withdrawing deal {deal_id} requires a reason",
            error_code="DEAL_WITHDRAWAL_REASON_REQUIRED",
            status_code=422,
        )


class DealBuyerRequiredError(AnerBaseException):
    """Leaving ``GATHERING_PAPERWORK`` with no buyer recorded.

    A handover payload carries the buyer (architecture §3.6), so a handover
    without one is not a handover. The buyer stays optional at ``OPEN``, since a
    deal often starts before the buyer is known (deal contract §3).
    """

    def __init__(self, deal_id: object) -> None:
        super().__init__(
            detail=(
                f"Deal {deal_id} has no buyer recorded, and the buyer's details are "
                "part of what the lending team is given"
            ),
            error_code="DEAL_BUYER_REQUIRED",
            status_code=422,
        )


class DocumentNotFoundError(AnerBaseException):
    """No document with that id, or no row for that storage key."""

    def __init__(self, document_ref: object) -> None:
        super().__init__(
            detail=f"Document {document_ref} was not found",
            error_code="DOCUMENT_NOT_FOUND",
            status_code=404,
        )


class DocumentCategoryNotAllowedError(AnerBaseException):
    """A category filed where it does not belong.

    Architecture §3.4 gives each of the ten categories an owner — a company, a
    deal, or both — so `SHIPPING` on a company is not a preference but a filing
    error, and the document would end up where nobody looks for it.
    """

    def __init__(self, category: object, reason: str) -> None:
        super().__init__(
            detail=f"{category} cannot be filed here: {reason}",
            error_code="DOCUMENT_CATEGORY_NOT_ALLOWED",
            status_code=422,
            extensions={"category": str(category)},
        )


class DocumentTypeNotAllowedError(AnerBaseException):
    """A type that the settings do not configure under this category.

    Types are settings, not code (architecture §3.4), so this is what an unknown
    one looks like: a 422 naming the category, not a new enum member. Adding the
    type is a GitOps change to
    `deployments/gitops/reference-data/crm/documents/document-types.yaml`.
    """

    def __init__(self, category: object, document_type: object) -> None:
        super().__init__(
            detail=(
                f"{document_type!r} is not a configured document type for {category}"
            ),
            error_code="DOCUMENT_TYPE_NOT_ALLOWED",
            status_code=422,
            extensions={"category": str(category), "document_type": str(document_type)},
        )


class DocumentContentTypeNotSupportedError(AnerBaseException):
    """A content type with no extension in the storage allow-list.

    The extension goes into the storage key, so a type with no known extension
    would have to be stored with a guessed one — and guessing from the uploaded
    file name is what §9.3's "Watch out for" forbids.
    """

    def __init__(self, content_type: object) -> None:
        super().__init__(
            detail=f"Files of type {content_type!r} are not accepted",
            error_code="DOCUMENT_CONTENT_TYPE_NOT_SUPPORTED",
            status_code=422,
            extensions={"content_type": str(content_type)},
        )


class DocumentNotAvailableError(AnerBaseException):
    """Content was requested for a document that is not `AVAILABLE`.

    Refused to **every** role: `PENDING_SCAN`, `QUARANTINED` and `SCAN_FAILED` are
    states, not permissions (architecture §3.4, assumption A9). There is no role,
    and no flag, that opens a quarantined file.
    """

    def __init__(self, document_id: object, scan_status: object) -> None:
        super().__init__(
            detail=(
                f"Document {document_id} is {scan_status} and cannot be opened; "
                "only a document that has passed the scan step is served"
            ),
            error_code="DOCUMENT_NOT_AVAILABLE",
            status_code=409,
            extensions={"scan_status": str(scan_status)},
        )


class DocumentLinkInvalidError(AnerBaseException):
    """A download link whose signature does not verify, or which has expired.

    One error for both, deliberately: telling a caller which of the two it was
    would help someone probing for a valid signature.
    """

    def __init__(self) -> None:
        super().__init__(
            detail="This download link is invalid or has expired",
            error_code="DOCUMENT_LINK_INVALID",
            status_code=403,
        )


class StorageKeyRefusedError(AnerBaseException):
    """A storage key that is absolute, escapes its root, or holds a bad segment.

    Reaching the boundary means something built a key from untrusted input; the
    implementation refuses it before any I/O (storage contract §2.1).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(
            detail=f"Storage key refused: {reason}",
            error_code="STORAGE_KEY_REFUSED",
            status_code=422,
        )


class DealHandoverBlockedError(AnerBaseException):
    """A handover whose assumption-A5 guard is unmet.

    The company must be a `CUSTOMER` **and** its background check `CLEAR`. The
    reason names which condition failed, including "the background check is not
    recorded yet" while Developer 4's migration 0015 is missing — "not recorded" is
    never treated as "clear".

    A class rather than an inline exception (which is what `deal_service.py` built
    until the review): the code it raises is part of the documented contract
    (`deal-and-buyer.md` §8), and every other refusal in this module is a named
    class.
    """

    def __init__(self, deal_id: object, reason: str) -> None:
        super().__init__(
            detail=f"Deal {deal_id} cannot be handed over: {reason}",
            error_code="DEAL_HANDOVER_BLOCKED",
            status_code=409,
            extensions={"reason": reason},
        )


# ══════════════════════════════════════════════════════════════════════════════
# Dev4 seam — anchor blocks for Developers 4A and 4B (4B-0; 4a/4b-task.md §9)
#
# Same reason as the §9.3 blocks above: two people append exceptions here in
# parallel pull requests, and one shared append point is one conflicting hunk
# every time. The Dev4 seam commit cuts two more owned blocks below the 3B block,
# and from then on each Dev4 owner adds classes inside its own block and nowhere
# else. Dev4B may additionally edit the existing `EXP-2: VerificationResult`
# classes above; Dev4A may not.
# ══════════════════════════════════════════════════════════════════════════════

# ── Background check — owner: Developer 4A ──
# (4A appends here; 4B does not.)


def _bc_value(value: object) -> str:
    """An enum's value (``IN_REVIEW``), not its repr-ish ``str`` (``BackgroundCheckState.IN_REVIEW``).

    The gauge and role enums mix in ``str`` but keep ``Enum.__str__``, so ``str()`` and
    ``!s`` would put the class name into the message and the error context a client reads.
    """
    return str(getattr(value, "value", value))


class BackgroundCheckMoveNotAllowedError(AnerBaseException):
    """A move that is not in the background-check contract's §3 table.

    Includes a move to the value already held (which would record nothing) and
    ``CLEAR → FLAGGED``: new information about a cleared company goes through a
    reopen and then ``FLAGGED`` (architecture §4.2), so that the reopen's reason is
    on the record rather than a cleared company silently becoming flagged.
    """

    def __init__(self, company_id: object, from_value: object, to_value: object) -> None:
        super().__init__(
            detail=(
                f"The background check for company {company_id} cannot move from "
                f"{_bc_value(from_value)} to {_bc_value(to_value)}"
            ),
            error_code="BACKGROUND_CHECK_MOVE_NOT_ALLOWED",
            status_code=409,
            extensions={"from_value": _bc_value(from_value), "to_value": _bc_value(to_value)},
        )


class BackgroundCheckRoleNotAllowedError(AnerBaseException):
    """The caller's role may not make this particular move.

    Roles are enforced **per move**, not only per route (contract §3): OPERATIONS may
    start a check and answer a ``MORE_INFO``, and nothing else. A route-level check
    alone would let an operations user flag a company.
    """

    def __init__(self, from_value: object, to_value: object, role: object) -> None:
        super().__init__(
            detail=(
                f"Role {_bc_value(role)} may not move a background check from {_bc_value(from_value)} "
                f"to {_bc_value(to_value)}"
            ),
            error_code="BACKGROUND_CHECK_ROLE_NOT_ALLOWED",
            status_code=403,
            extensions={
                "from_value": _bc_value(from_value),
                "to_value": _bc_value(to_value),
                "role": _bc_value(role),
            },
        )


class BackgroundCheckReasonRequiredError(AnerBaseException):
    """A move that needs text arrived without it, or with only whitespace.

    Every move but the start needs a reason or a note (contract §4). The service
    refuses it before anything is written and ``ck_background_check_decision_reason``
    refuses it again at the database.
    """

    def __init__(self, from_value: object, to_value: object) -> None:
        super().__init__(
            detail=(
                f"Moving a background check from {_bc_value(from_value)} to {_bc_value(to_value)} "
                "requires a reason or note"
            ),
            error_code="BACKGROUND_CHECK_REASON_REQUIRED",
            status_code=422,
            extensions={"from_value": _bc_value(from_value), "to_value": _bc_value(to_value)},
        )


class BackgroundCheckRiskRequiredError(AnerBaseException):
    """``CLEAR`` without a risk rating.

    Risk is set by compliance as part of the decision and is required on ``CLEAR``
    (architecture §3.3, A3, §4.1 step 9; contract §7), enforced here and by
    ``ck_background_check_decision_clear_risk``.
    """

    def __init__(self, company_id: object) -> None:
        super().__init__(
            detail=(
                f"Clearing the background check for company {company_id} requires a "
                "risk rating of LOW, MEDIUM, HIGH or CRITICAL"
            ),
            error_code="BACKGROUND_CHECK_RISK_REQUIRED",
            status_code=422,
            extensions={},
        )


class BackgroundCheckRiskNotAllowedError(AnerBaseException):
    """A risk rating on a move that is not ``CLEAR``.

    Risk is compliance's rating at the moment of clearing (contract §7). Accepting it
    elsewhere would let any move — an OPERATIONS start included — record a rating
    that the reader then reports as the company's. Refused here and again by
    ``ck_background_check_decision_risk_only_on_clear``.
    """

    def __init__(self, from_value: object, to_value: object) -> None:
        super().__init__(
            detail=(
                f"A risk rating is recorded only when a background check is cleared, "
                f"not on a move from {_bc_value(from_value)} to {_bc_value(to_value)}"
            ),
            error_code="BACKGROUND_CHECK_RISK_NOT_ALLOWED",
            status_code=422,
            extensions={"from_value": _bc_value(from_value), "to_value": _bc_value(to_value)},
        )


class BackgroundCheckStateChangedError(AnerBaseException):
    """The caller acted on a value the company no longer holds.

    The move request names a destination, and several moves share one (four reach
    ``IN_REVIEW``). A caller that sends the value it saw as ``from_value`` is refused
    here if someone moved the check in the meantime, rather than having its request
    silently become a different act — a reassessment turning into a reopen.
    """

    def __init__(self, company_id: object, expected: object, current: object) -> None:
        super().__init__(
            detail=(
                f"The background check for company {company_id} is now {_bc_value(current)}, "
                f"not {_bc_value(expected)}. Reload it and decide again"
            ),
            error_code="BACKGROUND_CHECK_STATE_CHANGED",
            status_code=409,
            extensions={"expected": _bc_value(expected), "current": _bc_value(current)},
        )


class BackgroundCheckPrerequisitesUnmetError(AnerBaseException):
    """``IN_REVIEW → CLEAR`` with one or more of A3's prerequisites unmet.

    Names every unmet prerequisite rather than the first, so the screen can list what
    is outstanding instead of revealing them one refusal at a time. The prerequisites
    are A3's; what two of its phrases mean is D1–D4 (``background_check_views``).
    """

    def __init__(self, company_id: object, unmet: object) -> None:
        names = list(unmet)
        super().__init__(
            detail=(
                f"The background check for company {company_id} cannot be cleared: "
                f"{', '.join(names)}"
            ),
            error_code="BACKGROUND_CHECK_PREREQUISITES_UNMET",
            status_code=409,
            extensions={"unmet": names},
        )


# ── Verification and screening — owner: Developer 4B ──
# (4B appends here; 4A does not.)


class ComplianceInputsBuyerNotFoundError(AnerBaseException):
    """No ``deal_buyer`` row exists for the ``deal_buyer_id`` a buyer check named.

    Raised by ``ComplianceInputsService.buyer_checks`` (4a/4b-task.md §6.3), and by
    ``VerificationService`` when a ``BUYER`` result's ``entity_reference`` is not a
    ``deal_buyer.id`` (§5.7). Buyer checks are keyed by ``deal_buyer.id`` only —
    never the deal id, never the company id — so an id that is not a buyer is a 404,
    not an empty list and not a check on something else.
    """

    def __init__(self, deal_buyer_id: object) -> None:
        self.deal_buyer_id = deal_buyer_id
        super().__init__(
            detail=f"Deal buyer {deal_buyer_id} not found",
            error_code="DEAL_BUYER_NOT_FOUND",
            status_code=404,
        )


class VerificationBuyerDealClosedError(AnerBaseException):
    """A new buyer check named a buyer whose deal is ``HANDED_OVER`` or ``WITHDRAWN``.

    Decision **D17** (lead, 28 Sep 2026): buyer checks are refused once the deal is
    terminal — the handover snapshot is the final word on a handed-over deal, and a
    withdrawn deal has no financing need left to check. Checks already recorded stay
    readable and reviewable. 409: the request is well-formed, the deal's state
    forbids it.
    """

    def __init__(self, *, deal_buyer_id: object, deal_id: object, stage: str) -> None:
        self.deal_buyer_id = deal_buyer_id
        self.deal_id = deal_id
        self.stage = stage
        super().__init__(
            detail=(
                f"Deal {deal_id} is {stage}: no new check can be recorded on its buyer "
                f"{deal_buyer_id}"
            ),
            error_code="DEAL_CLOSED",
            status_code=409,
            extensions={"deal_id": str(deal_id), "stage": stage},
        )


class VerificationLegacyReviewUnchainedError(AnerBaseException):
    """A result carries a legacy verdict (``verification_result.review_status``) but
    has no ``verification_review`` row for a new review to supersede.

    Migration ``onboarding_0021_verif_review`` copied every legacy verdict into the
    review table as its first review, and the service never writes the legacy columns
    since, so this state exists only if those columns were set outside the service
    afterwards (raw SQL). A new review would have nothing to supersede: recording it
    as a "first" review would overrule the legacy verdict with no supersede link and
    no stated reason — the silent overwrite 4b-task.md §5.1 forbids. So it is refused
    (409) until the legacy verdict is copied into ``verification_review`` the way the
    migration did; retrying does not help, unlike ``VerificationReviewStaleError``.
    """

    def __init__(self, *, verification_result_id: object, legacy_review_status: str) -> None:
        self.verification_result_id = verification_result_id
        self.legacy_review_status = legacy_review_status
        super().__init__(
            detail=(
                f"Verification result {verification_result_id} has a legacy review "
                f"({legacy_review_status}) with no review record to supersede. Its "
                "verdict must be copied into verification_review, as migration "
                "onboarding_0021_verif_review did, before it can be reviewed again."
            ),
            error_code="VERIFICATION_LEGACY_REVIEW_UNCHAINED",
            status_code=409,
            extensions={"legacy_review_status": legacy_review_status},
        )


# ── Compliance engine — owner: Developer 1 (allocation §3) ──
# (Developer 1 appends here.)


class BackgroundCheckDecisionNotFoundError(AnerBaseException):
    """No background-check decision with this id belongs to this company.

    A decision of another company is the same 404 as one that does not exist, so the
    evidence route cannot be used to learn which decision ids exist elsewhere.
    """

    def __init__(self, company_id: object, decision_id: object) -> None:
        super().__init__(
            detail=f"No background-check decision {decision_id} for company {company_id}",
            error_code="BACKGROUND_CHECK_DECISION_NOT_FOUND",
            status_code=404,
        )


class CheckCycleNotFoundError(AnerBaseException):
    """No check cycle with this id belongs to this company (404)."""

    def __init__(self, company_id: object, cycle_id: object) -> None:
        super().__init__(
            detail=f"No check cycle {cycle_id} for company {company_id}",
            error_code="CHECK_CYCLE_NOT_FOUND",
            status_code=404,
        )


class CheckCycleNotAllowedError(AnerBaseException):
    """A new cycle was asked for from a state that does not allow one (plan P2-3c).

    ``FLAGGED`` and ``ON_HOLD`` companies are reassessed first: a new round of checks
    is not how a concern already on record is dealt with. 409: the request is
    well-formed; the company's state forbids it.
    """

    def __init__(self, company_id: object, current: object) -> None:
        value = _bc_value(current)
        super().__init__(
            detail=(
                f"A new check cycle cannot be started while the background check for "
                f"company {company_id} is {value}; reassess it first"
            ),
            error_code="CHECK_CYCLE_NOT_ALLOWED",
            status_code=409,
            extensions={"current": value},
        )


class CheckCycleEmptyError(AnerBaseException):
    """The current cycle has nothing recorded in it yet, so a new one would replace an
    empty round with another empty round (plan P2-3c).

    This is also what makes two simultaneous starts produce **one** cycle: the second
    finds the first's new cycle still empty and is refused. 409.
    """

    def __init__(self, company_id: object, cycle_number: int) -> None:
        super().__init__(
            detail=(
                f"Check cycle {cycle_number} of company {company_id} has nothing recorded "
                "in it yet; record its checks before starting another"
            ),
            error_code="CHECK_CYCLE_EMPTY",
            status_code=409,
            extensions={"current_cycle_number": cycle_number},
        )


class CheckCycleRoleNotAllowedError(AnerBaseException):
    """Only COMPLIANCE and ADMIN may start a check cycle (plan P2-3c, IQ-3). 403."""

    def __init__(self, role: object) -> None:
        super().__init__(
            detail=f"The {_bc_value(role)} role may not start a check cycle",
            error_code="CHECK_CYCLE_ROLE_NOT_ALLOWED",
            status_code=403,
        )
