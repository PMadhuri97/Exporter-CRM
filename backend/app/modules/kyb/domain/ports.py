from abc import ABC, abstractmethod

from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)


class KYBAdapter(ABC):
    """
    The unified KYB Vendor Adapter interface.
    Every integration to an external KYB provider must implement this interface.
    """

    @abstractmethod
    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        """Returns the static capability declaration for this KYB vendor."""
        pass

    @abstractmethod
    def verify_entity(self, entity: EntityVerificationRequest) -> KYBVerificationResult:
        """Submits the entity for verification to the KYB vendor."""
        pass

    @abstractmethod
    def get_verification_status(self, vendor_reference: str) -> KYBVerificationResult:
        """
        For vendors that process verifications asynchronously.
        Polls for the result of a previously submitted verification.
        Not implemented (or acts as a no-op) by synchronous vendors.
        """
        pass

    @abstractmethod
    def get_vendor_health(self) -> VendorHealthStatus:
        """Performs a health check on the KYB vendor."""
        pass


REGISTRY: dict[str, type[KYBAdapter]] = {}


def register_adapter(name: str, adapter_cls: type[KYBAdapter]) -> None:
    REGISTRY[name] = adapter_cls


#: Packages a dotted-path adapter may be imported from.
#:
#: ``get_adapter``'s dotted fallback imports a caller-supplied module and hands
#: back the attribute it names, which callers then instantiate. An unrestricted
#: path is caller-chosen import-and-invoke. Adapters live in exactly two
#: packages; nothing outside them is a legitimate target.
#:
#: Kept byte-identical to
#: ``onboarding.domain.workflow_dependencies.ADAPTER_MODULE_ALLOWLIST`` — that
#: registry is specified as a straight copy of this one, so the two must not
#: drift in what they admit.
ADAPTER_MODULE_ALLOWLIST: tuple[str, ...] = (
    "app.modules.onboarding.infrastructure.adapters",
    "app.modules.kyb.infrastructure.adapters",
)


def _module_is_allowlisted(module_name: str) -> bool:
    """True if ``module_name`` is an allowlisted package or a submodule of one.

    Compares against ``prefix + "."`` rather than a bare ``startswith`` so a
    sibling named ``...adapters_injected`` cannot ride in on the prefix.
    """
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in ADAPTER_MODULE_ALLOWLIST
    )


def get_adapter(class_path: str) -> type[KYBAdapter]:
    if class_path in REGISTRY:
        return REGISTRY[class_path]
    if "." in class_path:
        module_name, class_name = class_path.rsplit(".", 1)
        if not _module_is_allowlisted(module_name):
            raise ValueError(
                f"KYB adapter class {class_path} is not in registry and "
                f"module {module_name} is not an allowlisted adapter package"
            )
        import importlib
        module = importlib.import_module(module_name)
        resolved = getattr(module, class_name, None)
        # An allowlisted module still exposes imports, constants and helpers.
        # Only an adapter class may come back out of here, because the caller
        # instantiates whatever this returns.
        if not isinstance(resolved, type) or not issubclass(resolved, KYBAdapter):
            raise ValueError(f"KYB adapter class {class_path} is not a KYBAdapter")
        return resolved
    raise ValueError(f"KYB adapter class {class_path} not found in registry and not fully qualified")

__all__ = [
    "KYBAdapter",
    "ADAPTER_MODULE_ALLOWLIST",
    "register_adapter",
    "get_adapter",
]
