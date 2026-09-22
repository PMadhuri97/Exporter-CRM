"""PII-safe masking utilities for Trulioo adapter logging — Epic 4.1 / S2T2.

Every structured log event that could carry PII (entity names, registration
numbers, addresses, tax IDs) passes through :func:`mask_value` or
:func:`mask_entity_for_logging` so that production logs never contain raw
personally identifiable information.

The masking rules intentionally retain enough prefix characters for engineers
to correlate log entries across calls while ensuring the full value is never
recoverable from log storage.
"""
from __future__ import annotations

# Minimum visible prefix characters per field type.  These are intentionally
# short — enough for correlation, not enough for reconstruction.
_DEFAULT_PREFIX_LEN = 3
_SHORT_PREFIX_LEN = 2


def mask_value(value: str | None, *, prefix_len: int = _DEFAULT_PREFIX_LEN) -> str:
    """Return a PII-masked representation of *value* for logging.

    Keeps the first *prefix_len* characters visible and replaces the rest with
    asterisks.  ``None`` or empty strings are returned as ``"***"``.
    """
    if not value:
        return "***"
    visible = value[:prefix_len]
    return f"{visible}{'*' * max(len(value) - prefix_len, 3)}"


def mask_entity_for_logging(
    *,
    legal_name: str | None = None,
    registration_number: str | None = None,
    tax_id: str | None = None,
    address: str | None = None,
    country: str | None = None,
) -> dict[str, str]:
    """Return a dict of masked PII fields safe for structured logging.

    ``country`` is not PII and is passed through unchanged.
    """
    masked: dict[str, str] = {}
    if legal_name is not None:
        masked["legal_name"] = mask_value(legal_name, prefix_len=_SHORT_PREFIX_LEN)
    if registration_number is not None:
        masked["registration_number"] = mask_value(registration_number)
    if tax_id is not None:
        masked["tax_id"] = mask_value(tax_id, prefix_len=_SHORT_PREFIX_LEN)
    if address is not None:
        masked["address"] = mask_value(address, prefix_len=_SHORT_PREFIX_LEN)
    if country is not None:
        masked["country"] = country  # ISO country code — not PII
    return masked
