"""Utilities and constants for idempotency key format validation and reference generation."""

MAX_CUSTOMER_KEY_LENGTH = 64
MAX_INTERNAL_KEY_LENGTH = 256
MAX_RAIL_REF_LENGTH = 64

KNOWN_RAIL_CODES = frozenset({
    "ACH",
    "WIRE",
    "RTP",
    "FEDNOW",
    "SWIFT",
    "CARD",
    "BOOK",
})

RAIL_REF_PREFIX = "ANER"
