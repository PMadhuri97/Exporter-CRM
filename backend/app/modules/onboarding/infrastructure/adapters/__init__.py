"""
Provider adapters.

One module per vendor. Nothing in the platform imports these directly — the
registry constructs them lazily by name, so that business logic never names a
vendor. The two mock adapters here are the credential-free default used by CI.

`ManualEntryAdapter` (EXP-2) and `StubRxilAdapter` (Exporter CRM Piece 3) are
a different, simpler registry (`workflow_dependencies.
VERIFICATION_ADAPTER_REGISTRY`, generalized from `kyb.domain.ports.REGISTRY`)
than the two mocks above (`infrastructure/registry.py`'s `ProviderRegistry`)
— importing them here, the same way `kyb/__init__.py` imports
`MiddeskAdapter`, is what runs their module-level `register_adapter(...)`
calls.
"""
from app.modules.onboarding.infrastructure.adapters.manual_entry_adapter import (
    ManualEntryAdapter,
)
from app.modules.onboarding.infrastructure.adapters.mock_provider import (
    MockIdentityProviderAdapter,
    MockScreeningProviderAdapter,
)
from app.modules.onboarding.infrastructure.adapters.stub_rxil_adapter import (
    StubRxilAdapter,
)

__all__ = [
    "ManualEntryAdapter",
    "MockIdentityProviderAdapter",
    "MockScreeningProviderAdapter",
    "StubRxilAdapter",
]
