from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from app.shared.value_objects.currency import (
    CURRENCY_REGISTRY,
    CurrencyAsset,
    CurrencyNotRegisteredError,
    CurrencyRegistry,
)

AmountLike = Decimal | int | str

ROUNDING = ROUND_HALF_EVEN


class InvalidAmountError(ValueError):
    """Raised when an amount cannot be interpreted as an exact decimal number."""


class ExcessPrecisionError(ValueError):
    """Raised when an amount has more decimal places than the asset permits."""


def get_currency(
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> CurrencyAsset:

    if not isinstance(asset_code, str):
        raise CurrencyNotRegisteredError(
            f"asset_code must be a string, got {type(asset_code).__name__}"
        )
    return registry.require(asset_code)


def validate_precision(
    amount: AmountLike,
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> Decimal:

    currency = get_currency(asset_code, registry=registry)
    value = _coerce_decimal(amount)
    if _fractional_digits(value) > currency.precision:
        raise ExcessPrecisionError(
            f"amount {value} has more than {currency.precision} decimal place(s) "
            f"allowed for {currency.asset_code}"
        )
    return value


def to_minor_units(
    amount: AmountLike,
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> int:

    currency = get_currency(asset_code, registry=registry)
    value = validate_precision(amount, asset_code, registry=registry)
    scaled = value * (10 ** currency.precision)

    return int(scaled.to_integral_value(rounding=ROUNDING))


def to_decimal(
    minor_units: int,
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> Decimal:

    if isinstance(minor_units, bool) or not isinstance(minor_units, int):
        raise InvalidAmountError(
            f"minor_units must be an int, got {type(minor_units).__name__}"
        )
    currency = get_currency(asset_code, registry=registry)
    quantum = _quantum(currency.precision)
    return Decimal(minor_units).scaleb(-currency.precision).quantize(quantum)


def round_to_minor_units(
    amount: AmountLike,
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> int:

    currency = get_currency(asset_code, registry=registry)
    value = _coerce_decimal(amount)
    scaled = value * (10 ** currency.precision)
    return int(scaled.to_integral_value(rounding=ROUNDING))


def round_to_asset_precision(
    amount: AmountLike,
    asset_code: str,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> Decimal:

    minor = round_to_minor_units(amount, asset_code, registry=registry)
    return to_decimal(minor, asset_code, registry=registry)


# ── internals ─────────────────────────────────────────────────────────────────

def _coerce_decimal(amount: AmountLike) -> Decimal:
    """Coerce a supported input to a finite Decimal; reject floats and junk."""
    if isinstance(amount, bool):
        raise InvalidAmountError("amount must not be a bool")
    if isinstance(amount, Decimal):
        value = amount
    elif isinstance(amount, int):
        value = Decimal(amount)
    elif isinstance(amount, str):
        try:
            value = Decimal(amount)
        except InvalidOperation:
            raise InvalidAmountError(f"amount {amount!r} is not a valid decimal string") from None
    else:
        raise InvalidAmountError(
            f"amount must be Decimal, int, or str; got {type(amount).__name__} "
            f"(floats are rejected because they cannot represent money exactly)"
        )
    if not value.is_finite():
        raise InvalidAmountError(f"amount must be a finite number, got {value}")
    return value


def _fractional_digits(value: Decimal) -> int:
    """Number of significant fractional digits, ignoring trailing zeros."""
    exponent = value.normalize().as_tuple().exponent
    # normalize() gives a positive/zero exponent for integers (e.g. 100 -> 1E+2).
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _quantum(precision: int) -> Decimal:
    """The Decimal step for a precision: 2 -> 0.01, 0 -> 1, 6 -> 0.000001."""
    return Decimal(1).scaleb(-precision)


__all__ = [
    "AmountLike",
    "ROUNDING",
    "InvalidAmountError",
    "ExcessPrecisionError",
    "CurrencyNotRegisteredError",
    "get_currency",
    "validate_precision",
    "to_minor_units",
    "to_decimal",
    "round_to_minor_units",
    "round_to_asset_precision",
]
