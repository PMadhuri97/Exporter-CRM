"""Asset-specific on-chain translation adapters (selected by asset_code)."""
from app.shared.value_objects.adapters.config import ADAPTER_CONFIG
from app.shared.value_objects.adapters.usdc import UsdcTranslationAdapter

__all__ = ["UsdcTranslationAdapter", "ADAPTER_CONFIG"]
