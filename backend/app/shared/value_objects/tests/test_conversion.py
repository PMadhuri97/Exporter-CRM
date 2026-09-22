"""
Comprehensive unit tests for the money conversion layer.

Pure tests — no database, no app services. They prove the layer is registry-driven
(precision always comes from the registry, never hardcoded), asset-agnostic
(a custom registry with a 6 dp stablecoin and a 0 dp currency behaves correctly),
and that it rejects unsupported currencies and excess precision.
"""
from decimal import Decimal

import pytest

from app.shared.value_objects import (
    AssetType,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
    ExcessPrecisionError,
    InvalidAmountError,
    get_currency,
    to_decimal,
    to_minor_units,
    validate_precision,
)

# ── A registry with non-2dp assets, to prove nothing is hardcoded ─────────────

@pytest.fixture(scope="module")
def extended_registry() -> CurrencyRegistry:
    return CurrencyRegistry(
        version="test-1",
        assets={
            "USD": CurrencyAsset("USD", AssetType.FIAT, 2, "cent"),
            "INR": CurrencyAsset("INR", AssetType.FIAT, 2, "paisa"),
            "JPY": CurrencyAsset("JPY", AssetType.FIAT, 0, "sen"),
            "USDC": CurrencyAsset("USDC", AssetType.STABLECOIN, 6, "micro-USDC"),
        },
    )


# ── get_currency ──────────────────────────────────────────────────────────────

def test_get_currency_returns_registry_entry():
    asset = get_currency("USD")
    assert asset.asset_code == "USD"
    assert asset.precision == 2


def test_get_currency_rejects_unknown_currency():
    with pytest.raises(CurrencyNotRegisteredError):
        get_currency("EUR")


def test_get_currency_is_case_sensitive():
    # Registered codes are uppercase; lowercase is treated as unsupported.
    with pytest.raises(CurrencyNotRegisteredError):
        get_currency("usd")


def test_get_currency_rejects_non_string():
    with pytest.raises(CurrencyNotRegisteredError):
        get_currency(None)  # type: ignore[arg-type]


def test_get_currency_uses_injected_registry(extended_registry):
    assert get_currency("JPY", registry=extended_registry).precision == 0
    # JPY is in the injected registry but not the default one.
    with pytest.raises(CurrencyNotRegisteredError):
        get_currency("JPY")


# ── validate_precision ────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount", ["12.34", "0.01", "1000", "0", "12.3", "7"])
def test_validate_precision_accepts_within_precision(amount):
    result = validate_precision(amount, "USD")
    assert isinstance(result, Decimal)
    assert result == Decimal(amount)


def test_validate_precision_trailing_zeros_are_not_excess():
    # 12.340 == 12.34 in value, so it fits a 2dp currency.
    assert validate_precision("12.340", "USD") == Decimal("12.34")
    assert validate_precision(Decimal("12.3400"), "USD") == Decimal("12.34")


@pytest.mark.parametrize("amount", ["12.345", "0.001", "1.239999"])
def test_validate_precision_rejects_excess(amount):
    with pytest.raises(ExcessPrecisionError):
        validate_precision(amount, "USD")


def test_validate_precision_zero_decimal_currency(extended_registry):
    assert validate_precision("100", "JPY", registry=extended_registry) == Decimal("100")
    with pytest.raises(ExcessPrecisionError):
        validate_precision("100.5", "JPY", registry=extended_registry)


def test_validate_precision_six_decimal_currency(extended_registry):
    assert validate_precision("1.500000", "USDC", registry=extended_registry) == Decimal("1.5")
    with pytest.raises(ExcessPrecisionError):
        validate_precision("1.0000001", "USDC", registry=extended_registry)


def test_validate_precision_rejects_unknown_currency():
    with pytest.raises(CurrencyNotRegisteredError):
        validate_precision("1.00", "EUR")


def test_validate_precision_accepts_int_and_decimal_inputs():
    assert validate_precision(5, "USD") == Decimal("5")
    assert validate_precision(Decimal("5.00"), "USD") == Decimal("5")


def test_validate_precision_rejects_float():
    with pytest.raises(InvalidAmountError):
        validate_precision(12.34, "USD")  # type: ignore[arg-type]


def test_validate_precision_rejects_bool():
    with pytest.raises(InvalidAmountError):
        validate_precision(True, "USD")  # type: ignore[arg-type]


def test_validate_precision_rejects_non_numeric_string():
    with pytest.raises(InvalidAmountError):
        validate_precision("not-a-number", "USD")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_validate_precision_rejects_non_finite(amount):
    with pytest.raises(InvalidAmountError):
        validate_precision(amount, "USD")


# ── to_minor_units ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "amount, expected",
    [
        ("12.34", 1234),
        ("0.01", 1),
        ("0", 0),
        ("1000", 100000),
        ("12.30", 1230),
        ("12.3", 1230),
        ("-5.25", -525),
    ],
)
def test_to_minor_units_usd(amount, expected):
    assert to_minor_units(amount, "USD") == expected


def test_to_minor_units_accepts_decimal_and_int():
    assert to_minor_units(Decimal("12.34"), "USD") == 1234
    assert to_minor_units(7, "USD") == 700


def test_to_minor_units_zero_decimal_currency(extended_registry):
    assert to_minor_units("100", "JPY", registry=extended_registry) == 100


def test_to_minor_units_six_decimal_currency(extended_registry):
    assert to_minor_units("1.5", "USDC", registry=extended_registry) == 1_500_000
    assert to_minor_units("0.000001", "USDC", registry=extended_registry) == 1


def test_to_minor_units_rejects_excess_precision():
    with pytest.raises(ExcessPrecisionError):
        to_minor_units("12.345", "USD")


def test_to_minor_units_rejects_unknown_currency():
    with pytest.raises(CurrencyNotRegisteredError):
        to_minor_units("12.34", "EUR")


def test_to_minor_units_result_is_plain_int():
    result = to_minor_units("12.34", "USD")
    assert type(result) is int


# ── to_decimal ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "minor, expected",
    [
        (1234, "12.34"),
        (1, "0.01"),
        (0, "0.00"),
        (100000, "1000.00"),
        (1200, "12.00"),
        (-525, "-5.25"),
    ],
)
def test_to_decimal_usd(minor, expected):
    result = to_decimal(minor, "USD")
    assert result == Decimal(expected)
    # Result is quantized to the currency precision (exponent -2).
    assert result.as_tuple().exponent == -2


def test_to_decimal_zero_decimal_currency(extended_registry):
    result = to_decimal(100, "JPY", registry=extended_registry)
    assert result == Decimal("100")
    assert result.as_tuple().exponent == 0


def test_to_decimal_six_decimal_currency(extended_registry):
    assert to_decimal(1_500_000, "USDC", registry=extended_registry) == Decimal("1.500000")


def test_to_decimal_rejects_unknown_currency():
    with pytest.raises(CurrencyNotRegisteredError):
        to_decimal(1234, "EUR")


def test_to_decimal_rejects_non_integer():
    with pytest.raises(InvalidAmountError):
        to_decimal(12.34, "USD")  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        to_decimal(Decimal("1234"), "USD")  # type: ignore[arg-type]


def test_to_decimal_rejects_bool():
    with pytest.raises(InvalidAmountError):
        to_decimal(True, "USD")  # type: ignore[arg-type]


# ── round-trip properties ─────────────────────────────────────────────────────

@pytest.mark.parametrize("amount", ["12.34", "0.00", "1000.00", "0.01", "999999.99"])
def test_round_trip_decimal_to_minor_and_back(amount):
    minor = to_minor_units(amount, "USD")
    assert to_decimal(minor, "USD") == Decimal(amount)


@pytest.mark.parametrize("minor", [0, 1, 1234, 100000, -525])
def test_round_trip_minor_to_decimal_and_back(minor):
    amount = to_decimal(minor, "USD")
    assert to_minor_units(amount, "USD") == minor


def test_round_trip_across_assets(extended_registry):
    for code, amount in [("USD", "12.34"), ("JPY", "500"), ("USDC", "1.234567")]:
        minor = to_minor_units(amount, code, registry=extended_registry)
        assert to_decimal(minor, code, registry=extended_registry) == Decimal(amount)


# ── registry-driven guarantee ─────────────────────────────────────────────────

def test_precision_comes_from_registry_not_a_constant(extended_registry):
    """The same amount maps to different minor units purely because of registry precision."""
    assert to_minor_units("1", "USD", registry=extended_registry) == 100        # 2 dp
    assert to_minor_units("1", "JPY", registry=extended_registry) == 1          # 0 dp
    assert to_minor_units("1", "USDC", registry=extended_registry) == 1_000_000  # 6 dp
