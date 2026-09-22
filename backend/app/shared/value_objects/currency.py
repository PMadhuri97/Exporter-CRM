"""Version-controlled currency registry — the single source of truth for precision.

CHANGELOG
    1.1.0 — Add USDC (STABLECOIN, precision 6, micro-USDC). Additive, backward
            compatible: existing USD/INR entries and the registry API are unchanged.
    1.0.0 — Initial seeded registry: USD, INR (both FIAT, precision 2).
"""
from __future__ import annotations

import enum
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

REGISTRY_VERSION = "1.1.0"


class AssetType(str, enum.Enum):
    FIAT = "FIAT"
    CRYPTO = "CRYPTO"
    STABLECOIN = "STABLECOIN"


@dataclass(frozen=True)
class CurrencyAsset:
    asset_code: str
    asset_type: AssetType
    precision: int
    minor_unit_name: str

    def __post_init__(self) -> None:
        if not self.asset_code or not self.asset_code.isupper():
            raise ValueError(f"asset_code must be a non-empty uppercase string, got {self.asset_code!r}")
        if not isinstance(self.asset_type, AssetType):
            raise ValueError(f"asset_type must be an AssetType, got {self.asset_type!r}")
        if not isinstance(self.precision, int) or isinstance(self.precision, bool) or self.precision < 0:
            raise ValueError(f"precision must be a non-negative integer, got {self.precision!r}")
        if not self.minor_unit_name:
            raise ValueError("minor_unit_name must be a non-empty string")


class CurrencyNotRegisteredError(KeyError):
    """Raised by :meth:`CurrencyRegistry.require` for an unknown asset code."""


class CurrencyRegistry:
    def __init__(self, version: str, assets: Mapping[str, CurrencyAsset]) -> None:
        self._version = version
        self._assets: Mapping[str, CurrencyAsset] = MappingProxyType(dict(assets))

    @property
    def version(self) -> str:
        """The semantic version of the reference data this registry holds."""
        return self._version

    def get(self, asset_code: str) -> CurrencyAsset | None:
        """Return the entry for ``asset_code``, or ``None`` if not registered."""
        return self._assets.get(asset_code)

    def require(self, asset_code: str) -> CurrencyAsset:
        """Like :meth:`get`, but raise :class:`CurrencyNotRegisteredError` if absent."""
        try:
            return self._assets[asset_code]
        except KeyError:
            raise CurrencyNotRegisteredError(
                f"asset_code {asset_code!r} is not in the currency registry "
                f"(version {self._version})"
            ) from None

    def has(self, asset_code: str) -> bool:
        """True if ``asset_code`` is registered."""
        return asset_code in self._assets

    def codes(self) -> tuple[str, ...]:
        """All registered asset codes, in insertion order."""
        return tuple(self._assets.keys())

    def all(self) -> tuple[CurrencyAsset, ...]:
        """All registered entries, in insertion order."""
        return tuple(self._assets.values())

    def __contains__(self, asset_code: object) -> bool:
        return asset_code in self._assets

    def __iter__(self) -> Iterator[CurrencyAsset]:
        return iter(self._assets.values())

    def __len__(self) -> int:
        return len(self._assets)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CurrencyRegistry(version={self._version!r}, codes={self.codes()})"


_SEED: tuple[CurrencyAsset, ...] = (
    CurrencyAsset(
        asset_code="USD",
        asset_type=AssetType.FIAT,
        precision=2,
        minor_unit_name="cent",
    ),
    CurrencyAsset(
        asset_code="INR",
        asset_type=AssetType.FIAT,
        precision=2,
        minor_unit_name="paisa",
    ),
    CurrencyAsset(
        asset_code="USDC",
        asset_type=AssetType.STABLECOIN,
        precision=6,
        minor_unit_name="micro-USDC",
    ),
)

#: The process-wide currency registry singleton. Import this to look assets up.
CURRENCY_REGISTRY = CurrencyRegistry(
    version=REGISTRY_VERSION,
    assets={asset.asset_code: asset for asset in _SEED},
)


__all__ = [
    "REGISTRY_VERSION",
    "AssetType",
    "CurrencyAsset",
    "CurrencyRegistry",
    "CurrencyNotRegisteredError",
    "CURRENCY_REGISTRY",
]
