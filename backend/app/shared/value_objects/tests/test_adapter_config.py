"""Tests for config-driven adapter registration.

Proves adapters are wired by declarative config, the dispatcher has no asset-specific
branches, and a new asset needs only a registry entry + config/adapter entry.
"""
import inspect
from decimal import Decimal

from app.shared.value_objects import (
    ADAPTER_CONFIG,
    TRANSLATION_REGISTRY,
    AssetType,
    CurrencyAsset,
    CurrencyRegistry,
    TranslationAdapter,
    TranslationDispatcher,
    TranslationRegistry,
    UsdcTranslationAdapter,
    translate_to_internal,
)

# ── The declarative config + generic load ───────────────────────────────────────

def test_config_declares_usdc():
    assert "USDC" in ADAPTER_CONFIG
    assert ADAPTER_CONFIG["USDC"] is UsdcTranslationAdapter


def test_load_registers_every_config_entry():
    reg = TranslationRegistry()
    reg.load(ADAPTER_CONFIG)
    assert "USDC" in reg
    assert isinstance(reg.require("USDC"), UsdcTranslationAdapter)


def test_load_accepts_both_factories_and_instances():
    reg = TranslationRegistry()
    reg.load({"USDC": UsdcTranslationAdapter})                     # factory (class)
    reg.load({"USDC": UsdcTranslationAdapter()}, overwrite=True)   # ready instance
    assert isinstance(reg.require("USDC"), UsdcTranslationAdapter)


def test_process_wide_registry_was_loaded_from_config():
    # The package facade loaded ADAPTER_CONFIG into the singleton at import time.
    assert "USDC" in TRANSLATION_REGISTRY
    assert translate_to_internal("USDC", "100.500000") == 100_500_000


# ── The dispatcher has no asset-specific logic ──────────────────────────────────

def test_dispatcher_has_no_asset_specific_branch():
    """No switch, no `if asset_code == "USDC"`: the dispatcher names no asset."""
    src = inspect.getsource(TranslationDispatcher)
    assert "USDC" not in src
    assert "asset_code ==" not in src
    assert "==" not in src  # dispatch is pure lookup — no equality branching at all


def test_load_is_generic_and_names_no_asset():
    src = inspect.getsource(TranslationRegistry.load)
    assert "USDC" not in src


# ── Registration flow: adding a new asset touches only config + adapter ─────────

class _MockTokenAdapter(TranslationAdapter):
    """A future on-chain asset's adapter — decimal major-unit format."""

    def to_canonical(self, external, asset):
        return Decimal(str(external))

    def from_canonical(self, amount, asset):
        return str(amount)


def test_adding_a_new_asset_requires_only_registry_entry_and_config():
    # 1) currency-registry entry for the new asset
    currencies = CurrencyRegistry(
        version="test-mock",
        assets={"MOCK": CurrencyAsset("MOCK", AssetType.STABLECOIN, 6, "micro-mock")},
    )
    # 2) a config entry mapping asset_code → adapter (the only registration surface)
    config = {"MOCK": _MockTokenAdapter}

    adapters = TranslationRegistry()
    adapters.load(config)

    # 3) the SAME, unmodified dispatcher class now serves the new asset
    dispatcher = TranslationDispatcher(currency_registry=currencies, adapters=adapters)
    assert dispatcher.to_internal("MOCK", "1.5") == 1_500_000


def test_two_assets_share_one_unchanged_dispatcher():
    currencies = CurrencyRegistry(
        version="test-multi",
        assets={
            "USDC": CurrencyAsset("USDC", AssetType.STABLECOIN, 6, "micro-USDC"),
            "MOCK": CurrencyAsset("MOCK", AssetType.STABLECOIN, 6, "micro-mock"),
        },
    )
    adapters = TranslationRegistry()
    adapters.load({"USDC": UsdcTranslationAdapter, "MOCK": _MockTokenAdapter})
    dispatcher = TranslationDispatcher(currency_registry=currencies, adapters=adapters)

    assert dispatcher.to_internal("USDC", "100.50") == 100_500_000
    assert dispatcher.to_internal("MOCK", "2.5") == 2_500_000
    assert set(adapters.codes()) == {"USDC", "MOCK"}
