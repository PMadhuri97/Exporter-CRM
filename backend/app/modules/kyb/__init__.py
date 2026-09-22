"""
KYB Module Facade.
"""
from app.modules.kyb.domain.ports import KYBAdapter, get_adapter, register_adapter
from app.modules.kyb.infrastructure.adapters.middesk_adapter import MiddeskAdapter

__all__ = [
    "KYBAdapter",
    "MiddeskAdapter",
    "get_adapter",
    "register_adapter",
]
