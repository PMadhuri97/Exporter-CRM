"""Generic, asset-agnostic on-chain amount translation.

Turns external amount representations (on-chain / vendor payloads) into internal
integer minor units and back. Dispatch: asset_code -> registered adapter ->
canonical Decimal -> conversion layer -> minor units. Holds no asset-specific logic;
precision always comes from the currency registry. Asset adapters are registered at
composition time (shared may not import them). Fiat has no adapter and bypasses this
layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from typing import Any, Union

from app.shared.value_objects.conversion import (
    get_currency,
    to_decimal,
    to_minor_units,
)
from app.shared.value_objects.currency import (
    CURRENCY_REGISTRY,
    CurrencyAsset,
    CurrencyRegistry,
)

#: An external amount representation; its shape is known only to the adapter.
ExternalAmount = Any

#: A zero-arg callable that builds an adapter (usually the adapter class).
AdapterFactory = Callable[[], "TranslationAdapter"]

#: A config entry: a ready adapter instance or a factory that builds one.
AdapterConfigEntry = Union["TranslationAdapter", AdapterFactory]


class AdapterNotRegisteredError(KeyError):
    """No :class:`TranslationAdapter` is registered for an asset code."""


class TranslationAdapter(ABC):
    """Translates one external amount format to/from the canonical major-unit Decimal.

    Handed the asset's registry entry, so scale is never hardcoded. Does not pick the
    asset (the dispatcher does) or touch minor units (the conversion layer does).
    """

    @abstractmethod
    def to_canonical(self, external_amount: ExternalAmount, asset: CurrencyAsset) -> Decimal:
        """External representation -> canonical Decimal in major units."""

    @abstractmethod
    def from_canonical(self, amount: Decimal, asset: CurrencyAsset) -> ExternalAmount:
        """Canonical Decimal in major units -> external representation."""


class TranslationRegistry:
    """Mutable ``asset_code`` -> adapter map, populated at composition time."""

    def __init__(self, adapters: Mapping[str, TranslationAdapter] | None = None) -> None:
        self._adapters: dict[str, TranslationAdapter] = dict(adapters or {})

    def register(
        self,
        asset_code: str,
        adapter: TranslationAdapter,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register ``adapter`` for ``asset_code``; won't clobber unless ``overwrite``."""
        if not isinstance(adapter, TranslationAdapter):
            raise TypeError(
                f"adapter must be a TranslationAdapter, got {type(adapter).__name__}"
            )
        if not overwrite and asset_code in self._adapters:
            raise ValueError(
                f"a translation adapter is already registered for {asset_code!r}; "
                f"pass overwrite=True to replace it"
            )
        self._adapters[asset_code] = adapter

    def unregister(self, asset_code: str) -> None:
        """Remove the adapter for ``asset_code`` if present."""
        self._adapters.pop(asset_code, None)

    def load(
        self,
        config: Mapping[str, AdapterConfigEntry],
        *,
        overwrite: bool = False,
    ) -> None:
        """Register every adapter declared in ``config`` (asset_code -> adapter/factory).

        Generic: no asset names, no per-asset branching.
        """
        for asset_code, entry in config.items():
            adapter = entry if isinstance(entry, TranslationAdapter) else entry()
            self.register(asset_code, adapter, overwrite=overwrite)

    def get(self, asset_code: str) -> TranslationAdapter | None:
        """Return the adapter for ``asset_code``, or ``None``."""
        return self._adapters.get(asset_code)

    def require(self, asset_code: str) -> TranslationAdapter:
        """Like :meth:`get`, but raise :class:`AdapterNotRegisteredError` if absent."""
        try:
            return self._adapters[asset_code]
        except KeyError:
            raise AdapterNotRegisteredError(
                f"no translation adapter registered for asset_code {asset_code!r}"
            ) from None

    def has(self, asset_code: str) -> bool:
        return asset_code in self._adapters

    def codes(self) -> tuple[str, ...]:
        """Asset codes with a registered adapter."""
        return tuple(self._adapters.keys())

    def __contains__(self, asset_code: object) -> bool:
        return asset_code in self._adapters

    def __iter__(self) -> Iterator[str]:
        return iter(self._adapters.keys())

    def __len__(self) -> int:
        return len(self._adapters)


class TranslationDispatcher:
    """Bridges the currency registry, adapter registry, and conversion layer.

    Both registries are injectable; defaults are the process-wide singletons.
    """

    def __init__(
        self,
        *,
        currency_registry: CurrencyRegistry = CURRENCY_REGISTRY,
        adapters: TranslationRegistry | None = None,
    ) -> None:
        self._currency_registry = currency_registry
        self._adapters = adapters if adapters is not None else TRANSLATION_REGISTRY

    def to_internal(self, asset_code: str, external_amount: ExternalAmount) -> int:
        """External representation -> internal integer minor units.

        Precision is enforced by the conversion layer (``ExcessPrecisionError``).
        """
        asset = get_currency(asset_code, registry=self._currency_registry)
        adapter = self._adapters.require(asset_code)
        canonical = adapter.to_canonical(external_amount, asset)
        return to_minor_units(canonical, asset_code, registry=self._currency_registry)

    def from_internal(self, asset_code: str, minor_units: int) -> ExternalAmount:
        """Internal integer minor units -> external representation."""
        asset = get_currency(asset_code, registry=self._currency_registry)
        adapter = self._adapters.require(asset_code)
        canonical = to_decimal(minor_units, asset_code, registry=self._currency_registry)
        return adapter.from_canonical(canonical, asset)


#: Process-wide adapter registry, populated at composition time (empty by default).
TRANSLATION_REGISTRY = TranslationRegistry()

#: Default dispatcher bound to the process-wide registries.
_DEFAULT_DISPATCHER = TranslationDispatcher()


def translate_to_internal(
    asset_code: str,
    external_amount: ExternalAmount,
    *,
    dispatcher: TranslationDispatcher = _DEFAULT_DISPATCHER,
) -> int:
    """External on-chain amount -> internal integer minor units."""
    return dispatcher.to_internal(asset_code, external_amount)


def translate_from_internal(
    asset_code: str,
    minor_units: int,
    *,
    dispatcher: TranslationDispatcher = _DEFAULT_DISPATCHER,
) -> ExternalAmount:
    """Internal integer minor units -> external on-chain representation."""
    return dispatcher.from_internal(asset_code, minor_units)


__all__ = [
    "ExternalAmount",
    "AdapterFactory",
    "AdapterConfigEntry",
    "AdapterNotRegisteredError",
    "TranslationAdapter",
    "TranslationRegistry",
    "TranslationDispatcher",
    "TRANSLATION_REGISTRY",
    "translate_to_internal",
    "translate_from_internal",
]
