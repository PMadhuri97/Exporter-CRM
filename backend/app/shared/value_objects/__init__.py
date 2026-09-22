"""Shared, framework-agnostic value objects and reference data."""
from app.shared.value_objects.adapters import ADAPTER_CONFIG, UsdcTranslationAdapter
from app.shared.value_objects.conversion import (
    ROUNDING,
    AmountLike,
    ExcessPrecisionError,
    InvalidAmountError,
    get_currency,
    round_to_asset_precision,
    round_to_minor_units,
    to_decimal,
    to_minor_units,
    validate_precision,
)
from app.shared.value_objects.currency import (
    CURRENCY_REGISTRY,
    REGISTRY_VERSION,
    AssetType,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
)
from app.shared.value_objects.translation import (
    TRANSLATION_REGISTRY,
    AdapterNotRegisteredError,
    ExternalAmount,
    TranslationAdapter,
    TranslationDispatcher,
    TranslationRegistry,
    translate_from_internal,
    translate_to_internal,
)

# Load the declarative adapter config into the process-wide registry (idempotent).
TRANSLATION_REGISTRY.load(ADAPTER_CONFIG, overwrite=True)

__all__ = [
    # registry
    "CURRENCY_REGISTRY",
    "REGISTRY_VERSION",
    "AssetType",
    "CurrencyAsset",
    "CurrencyRegistry",
    "CurrencyNotRegisteredError",
    # conversion layer
    "AmountLike",
    "ROUNDING",
    "ExcessPrecisionError",
    "InvalidAmountError",
    "get_currency",
    "validate_precision",
    "to_minor_units",
    "to_decimal",
    # rounding policy
    "round_to_minor_units",
    "round_to_asset_precision",
    # on-chain translation layer (generic; adapters registered at composition time)
    "ExternalAmount",
    "AdapterNotRegisteredError",
    "TranslationAdapter",
    "TranslationRegistry",
    "TranslationDispatcher",
    "TRANSLATION_REGISTRY",
    "translate_to_internal",
    "translate_from_internal",
    # asset-specific on-chain adapters + declarative registration config
    "UsdcTranslationAdapter",
    "ADAPTER_CONFIG",
]
