"""
Provider registry and resolver.

The registry is how a provider name becomes a provider adapter. Business logic asks
for ``"mock"`` — a string the route resolver emits from a
``provider_route`` row — and receives something satisfying the contract. It never
imports a vendor module, never branches on a vendor name, and never learns which
vendor it just used. That is the whole point: adding a provider is a configuration
change plus one new adapter module, with no edit to any existing business logic.

Three layers, in order:

``_KNOWN_FACTORIES``
    Name → zero-argument factory. Each factory imports its adapter *inside* the
    call, so a provider that is configured off is never imported and its optional
    dependencies and credentials are never touched.

:class:`ProviderRegistry`
    Holds the factories and the set of names enabled for this environment. Refuses
    an unknown name, a disabled name, or a name whose adapter lacks the capability
    the caller needs — all before any external call, so before any ``provider_run``
    row exists.

:func:`resolve_provider` and friends
    The module-level entry points. Following the platform's dependency-injection
    convention (FX, USDC bridge, INR payout, notifications), these are ``resolve_*``
    functions that tests monkeypatch.

Enablement comes from ``ONBOARDING_ENABLED_PROVIDERS``, a comma-separated list in
``pydantic-settings``, environment-separated as the backlog requires. Defaults to
the two mock adapters so CI and local development run credential-free.

.. note::
   Two functions live here with different jobs. :func:`resolve_identity_provider`
   is the **legacy** boolean-flag resolver serving the existing onboarding module
   (``create_applicant`` / ``generate_sdk_token`` / ``parse_webhook``). It is
   retired when the Sumsub adapter moves behind the new contract.
   Everything else in this module is the new orchestration framework. They do not
   interact.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import cast

import structlog

from app.modules.onboarding.domain.dto import ProviderCapability
from app.modules.onboarding.domain.ports import (
    PROTOCOL_FOR_CAPABILITY,
    IdentityVerificationProvider,
    ProviderAdapter,
    ScreeningProvider,
)
from app.modules.onboarding.domain.ports_legacy import BaseIdentityProvider
from app.modules.onboarding.exceptions import (
    ProviderCapabilityError,
    ProviderNotEnabledError,
    ProviderNotRegisteredError,
)
from app.modules.onboarding.infrastructure.mock_identity_provider import MockIdentityProvider
from app.platform.configuration.config import Settings, get_settings

logger = structlog.get_logger(__name__)

#: A zero-argument callable that constructs a fresh adapter.
ProviderFactory = Callable[[], ProviderAdapter]


def _build_mock_identity() -> ProviderAdapter:
    from app.modules.onboarding.infrastructure.adapters.mock_provider import (
        MockIdentityProviderAdapter,
    )

    return MockIdentityProviderAdapter()


def _build_mock_screening() -> ProviderAdapter:
    from app.modules.onboarding.infrastructure.adapters.mock_provider import (
        MockScreeningProviderAdapter,
    )

    return MockScreeningProviderAdapter()


#: Every adapter the platform knows how to construct, keyed by its registry name.
#:
#: To add a provider: write the adapter, add one entry here, and add its name to
#: ``ONBOARDING_ENABLED_PROVIDERS``. No existing business logic changes. The Sumsub
#: and ComplyAdvantage adapters are added the same way.
_KNOWN_FACTORIES: dict[str, ProviderFactory] = {
    "mock": _build_mock_identity,
    "mock_screening": _build_mock_screening,
}



class ProviderRegistry:
    """
    Resolves provider names to contract-conforming adapters.

    A registry instance is cheap and holds no adapter state — :meth:`create` builds
    a fresh adapter per call, because adapters own HTTP clients and must not be
    shared across event loops.

    Args:
        enabled: The provider names permitted in this environment. A name that is
            registered but not enabled raises :class:`ProviderNotEnabledError`, which
            is a different and more actionable failure than "unknown provider".
    """

    def __init__(self, *, enabled: Iterable[str] | None = None) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._enabled: set[str] = set(enabled or ())

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
        """
        Register a factory under ``name``.

        Args:
            name: The registry key. This is the string a ``provider_route`` row
                stores and the route resolver emits.
            factory: Zero-argument callable returning a fresh adapter. Import the
                adapter inside the callable so a disabled provider is never imported.
            replace: Permit overwriting an existing registration. Tests use this;
                production code should not.

        Raises:
            ValueError: ``name`` is already registered and ``replace`` is False.
        """
        if name in self._factories and not replace:
            raise ValueError(f"Provider '{name}' is already registered")
        self._factories[name] = factory

    def enable(self, name: str) -> None:
        """Mark a registered provider as usable in this environment."""
        self._enabled.add(name)

    def registered_names(self) -> tuple[str, ...]:
        """Every registered name, enabled or not, sorted."""
        return tuple(sorted(self._factories))

    def enabled_names(self) -> tuple[str, ...]:
        """Every name that is both registered and enabled, sorted."""
        return tuple(sorted(n for n in self._factories if n in self._enabled))

    def is_enabled(self, name: str) -> bool:
        return name in self._factories and name in self._enabled

    # ── Resolution ───────────────────────────────────────────────────────────

    def create(self, name: str) -> ProviderAdapter:
        """
        Construct the adapter registered under ``name``.

        Args:
            name: The provider name, as emitted by the route resolver.

        Returns:
            A fresh adapter satisfying the provider contract.

        Raises:
            ProviderNotRegisteredError: No factory under that name (422).
            ProviderNotEnabledError: Registered, but off in this environment (422).
        """
        factory = self._factories.get(name)
        if factory is None:
            raise ProviderNotRegisteredError(name)
        if name not in self._enabled:
            raise ProviderNotEnabledError(name)

        adapter = factory()
        logger.debug("provider_adapter_created", provider=name)
        return adapter

    def create_for_capability(self, name: str, capability: ProviderCapability) -> ProviderAdapter:
        """
        Construct ``name``'s adapter and assert it can do ``capability``.

        Capability is checked against the adapter's **declared** ``capabilities``
        rather than by structural typing alone. The two differ: an identity adapter
        structurally satisfies :class:`ScreeningProvider`, because screening's method
        set is a subset of identity's. Only the declaration distinguishes an adapter
        that *can* screen from one that merely has the right method names.

        The structural check runs second, to catch an adapter that declares a
        capability it does not actually implement.

        Args:
            name: The provider name.
            capability: What the caller needs the adapter to do.

        Returns:
            A fresh adapter, guaranteed to satisfy ``capability``.

        Raises:
            ProviderNotRegisteredError | ProviderNotEnabledError: See :meth:`create`.
            ProviderCapabilityError: The adapter does not declare, or does not
                implement, the requested capability (422).
        """
        adapter = self.create(name)

        declared: frozenset[ProviderCapability] = getattr(adapter, "capabilities", frozenset())
        if capability not in declared:
            raise ProviderCapabilityError(name, capability.value)

        protocol = PROTOCOL_FOR_CAPABILITY[capability]
        if not isinstance(adapter, protocol):
            # The adapter lies about itself. A bug, not a configuration problem —
            # but it must still fail before any external call is made.
            logger.error(
                "provider_capability_declaration_mismatch",
                provider=name,
                capability=capability.value,
            )
            raise ProviderCapabilityError(name, capability.value)

        return adapter

    def names_for_capability(self, capability: ProviderCapability) -> tuple[str, ...]:
        """
        Every enabled provider that declares ``capability``, sorted.

        Constructs each adapter to read its declaration, so call it sparingly.
        """
        matches = []
        for name in self.enabled_names():
            adapter = self.create(name)
            if capability in getattr(adapter, "capabilities", frozenset()):
                matches.append(name)
        return tuple(matches)


def build_default_registry(settings: Settings | None = None) -> ProviderRegistry:
    """
    Build a registry from every known factory, enabling what configuration allows.

    Every known provider is *registered*; only those named in
    ``ONBOARDING_ENABLED_PROVIDERS`` are *enabled*. The distinction lets a
    misconfigured environment say "provider 'sumsub' is not enabled here" instead of
    the misleading "no such provider".

    A configured name with no registered factory is logged and skipped rather than
    raising, so a stale environment variable cannot prevent the application from
    starting; the failure surfaces at resolution time, on the one request that
    needs it.
    """
    resolved = settings or get_settings()
    registry = ProviderRegistry()

    for name, factory in _KNOWN_FACTORIES.items():
        registry.register(name, factory)

    for name in resolved.onboarding_enabled_provider_names:
        if name not in _KNOWN_FACTORIES:
            logger.warning("provider_enabled_but_not_registered", provider=name)
            continue
        registry.enable(name)

    logger.info("provider_registry_built", enabled=list(registry.enabled_names()))
    return registry


_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """
    The process-wide registry, built on first use.

    Lazy rather than ``@lru_cache``-at-import so that a test which overrides
    ``ONBOARDING_ENABLED_PROVIDERS`` before the first resolution sees its own value.
    """
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def reset_provider_registry() -> None:
    """Drop the cached registry. For tests that change provider configuration."""
    global _registry
    _registry = None


def resolve_provider(name: str, capability: ProviderCapability | None = None) -> ProviderAdapter:
    """
    Resolve a provider name to an adapter. **The framework's main entry point.**

    Args:
        name: The provider name emitted by the route resolver. Business logic passes
            this through as opaque data; it must never compare it to a literal.
        capability: If given, the adapter is additionally checked for it.

    Returns:
        A fresh, contract-conforming adapter.

    Raises:
        ProviderNotRegisteredError | ProviderNotEnabledError | ProviderCapabilityError:
            All 422 domain errors, all raised before any external call.
    """
    registry = get_provider_registry()
    if capability is None:
        return registry.create(name)
    return registry.create_for_capability(name, capability)


def resolve_identity_verification_provider(name: str) -> IdentityVerificationProvider:
    """
    Resolve ``name`` as an identity-verification provider, or fail with 422.

    ``create_for_capability`` has already proven the adapter satisfies the protocol,
    both by declaration and structurally, so the cast restates a checked fact.
    """
    adapter = resolve_provider(name, ProviderCapability.IDENTITY_VERIFICATION)
    return cast(IdentityVerificationProvider, adapter)


def resolve_screening_provider(name: str) -> ScreeningProvider:
    """Resolve ``name`` as a screening provider, or fail with 422."""
    adapter = resolve_provider(name, ProviderCapability.SCREENING)
    return cast(ScreeningProvider, adapter)


# ── Legacy resolver (retired once Sumsub moves behind the new contract) ──────


def resolve_identity_provider() -> BaseIdentityProvider:
    """
    Return the live SumsubProvider when SUMSUB_ENABLED, else the in-process mock.

    **Legacy.** This serves the pre-backlog onboarding module, whose narrow
    three-method ``BaseIdentityProvider`` interface predates the provider contract.
    It is untouched by this work and retired later, when the Sumsub
    integration moves behind :mod:`app.modules.onboarding.domain.ports`.

    New code must use :func:`resolve_provider`.
    """
    if get_settings().SUMSUB_ENABLED:
        from app.integrations.identity_providers.sumsub import SumsubProvider

        return SumsubProvider()
    return MockIdentityProvider()
