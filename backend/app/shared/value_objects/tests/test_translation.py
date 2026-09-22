"""Tests for the generic on-chain translation layer.

Uses local fake adapters to prove dispatch, precision enforcement, and that a second
asset needs only a registry entry + adapter (no dispatcher change). Runs against
isolated registries.
"""
from decimal import Decimal

import pytest

from app.shared.value_objects import (
    TRANSLATION_REGISTRY,
    AdapterNotRegisteredError,
    AssetType,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
    ExcessPrecisionError,
    TranslationAdapter,
    TranslationDispatcher,
    TranslationRegistry,
    translate_from_internal,
    translate_to_internal,
)

# ── Fake adapters (two distinct external formats) ───────────────────────────────

class IntegerBaseUnitsAdapter(TranslationAdapter):
    """External amounts arrive as integer base units in the asset's own scale
    (e.g. an ERC-20 style integer). Scale comes from the registry, never hardcoded."""

    def to_canonical(self, external_amount, asset: CurrencyAsset) -> Decimal:
        return Decimal(int(external_amount)).scaleb(-asset.precision)

    def from_canonical(self, amount: Decimal, asset: CurrencyAsset):
        return int(amount.scaleb(asset.precision))


class DecimalMajorUnitsAdapter(TranslationAdapter):
    """External amounts arrive as a decimal string in major units (e.g. "1.5")."""

    def to_canonical(self, external_amount, asset: CurrencyAsset) -> Decimal:
        return Decimal(str(external_amount))

    def from_canonical(self, amount: Decimal, asset: CurrencyAsset):
        return str(amount)


# ── Fixtures: an isolated currency revision + adapter registry ──────────────────

@pytest.fixture()
def currency_registry() -> CurrencyRegistry:
    return CurrencyRegistry(
        version="test-onchain",
        assets={
            # MOCKA — 6 dp, external format = integer base units
            "MOCKA": CurrencyAsset("MOCKA", AssetType.STABLECOIN, 6, "micro-mocka"),
            # MOCKB — 8 dp, external format = decimal-string major units
            "MOCKB": CurrencyAsset("MOCKB", AssetType.CRYPTO, 8, "sat-mockb"),
            # A fiat asset with NO adapter — proves fiat bypasses translation.
            "USD": CurrencyAsset("USD", AssetType.FIAT, 2, "cent"),
        },
    )


@pytest.fixture()
def dispatcher(currency_registry) -> TranslationDispatcher:
    adapters = TranslationRegistry()
    adapters.register("MOCKA", IntegerBaseUnitsAdapter())
    return TranslationDispatcher(currency_registry=currency_registry, adapters=adapters)


# ── Core dispatch ───────────────────────────────────────────────────────────────

def test_to_internal_dispatches_by_asset_code(dispatcher):
    # 100.500000 MOCKA delivered as 100500000 base units → 100500000 minor units.
    assert dispatcher.to_internal("MOCKA", 100_500_000) == 100_500_000
    assert dispatcher.to_internal("MOCKA", 1) == 1  # 0.000001 MOCKA


def test_from_internal_round_trips(dispatcher):
    external = dispatcher.from_internal("MOCKA", 100_500_000)
    assert external == 100_500_000
    assert dispatcher.to_internal("MOCKA", external) == 100_500_000


def test_unknown_asset_is_rejected_by_registry(dispatcher):
    with pytest.raises(CurrencyNotRegisteredError):
        dispatcher.to_internal("NOPE", 1)


def test_missing_adapter_raises(dispatcher):
    # MOCKB is a known asset but has no adapter registered.
    with pytest.raises(AdapterNotRegisteredError):
        dispatcher.to_internal("MOCKB", "1.0")


def test_fiat_has_no_adapter_and_never_translates(dispatcher):
    # USD is a valid asset but intentionally has no adapter — translation is not
    # for fiat. Fiat goes straight through the conversion layer instead.
    with pytest.raises(AdapterNotRegisteredError):
        dispatcher.to_internal("USD", "1.00")


# ── Precision enforcement is delegated, not duplicated ──────────────────────────

def test_excess_precision_rejected_via_conversion_layer(currency_registry):
    adapters = TranslationRegistry()
    adapters.register("MOCKB", DecimalMajorUnitsAdapter())
    disp = TranslationDispatcher(currency_registry=currency_registry, adapters=adapters)

    assert disp.to_internal("MOCKB", "1.23456789") == 123_456_789  # 8 dp OK
    with pytest.raises(ExcessPrecisionError):
        disp.to_internal("MOCKB", "1.234567891")  # 9 dp — rejected by to_minor_units


# ── Extensibility: a second asset needs no dispatcher change (AC #6 pattern) ─────

def test_registering_second_asset_requires_no_core_change(currency_registry):
    """Register two on-chain assets with two different external formats into the same
    dispatcher; both translate correctly. Only registry entries were added — the
    TranslationDispatcher and its dispatch logic are untouched."""
    adapters = TranslationRegistry()
    adapters.register("MOCKA", IntegerBaseUnitsAdapter())   # integer base units
    adapters.register("MOCKB", DecimalMajorUnitsAdapter())  # decimal major units
    disp = TranslationDispatcher(currency_registry=currency_registry, adapters=adapters)

    assert disp.to_internal("MOCKA", 2_500_000) == 2_500_000     # 2.5 MOCKA (6 dp)
    assert disp.to_internal("MOCKB", "2.5") == 250_000_000       # 2.5 MOCKB (8 dp)
    assert set(adapters.codes()) == {"MOCKA", "MOCKB"}


# ── Module-level front doors + injected dispatcher ──────────────────────────────

def test_module_functions_use_injected_dispatcher(dispatcher):
    assert translate_to_internal("MOCKA", 100_500_000, dispatcher=dispatcher) == 100_500_000
    assert translate_from_internal("MOCKA", 100_500_000, dispatcher=dispatcher) == 100_500_000


# ── TranslationRegistry behaviour ───────────────────────────────────────────────

def test_registry_guards_against_accidental_overwrite():
    reg = TranslationRegistry()
    reg.register("MOCKA", IntegerBaseUnitsAdapter())
    with pytest.raises(ValueError):
        reg.register("MOCKA", DecimalMajorUnitsAdapter())
    # explicit overwrite is allowed
    reg.register("MOCKA", DecimalMajorUnitsAdapter(), overwrite=True)
    assert isinstance(reg.require("MOCKA"), DecimalMajorUnitsAdapter)


def test_registry_rejects_non_adapter():
    reg = TranslationRegistry()
    with pytest.raises(TypeError):
        reg.register("MOCKA", object())  # type: ignore[arg-type]


def test_registry_membership_and_unregister():
    reg = TranslationRegistry()
    adapter = IntegerBaseUnitsAdapter()
    reg.register("MOCKA", adapter)
    assert "MOCKA" in reg and reg.has("MOCKA") and len(reg) == 1
    assert reg.get("MOCKA") is adapter
    reg.unregister("MOCKA")
    assert "MOCKA" not in reg and reg.get("MOCKA") is None
    with pytest.raises(AdapterNotRegisteredError):
        reg.require("MOCKA")


def test_process_wide_registry_has_only_usdc():
    """The one wired on-chain adapter is USDC; assets without one don't translate."""
    from app.shared.value_objects import UsdcTranslationAdapter

    assert "USDC" in TRANSLATION_REGISTRY
    assert isinstance(TRANSLATION_REGISTRY.require("USDC"), UsdcTranslationAdapter)
    assert "MOCKA" not in TRANSLATION_REGISTRY
