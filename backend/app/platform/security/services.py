"""Cryptographic primitives shared across the platform.

ARCHITECTURE.md §8: "Webhook signature verification uses `platform/security/`.
Never roll bespoke crypto."
"""
from __future__ import annotations

import hashlib
import hmac


def sign_payload(raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 of the raw body, formatted per the X-Aner-Signature contract."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"hmac-sha256={digest}"
