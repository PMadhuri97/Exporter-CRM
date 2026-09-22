"""Tests for the USDC on-chain translation adapter.

Covers parsing of Circle/on-chain formats to minor units, registry-driven precision,
chain round-trip, and dispatch through the default dispatcher.
"""
from decimal import Decimal

import pytest

from app.shared.value_objects import (
    AssetType,
    CurrencyAsset,
    CurrencyRegistry,
    ExcessPrecisionError,
    TranslationDispatcher,
    TranslationRegistry,
    UsdcTranslationAdapter,
    translate_from_internal,
    translate_to_internal,
)

# ── Plugs into the default (process-wide) dispatcher, no dispatcher change ───────

@pytest.mark.parametrize(
    "external, expected_minor",
    [
        ("100.500000", 100_500_000),                              # decimal major string
        (Decimal("100.50"), 100_500_000),                         # Decimal major units
        (100_500_000, 100_500_000),                               # int on-chain base units
        ("100500000", 100_500_000),                               # bare integer string = base units
        ({"amount": "100.50", "currency": "USD"}, 100_500_000),   # Circle API amount object
        ({"amount": "100.50", "currency": "USDC"}, 100_500_000),  # currency may be USDC
        ({"amount": "100500000", "unit": "base"}, 100_500_000),   # explicit base units
        ("0.000001", 1),                                          # one micro-USDC
        ("0", 0),
    ],
)
def test_to_internal_via_default_dispatcher(external, expected_minor):
    assert translate_to_internal("USDC", external) == expected_minor


def test_from_internal_returns_chain_base_units_and_round_trips():
    chain = translate_from_internal("USDC", 100_500_000)
    assert chain == 100_500_000  # on-chain base units (== minor units at 6 dp)
    assert translate_to_internal("USDC", chain) == 100_500_000


# ── Acceptance criteria ─────────────────────────────────────────────────────────

def test_ac_stored_as_integer_minor_units():
    # AC: USDC 100.500000 is stored as integer 100500000.
    assert translate_to_internal("USDC", "100.500000") == 100_500_000


def test_ac_excess_precision_rejected():
    # AC: a USDC amount with more than 6 decimal places is rejected.
    with pytest.raises(ExcessPrecisionError):
        translate_to_internal("USDC", "1.2345678")   # 7 dp
    with pytest.raises(ExcessPrecisionError):
        translate_to_internal("USDC", Decimal("1.0000001"))


# ── Payload validation ──────────────────────────────────────────────────────────

def test_rejects_non_usd_payload_currency():
    with pytest.raises(ValueError):
        translate_to_internal("USDC", {"amount": "1.00", "currency": "EUR"})


def test_rejects_payload_without_amount():
    with pytest.raises(ValueError):
        translate_to_internal("USDC", {"currency": "USD"})


def test_rejects_non_integer_base_units():
    with pytest.raises(ValueError):
        translate_to_internal("USDC", {"amount": "100.5", "unit": "base"})


# ── Precision is read from the registry, never hardcoded ────────────────────────

def test_precision_is_registry_driven_not_hardcoded():
    """The SAME adapter, pointed at a registry revision where USDC is defined with a
    different precision, scales by that precision — proving 6 is not baked in."""
    four_dp = CurrencyRegistry(
        version="test-usdc-4dp",
        assets={"USDC": CurrencyAsset("USDC", AssetType.STABLECOIN, 4, "milli-USDC")},
    )
    adapters = TranslationRegistry()
    adapters.register("USDC", UsdcTranslationAdapter())
    disp = TranslationDispatcher(currency_registry=four_dp, adapters=adapters)

    # major units → minor units scaled by 4, not 6
    assert disp.to_internal("USDC", "100.50") == 1_005_000
    # base units interpreted at precision 4
    assert disp.to_internal("USDC", 1_005_000) == 1_005_000
    # the excess-precision boundary moves with the registry: 4 dp ok, 5 dp rejected
    assert disp.to_internal("USDC", "1.2345") == 12_345
    with pytest.raises(ExcessPrecisionError):
        disp.to_internal("USDC", "1.23456")
