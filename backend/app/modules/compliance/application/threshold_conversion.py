"""Value a settlement in the currency a rule's threshold is set in.

Money in, money out, integers at both ends. The settlement arrives as minor
units of the asset it is sent in and leaves as minor units of the threshold's
asset, because that is the only form in which the two can be compared without
carrying a scale around beside them.

Floats never appear. A rate held as a float is already wrong before it is used,
and a threshold comparison decides whether a payment is reviewed — landing one
minor unit either side of the boundary is the whole question.
"""

from decimal import Decimal

from app.shared.value_objects import (
    CURRENCY_REGISTRY,
    CurrencyRegistry,
    round_to_minor_units,
    to_decimal,
)


class RateNotUsableError(TypeError):
    """Raised when a rate is not an exact number."""


def convert_minor_units(
    amount_minor: int,
    from_asset_code: str,
    to_asset_code: str,
    rate: Decimal,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
) -> int:
    """Convert ``amount_minor`` of ``from_asset_code`` into ``to_asset_code``.

    ``rate`` is the value of one unit of ``from_asset_code`` in
    ``to_asset_code``, so the arithmetic is
    ``major_from × rate → major_to → minor_to``, the scale on either side coming
    from each asset's registered precision rather than being assumed equal. USD
    and INR both hold two, USDC holds six, and a conversion between them that
    assumed otherwise would be wrong by four orders of magnitude.

    The result is rounded half-to-even — banker's rounding — which is the
    platform's rounding everywhere money is scaled (``value_objects.ROUNDING``).
    Half-up would bias every rounded comparison towards the threshold, and over
    many settlements that is a systematic drift in how many get reviewed.

    ``registry`` is injectable on the same terms as the shared helpers this is
    built from, so a currency the platform has not onboarded can still be
    valued in a test without being registered platform-wide.
    """
    if isinstance(rate, float):
        raise RateNotUsableError(
            "rate must be a Decimal, not a float: a float cannot hold a rate "
            "exactly, and a threshold comparison turns on the last minor unit"
        )
    if not isinstance(rate, Decimal):
        rate = Decimal(rate)
    if not rate.is_finite():
        raise RateNotUsableError(f"rate must be a finite number, got {rate}")

    major_from = to_decimal(amount_minor, from_asset_code, registry=registry)
    return round_to_minor_units(major_from * rate, to_asset_code, registry=registry)
