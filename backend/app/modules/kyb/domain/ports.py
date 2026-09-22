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


def get_adapter(class_path: str) -> type[KYBAdapter]:
    if class_path in REGISTRY:
        return REGISTRY[class_path]
    if "." in class_path:
        module_name, class_name = class_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    raise ValueError(f"KYB adapter class {class_path} not found in registry and not fully qualified")

__all__ = [
    "KYBAdapter",
    "register_adapter",
    "get_adapter",
]
