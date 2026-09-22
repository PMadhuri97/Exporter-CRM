"""Valuing a settlement in a threshold's currency — integers in, integers out.

A threshold comparison turns on the last minor unit, so what is asserted here is
not that conversion is roughly right but that it is exactly right: the scale on
each side comes from that asset's registered precision, the rounding is
half-to-even, and a float never touches the arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.compliance.application.threshold_conversion import (
    RateNotUsableError,
    convert_minor_units,
)
from app.shared.value_objects import AssetType, CurrencyAsset, CurrencyRegistry

#: EUR is not in the platform registry — the corridor is USD/USDC/INR — so a EUR
#: threshold is valued against a registry supplied for the test. Onboarding an
#: asset platform-wide is a ledger and settlement decision, not a compliance one.
REGISTRY_WITH_EUR = CurrencyRegistry(
    version="test-eur",
    assets={
        "USD": CurrencyAsset(
            asset_code="USD", asset_type=AssetType.FIAT, precision=2, minor_unit_name="cent"
        ),
        "EUR": CurrencyAsset(
            asset_code="EUR", asset_type=AssetType.FIAT, precision=2, minor_unit_name="cent"
        ),
    },
)


# ── the arithmetic ────────────────────────────────────────────────────────────


def test_a_rate_of_one_returns_the_same_amount_at_equal_precision():
    assert convert_minor_units(5_000_000, "USD", "INR", Decimal("1")) == 5_000_000


def test_usd_is_valued_in_inr():
    """USD 50,000.00 at 83 is INR 4,150,000.00."""
    assert convert_minor_units(5_000_000, "USD", "INR", Decimal("83")) == 415_000_000


def test_inr_is_valued_in_usd():
    """The inverse direction, so the helper is not only right one way round.

    INR 4,150,000.00 at 1/83 is USD 49,999.99999965, which rounds back to the
    USD 50,000.00 it came from rather than drifting a minor unit short."""
    assert convert_minor_units(415_000_000, "INR", "USD", Decimal("0.012048192771")) == 5_000_000


def test_usd_is_valued_in_eur():
    """EUR 46,000.00 for USD 50,000.00 at 0.92."""
    converted = convert_minor_units(
        5_000_000, "USD", "EUR", Decimal("0.92"), registry=REGISTRY_WITH_EUR
    )

    assert converted == 4_600_000


def test_precision_is_taken_from_each_asset_rather_than_assumed_equal():
    """USD holds two minor digits and USDC six. A conversion that carried the
    source scale across would be wrong by four orders of magnitude."""
    assert convert_minor_units(100, "USD", "USDC", Decimal("1")) == 1_000_000
    assert convert_minor_units(1_000_000, "USDC", "USD", Decimal("1")) == 100


def test_a_fractional_rate_is_applied_exactly():
    """0.01 USD at 83.25 is 0.8325 INR, which is 83.25 paisa."""
    assert convert_minor_units(1, "USD", "INR", Decimal("83.25")) == 83


# ── banker's rounding ─────────────────────────────────────────────────────────


def test_a_tie_rounds_to_the_even_minor_unit():
    """83.5 paisa rounds to 84 and 82.5 rounds to 82 — both to the even
    neighbour. Half-up would return 84 and 83, biasing every tie upward, and
    over many settlements that is a systematic drift in how many are reviewed."""
    assert convert_minor_units(1, "USD", "INR", Decimal("83.5")) == 84
    assert convert_minor_units(1, "USD", "INR", Decimal("82.5")) == 82


def test_rounding_is_not_truncation():
    """0.836 paisa is nearer 84 than 83 and must round rather than truncate."""
    assert convert_minor_units(1, "USD", "INR", Decimal("83.6")) == 84


def test_a_value_below_half_a_minor_unit_rounds_down():
    assert convert_minor_units(1, "USD", "INR", Decimal("83.4")) == 83


# ── floats ────────────────────────────────────────────────────────────────────


def test_a_float_rate_is_rejected():
    """A float cannot hold a rate exactly. Rejected at the boundary rather than
    silently absorbed, because the error it introduces is invisible until a
    comparison lands on the threshold."""
    with pytest.raises(RateNotUsableError, match="float"):
        convert_minor_units(5_000_000, "USD", "INR", 83.5)  # type: ignore[arg-type]


def test_an_integer_rate_is_accepted_as_an_exact_number():
    assert convert_minor_units(5_000_000, "USD", "INR", 83) == 415_000_000  # type: ignore[arg-type]


def test_a_non_finite_rate_is_rejected():
    with pytest.raises(RateNotUsableError):
        convert_minor_units(5_000_000, "USD", "INR", Decimal("NaN"))


def test_the_result_is_an_integer_number_of_minor_units():
    converted = convert_minor_units(1, "USD", "INR", Decimal("83.333333"))

    assert isinstance(converted, int)
    assert not isinstance(converted, bool)


# ── determinism ───────────────────────────────────────────────────────────────


def test_the_same_inputs_convert_the_same_way_every_time():
    args = (1_234_567, "USD", "INR", Decimal("83.176543"))

    assert len({convert_minor_units(*args) for _ in range(50)}) == 1


def test_an_unregistered_asset_is_rejected():
    """EUR is not in the platform registry. Valuing against it without saying so
    would invent a precision, and a wrong precision is a wrong threshold."""
    from app.shared.value_objects import CurrencyNotRegisteredError

    with pytest.raises(CurrencyNotRegisteredError):
        convert_minor_units(5_000_000, "USD", "EUR", Decimal("0.92"))
