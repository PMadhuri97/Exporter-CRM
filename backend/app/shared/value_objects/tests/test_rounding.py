"""
Tests for the rounding policy (banker's rounding / ROUND_HALF_EVEN).

Two contracts are proven side by side:

  * The rounding path (round_to_minor_units / round_to_asset_precision) rounds to
    the asset grid with ROUND_HALF_EVEN — and does so ONLY at the decimal → integer
    boundary.
  * The strict path (validate_precision / to_minor_units) never rounds; it rejects
    any value whose precision exceeds the asset definition.

The required banker examples are demonstrated at two precisions:
  precision 0 (JPY): 0.5, 1.5, 2.5, 3.5
  precision 2 (USD): 10.25, 10.255, 10.245
"""
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest

from app.shared.value_objects import (
    ROUNDING,
    AssetType,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
    ExcessPrecisionError,
    InvalidAmountError,
    round_to_asset_precision,
    round_to_minor_units,
    to_decimal,
    to_minor_units,
    validate_precision,
)


@pytest.fixture(scope="module")
def registry() -> CurrencyRegistry:
    return CurrencyRegistry(
        version="test-rounding",
        assets={
            "USD": CurrencyAsset("USD", AssetType.FIAT, 2, "cent"),
            "JPY": CurrencyAsset("JPY", AssetType.FIAT, 0, "sen"),
            "USDC": CurrencyAsset("USDC", AssetType.STABLECOIN, 6, "micro-USDC"),
        },
    )


# ── the policy itself ─────────────────────────────────────────────────────────

def test_policy_is_round_half_even():
    assert ROUNDING is ROUND_HALF_EVEN


# ── required banker examples: precision 0 (round to integer) ──────────────────

@pytest.mark.parametrize(
    "amount, expected",
    [
        ("0.5", 0),   # ties to even -> 0
        ("1.5", 2),   # ties to even -> 2
        ("2.5", 2),   # ties to even -> 2  (HALF_UP would give 3)
        ("3.5", 4),   # ties to even -> 4
    ],
)
def test_banker_rounding_to_integer(registry, amount, expected):
    assert round_to_minor_units(amount, "JPY", registry=registry) == expected
    # JPY has 0 dp, so minor units == the rounded whole number.
    assert round_to_asset_precision(amount, "JPY", registry=registry) == Decimal(expected)


def test_ties_go_to_even_not_always_up(registry):
    """Contrast with ROUND_HALF_UP to make the half-even behaviour explicit."""
    amounts = [Decimal("0.5"), Decimal("1.5"), Decimal("2.5"), Decimal("3.5")]
    half_even = [round_to_minor_units(a, "JPY", registry=registry) for a in amounts]
    half_up = [int(a.to_integral_value(rounding=ROUND_HALF_UP)) for a in amounts]
    assert half_even == [0, 2, 2, 4]
    assert half_up == [1, 2, 3, 4]
    assert half_even != half_up


# ── required banker examples: precision 2 (round to cents) ────────────────────

@pytest.mark.parametrize(
    "amount, expected_minor, expected_decimal",
    [
        ("10.25", 1025, "10.25"),    # exact at 2 dp — no rounding needed
        ("10.255", 1026, "10.26"),   # tie at the mill: 5 preceding is odd -> up to even 6
        ("10.245", 1024, "10.24"),   # tie at the mill: 4 preceding is even -> stays
    ],
)
def test_banker_rounding_to_cents(registry, amount, expected_minor, expected_decimal):
    assert round_to_minor_units(amount, "USD", registry=registry) == expected_minor
    assert round_to_asset_precision(amount, "USD", registry=registry) == Decimal(expected_decimal)


# ── negative amounts round symmetrically to even ──────────────────────────────

@pytest.mark.parametrize(
    "amount, expected",
    [("-0.5", 0), ("-1.5", -2), ("-2.5", -2), ("-3.5", -4)],
)
def test_banker_rounding_negative(registry, amount, expected):
    assert round_to_minor_units(amount, "JPY", registry=registry) == expected


# ── rounding is asset-precision driven, at the 6dp grid too ───────────────────

@pytest.mark.parametrize(
    "amount, expected_minor",
    [
        ("1.0000005", 1_000_000),  # tie -> even (…0)
        ("1.0000015", 1_000_002),  # tie -> even (…2)
        ("1.0000025", 1_000_002),  # tie -> even (…2)
    ],
)
def test_banker_rounding_six_decimals(registry, amount, expected_minor):
    assert round_to_minor_units(amount, "USDC", registry=registry) == expected_minor


# ── rounding happens ONLY at decimal -> integer conversion ────────────────────

def test_rounding_path_accepts_excess_precision(registry):
    """The rounding path rounds sub-precision values instead of rejecting them."""
    assert round_to_minor_units("10.255", "USD", registry=registry) == 1026


def test_validate_precision_never_rounds(registry):
    """Precision validation rejects excess precision — it must not silently round."""
    with pytest.raises(ExcessPrecisionError):
        validate_precision("10.255", "USD", registry=registry)


def test_strict_to_minor_units_never_rounds(registry):
    """The strict conversion rejects excess precision rather than rounding it."""
    with pytest.raises(ExcessPrecisionError):
        to_minor_units("10.255", "USD", registry=registry)


def test_to_decimal_is_exact_no_rounding(registry):
    """integer -> decimal expansion is lossless; it introduces no rounding."""
    assert to_decimal(1025, "USD", registry=registry) == Decimal("10.25")
    assert to_decimal(1026, "USD", registry=registry) == Decimal("10.26")


def test_round_to_asset_precision_only_rounds_once(registry):
    """
    round_to_asset_precision must equal to_decimal(round_to_minor_units(...)):
    the sole rounding step is the decimal -> integer conversion; expanding back
    is exact.
    """
    for amount in ["10.25", "10.255", "10.245", "0.005", "0.015"]:
        minor = round_to_minor_units(amount, "USD", registry=registry)
        assert round_to_asset_precision(amount, "USD", registry=registry) == to_decimal(
            minor, "USD", registry=registry
        )


# ── rounding path still enforces the other guarantees ─────────────────────────

def test_rounding_rejects_unsupported_currency(registry):
    with pytest.raises(CurrencyNotRegisteredError):
        round_to_minor_units("10.25", "EUR", registry=registry)
    with pytest.raises(CurrencyNotRegisteredError):
        round_to_asset_precision("10.25", "EUR", registry=registry)


def test_rounding_rejects_float_and_non_finite(registry):
    with pytest.raises(InvalidAmountError):
        round_to_minor_units(10.25, "USD", registry=registry)  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        round_to_minor_units("NaN", "USD", registry=registry)


# ── whole-number and already-exact values are unchanged ───────────────────────

@pytest.mark.parametrize("amount, expected", [("12.34", 1234), ("100", 10000), ("0", 0)])
def test_exact_values_pass_through_rounding_unchanged(registry, amount, expected):
    assert round_to_minor_units(amount, "USD", registry=registry) == expected
