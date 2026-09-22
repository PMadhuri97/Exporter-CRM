"""Unit tests for the shared Currency Registry (pure — no DB, no app services)."""
import dataclasses

import pytest

from app.shared.value_objects import (
    CURRENCY_REGISTRY,
    REGISTRY_VERSION,
    AssetType,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
)


def test_registry_is_versioned():
    assert CURRENCY_REGISTRY.version == REGISTRY_VERSION
    assert REGISTRY_VERSION == "1.1.0"


def test_seeds_usd_inr_and_usdc():
    assert set(CURRENCY_REGISTRY.codes()) == {"USD", "INR", "USDC"}


@pytest.mark.parametrize(
    "code, precision, minor_unit_name",
    [("USD", 2, "cent"), ("INR", 2, "paisa")],
)
def test_fiat_seed_entries_have_required_fields(code, precision, minor_unit_name):
    asset = CURRENCY_REGISTRY.require(code)
    assert asset.asset_code == code
    assert asset.asset_type is AssetType.FIAT
    assert asset.precision == precision
    assert asset.minor_unit_name == minor_unit_name


def test_usdc_is_registered():
    """USDC is a first-class registry entry (STABLECOIN, 6 dp)."""
    usdc = CURRENCY_REGISTRY.require("USDC")
    assert usdc.asset_code == "USDC"
    assert usdc.asset_type is AssetType.STABLECOIN
    assert usdc.precision == 6
    assert usdc.minor_unit_name == "micro-USDC"
    assert CURRENCY_REGISTRY.has("USDC")
    assert "USDC" in CURRENCY_REGISTRY


def test_get_returns_none_for_unknown():
    assert CURRENCY_REGISTRY.get("EUR") is None
    assert not CURRENCY_REGISTRY.has("EUR")
    assert "EUR" not in CURRENCY_REGISTRY


def test_require_raises_for_unknown():
    with pytest.raises(CurrencyNotRegisteredError):
        CURRENCY_REGISTRY.require("EUR")


def test_entries_are_immutable():
    asset = CURRENCY_REGISTRY.require("USD")
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.precision = 6  # type: ignore[misc]


def test_registry_supports_future_assets_without_schema_change():
    """A future asset (e.g. BTC) fits the existing record shape — data, not schema."""
    btc = CurrencyAsset("BTC", AssetType.CRYPTO, 8, "satoshi")
    future = CurrencyRegistry(
        version="2.0.0",
        assets={a.asset_code: a for a in (*CURRENCY_REGISTRY.all(), btc)},
    )
    assert future.require("BTC").precision == 8
    assert future.require("BTC").asset_type is AssetType.CRYPTO
    # The seeded registry is untouched by building a new revision.
    assert "BTC" not in CURRENCY_REGISTRY


def test_precision_must_be_non_negative_int():
    with pytest.raises(ValueError):
        CurrencyAsset("XxX", AssetType.FIAT, 2, "unit")  # not uppercase
    with pytest.raises(ValueError):
        CurrencyAsset("BAD", AssetType.FIAT, -1, "unit")  # negative precision
