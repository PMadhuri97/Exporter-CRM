"""Declarative config of built-in on-chain translation adapters.

Maps ``asset_code`` -> adapter factory; loaded generically by
:meth:`TranslationRegistry.load`. Enabling an asset = a currency-registry entry plus
one line here — no dispatcher change, no per-asset branching.
"""
from __future__ import annotations

from collections.abc import Mapping

from app.shared.value_objects.adapters.usdc import UsdcTranslationAdapter
from app.shared.value_objects.translation import AdapterFactory

#: asset_code → adapter factory. Add a line to enable a new on-chain asset.
ADAPTER_CONFIG: Mapping[str, AdapterFactory] = {
    "USDC": UsdcTranslationAdapter,
}

__all__ = ["ADAPTER_CONFIG"]
