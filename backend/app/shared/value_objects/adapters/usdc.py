"""USDC on-chain amount translation adapter.

Parses USDC amount formats (Circle payloads / on-chain values) into the canonical
major-unit Decimal, and back. No network calls — formats only. Scale comes from the
registry, never hardcoded.

Accepted inputs:
  - Circle amount object: {"amount": "100.50", "currency": "USD"|"USDC", "unit"?}
  - decimal major units: "100.50" / Decimal("100.50")
  - base units: 100500000 (int), "100500000", or {"amount": "100500000", "unit": "base"}

A bare int or all-digit string is base units; a value with a decimal point (or a
Decimal) is major units.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from app.shared.value_objects.currency import CurrencyAsset
from app.shared.value_objects.translation import ExternalAmount, TranslationAdapter

_ACCEPTED_CURRENCIES = frozenset({"USD", "USDC"})
_BASE_UNIT_ALIASES = frozenset({"base", "micro", "raw"})


class UsdcTranslationAdapter(TranslationAdapter):
    """USDC amount formats <-> canonical major-unit Decimal (registry-driven scale)."""

    def to_canonical(self, external_amount: ExternalAmount, asset: CurrencyAsset) -> Decimal:
        raw, unit = self._extract(external_amount)
        value = self._to_decimal(raw)
        if unit == "base":
            if value != value.to_integral_value():
                raise ValueError(
                    f"USDC base-unit amount must be a whole number, got {raw!r}"
                )
            return value.scaleb(-asset.precision)
        return value

    def from_canonical(self, amount: Decimal, asset: CurrencyAsset) -> int:
        # Canonical major-unit Decimal -> integer base units at registry precision.
        return int(amount.scaleb(asset.precision).to_integral_value())

    # ── internals ───────────────────────────────────────────────────────────────

    def _extract(self, external: ExternalAmount) -> tuple[object, str]:
        # Returns (raw_amount, unit) where unit is "base" or "major".
        if isinstance(external, Mapping):
            if "amount" not in external:
                raise ValueError("Circle USDC payload is missing an 'amount' field")
            currency = external.get("currency", external.get("asset"))
            if currency is not None and str(currency).upper() not in _ACCEPTED_CURRENCIES:
                raise ValueError(
                    f"USDC adapter received a non-USD/USDC payload currency {currency!r}"
                )
            raw = external["amount"]
            unit = external.get("unit")
            if unit is None:
                return raw, self._infer_unit(raw)
            unit = str(unit).lower()
            return raw, ("base" if unit in _BASE_UNIT_ALIASES else "major")
        return external, self._infer_unit(external)

    @staticmethod
    def _infer_unit(raw: object) -> str:
        if isinstance(raw, bool):
            raise ValueError("USDC amount must not be a bool")
        if isinstance(raw, int):
            return "base"
        if isinstance(raw, Decimal):
            return "major"
        if isinstance(raw, str):
            return "major" if "." in raw else "base"
        raise ValueError(
            f"unsupported USDC amount type {type(raw).__name__}; expected int, "
            f"str, Decimal, or a Circle amount object"
        )

    @staticmethod
    def _to_decimal(raw: object) -> Decimal:
        if isinstance(raw, bool):
            raise ValueError("USDC amount must not be a bool")
        if isinstance(raw, Decimal):
            value = raw
        elif isinstance(raw, int):
            value = Decimal(raw)
        elif isinstance(raw, str):
            try:
                value = Decimal(raw.strip())
            except InvalidOperation:
                raise ValueError(f"USDC amount {raw!r} is not a valid number") from None
        else:
            raise ValueError(f"unsupported USDC amount type {type(raw).__name__}")
        if not value.is_finite():
            raise ValueError(f"USDC amount must be finite, got {value}")
        return value


__all__ = ["UsdcTranslationAdapter"]
