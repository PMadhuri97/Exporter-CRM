"""
FastAPI dependency injection for the provider framework.

Routes and services take a :class:`ProviderResolver` rather than reaching for the
module-level ``resolve_provider``. Two reasons:

* A test overrides one FastAPI dependency instead of monkeypatching a module
  global, so parallel tests cannot leak provider configuration into each other.
* The dependency graph states the requirement in the signature: a service that
  needs a provider says so, and one that does not, cannot reach for one.

Nothing here knows a vendor's name. A resolver takes the name the route resolver
emitted and returns something satisfying the contract.
"""
from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends

from app.modules.onboarding.domain.dto import ProviderCapability
from app.modules.onboarding.domain.ports import (
    IdentityVerificationProvider,
    ProviderAdapter,
    ScreeningProvider,
)
from app.modules.onboarding.infrastructure.registry import (
    ProviderRegistry,
    get_provider_registry,
)


def provider_registry_dependency() -> ProviderRegistry:
    """
    Yield the process-wide provider registry.

    Override this in tests via ``app.dependency_overrides`` to inject a registry
    holding stub adapters.
    """
    return get_provider_registry()


class ProviderResolver:
    """
    A capability-aware facade over the registry, injected into services.

    Holds no adapter: each method constructs a fresh one, because adapters own HTTP
    clients that must not be shared across event loops.

    Every method raises a 422 domain error — ``PROVIDER_NOT_REGISTERED``,
    ``PROVIDER_NOT_ENABLED``, or ``PROVIDER_CAPABILITY_UNSUPPORTED`` — *before* any
    external call is attempted, and therefore before any ``provider_run`` row is
    created.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def identity(self, provider_name: str) -> IdentityVerificationProvider:
        """Resolve an identity-verification provider by name."""
        adapter = self._registry.create_for_capability(
            provider_name, ProviderCapability.IDENTITY_VERIFICATION
        )
        return cast(IdentityVerificationProvider, adapter)

    def screening(self, provider_name: str) -> ScreeningProvider:
        """Resolve a screening provider by name."""
        adapter = self._registry.create_for_capability(provider_name, ProviderCapability.SCREENING)
        return cast(ScreeningProvider, adapter)

    def any_provider(self, provider_name: str) -> ProviderAdapter:
        """
        Resolve a provider without asserting a capability.

        For callers that only need ``parse_webhook`` / ``normalize_result``, which
        every provider implements — webhook ingestion, for instance, which must
        parse an event before it knows what the provider was for.
        """
        return self._registry.create(provider_name)

    def enabled_names(self, capability: ProviderCapability | None = None) -> tuple[str, ...]:
        """Names enabled in this environment, optionally filtered by capability."""
        if capability is None:
            return self._registry.enabled_names()
        return self._registry.names_for_capability(capability)


def provider_resolver_dependency(
    registry: Annotated[ProviderRegistry, Depends(provider_registry_dependency)],
) -> ProviderResolver:
    """The dependency a route or service declares to gain provider access."""
    return ProviderResolver(registry)


#: Annotated aliases, so a route signature reads
#: ``providers: ProviderResolverDep`` rather than repeating ``Depends(...)``.
ProviderRegistryDep = Annotated[ProviderRegistry, Depends(provider_registry_dependency)]
ProviderResolverDep = Annotated[ProviderResolver, Depends(provider_resolver_dependency)]
