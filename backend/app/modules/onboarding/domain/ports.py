"""
The internal provider contract.

This module is the boundary between Aner's workflow and every external KYC/KYB or
screening vendor. Business logic imports *only* this module and
:mod:`app.modules.onboarding.domain.dto`. It must never import
``providers.sumsub``, a ComplyAdvantage module, or any other vendor package —
``tests/onboarding/test_provider_contract.py`` enforces that by inspection.

Shape: composed capabilities, not one flat ABC
----------------------------------------------
The backlog names six methods: ``create_subject``, ``submit_profile``,
``start_checks``, ``get_status``, ``parse_webhook``, ``normalize_result``. All six
exist here. They are grouped rather than flattened, because screening has no
profile-submission step — a single six-method ABC would force a screening provider
to raise ``NotImplementedError`` from two of them, and a contract whose
implementations lie about what they support is not a contract.

    SupportsWebhook          parse_webhook, normalize_result       (every provider)
      ├─ IdentityVerificationProvider   + create_subject, submit_profile,
      │                                   start_checks, get_status
      └─ ScreeningProvider              + start_checks, get_status

Both branches produce the same :class:`~...dto.NormalizedResult`, which is what the
acceptance criteria actually test.

.. warning::
   **This contract is NOT frozen.** Escalation E1 (``docs/project-memory.md``
   §10.1) is open: Tejasvi owns the screening adapters and must ratify this split
   before the version drops its ``-draft`` suffix. The backlog requires freezing
   adapter methods *before* vendor code is written, so no vendor adapter should be
   built against this until E1 closes.

Why ``Protocol`` and not ``ABC``
--------------------------------
Structural typing means an adapter never has to import this module to satisfy it,
which keeps the dependency arrow pointing one way: vendors depend on nothing, the
workflow depends on the contract. The protocols are ``@runtime_checkable`` so the
contract tests can assert conformance of a live instance with ``isinstance``.

Note that ``isinstance`` against a runtime-checkable ``Protocol`` verifies member
*presence*, not signatures. :data:`REQUIRED_METHODS` exists so contract tests can
produce a precise "adapter X is missing method Y" failure rather than a bare
``False``.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar, Protocol, runtime_checkable

from app.modules.onboarding.domain.dto import (
    CheckRequest,
    CheckRun,
    NormalizedResult,
    ProfileInput,
    ProfileRef,
    ProviderCapability,
    ProviderStatus,
    SubjectInput,
    SubjectRef,
    WebhookEvent,
    WebhookRequest,
)


@runtime_checkable
class SupportsWebhook(Protocol):
    """
    The methods every provider must implement, whatever its capability.

    Attributes:
        name: The provider's registry key, e.g. ``"mock"``. This is the string the
            route resolver emits and the registry resolves on. It is
            the *only* form in which a vendor's identity may appear in business
            logic — as opaque data, never as an import or a constant.
        capabilities: What this adapter can actually do. The registry checks this
            before handing the adapter to a caller.
    """

    name: ClassVar[str]
    capabilities: ClassVar[frozenset[ProviderCapability]]

    def parse_webhook(self, request: WebhookRequest) -> WebhookEvent:
        """
        Interpret a raw inbound webhook in vendor-neutral terms.

        The caller has already persisted the raw event. This method must verify the
        signature where the vendor supports it and set
        ``WebhookEvent.signature_verified`` accordingly; an unverifiable event is
        rejected and audited *without* being processed.

        The returned :class:`WebhookEvent` carries no verdict. It updates a
        ``provider_run``; it can never approve or reject a case.

        Args:
            request: The exact bytes received, plus headers. Signature digests are
                computed over the raw body, so it is not pre-parsed.

        Returns:
            The parsed event.

        Raises:
            InvalidProviderPayloadError: The body is malformed or unrecognized.
        """
        ...

    def normalize_result(
        self,
        *,
        raw_payload: Mapping[str, Any],
        provider_run_id: uuid.UUID | None = None,
    ) -> NormalizedResult:
        """
        Map a vendor's raw response onto the shared :class:`NormalizedResult`.

        This is the **only** method in the system permitted to read a vendor's raw
        payload, and the raw payload must not survive into the return value: point
        at it with an ``EvidenceRef`` instead. Everything downstream — the state
        machine, the decision layer, the workflow — reads the normalized result.

        A provider failure is normalized like any other outcome, to
        ``overall_status=FAILED`` with populated ``failure_details``. It is never
        represented by patching the database by hand.

        Args:
            raw_payload: The vendor response, as received.
            provider_run_id: The run this result belongs to, once runs exist.

        Returns:
            The normalized result.

        Raises:
            ProviderNormalizationError: The payload could not be mapped.
        """
        ...


@runtime_checkable
class IdentityVerificationProvider(SupportsWebhook, Protocol):
    """
    A provider that verifies who a subject is: identity, documents, liveness.

    Sumsub implements this. The four methods below model the full
    lifecycle of a verification: open a subject, give it a profile, ask for checks,
    then read the outcome.
    """

    async def create_subject(self, subject: SubjectInput) -> SubjectRef:
        """
        Open a subject with the provider and return the vendor's handle on it.

        Must be idempotent for a given ``external_subject_id``: calling it twice
        returns the same ``provider_subject_id`` rather than creating a duplicate.

        Args:
            subject: Case, subject type, country, and Aner's own subject id.
                Deliberately PII-free, so this call may be logged and traced.

        Returns:
            The vendor's subject handle.

        Raises:
            UnsupportedCountryError: The provider does not cover this country.
            ProviderTimeoutError | ProviderUnavailableError: Transient; retryable.
        """
        ...

    async def submit_profile(self, profile: ProfileInput) -> ProfileRef:
        """
        Attach the subject's identity attributes to the provider-side subject.

        Args:
            profile: **Carries PII.** Never log this argument, never audit its
                contents, never place it in an event payload.

        Returns:
            Acknowledgement of acceptance.

        Raises:
            InvalidProviderPayloadError: The provider rejected the attributes.
            ProviderTimeoutError | ProviderUnavailableError: Transient; retryable.
        """
        ...

    async def start_checks(self, request: CheckRequest) -> CheckRun:
        """
        Ask the provider to run the requested checks against the subject.

        The caller has already created a ``provider_run`` row and resolved a route.
        This method never decides *which* checks to
        run; it executes the ones the route resolver required.

        Args:
            request: The subject handle and the check types to run.

        Returns:
            The vendor's reference for this unit of work.

        Raises:
            UnsupportedCountryError: A requested check is unavailable in-country.
            InvalidProviderPayloadError: A requested check type is not supported.
            ProviderTimeoutError | ProviderUnavailableError: Transient; retryable.
        """
        ...

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        """
        Poll the provider for the current state of a check run.

        The fallback path when a webhook is lost, and the reconciliation path that
        makes the workflow restart-safe: ``provider_run`` state lives in PostgreSQL,
        and this method re-derives the vendor's half of the truth.

        Args:
            provider_reference: The value returned as ``CheckRun.provider_reference``.

        Returns:
            The provider's current view, including structured failure details if it
            failed.

        Raises:
            ProviderTimeoutError | ProviderUnavailableError: Transient; retryable.
        """
        ...


@runtime_checkable
class ScreeningProvider(SupportsWebhook, Protocol):
    """
    A provider that screens a known subject against watchlists: sanctions, PEP,
    adverse media.

    ComplyAdvantage implements this (Tejasvi). There is no
    ``create_subject`` or ``submit_profile``: screening takes the subject's
    attributes as arguments to the check itself, so the subject is never "opened".
    """

    async def start_checks(self, request: CheckRequest) -> CheckRun:
        """
        Screen the subject against the requested watchlists.

        See :meth:`IdentityVerificationProvider.start_checks`. The contract is
        identical; only the ``check_types`` differ.
        """
        ...

    async def get_status(self, provider_reference: str) -> ProviderStatus:
        """
        Poll the provider for the current state of a screening run.

        See :meth:`IdentityVerificationProvider.get_status`.
        """
        ...


#: Any adapter, whatever its capability. Use this as the type of a value pulled out
#: of the registry when the caller does not yet know which capability it needs.
ProviderAdapter = SupportsWebhook


#: The methods each capability obliges an adapter to implement.
#:
#: Contract tests read this to report exactly which method an adapter is missing.
#: The union of both entries is the six methods the backlog names.
REQUIRED_METHODS: Mapping[ProviderCapability, frozenset[str]] = {
    ProviderCapability.IDENTITY_VERIFICATION: frozenset(
        {
            "create_subject",
            "submit_profile",
            "start_checks",
            "get_status",
            "parse_webhook",
            "normalize_result",
        }
    ),
    ProviderCapability.SCREENING: frozenset(
        {
            "start_checks",
            "get_status",
            "parse_webhook",
            "normalize_result",
        }
    ),
}


#: The runtime-checkable protocol that guards each capability.
PROTOCOL_FOR_CAPABILITY: Mapping[ProviderCapability, type] = {
    ProviderCapability.IDENTITY_VERIFICATION: IdentityVerificationProvider,
    ProviderCapability.SCREENING: ScreeningProvider,
}


#: Every method name the backlog requires, across all capabilities. Present so a
#: reviewer can check the six-method requirement at a glance.
ALL_CONTRACT_METHODS: frozenset[str] = frozenset().union(*REQUIRED_METHODS.values())
