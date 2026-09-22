"""
Inbound webhook signature verification.

Sumsub signs each webhook with an HMAC of the raw request body using the
webhook secret, sending the hex digest in `X-Payload-Digest` and the algorithm
in `X-Payload-Digest-Alg` (e.g. `HMAC_SHA256_HEX`). We recompute the digest and
compare in constant time. This mirrors the outbound HMAC signing already used by
the notifications webhook provider — same primitive, opposite direction.
"""
from __future__ import annotations

import hashlib
import hmac

# Sumsub digest-algorithm header value → hashlib constructor.
_ALG_MAP = {
    "HMAC_SHA1_HEX": hashlib.sha1,
    "HMAC_SHA256_HEX": hashlib.sha256,
    "HMAC_SHA512_HEX": hashlib.sha512,
}


def compute_digest(raw_body: bytes, secret: str, alg: str | None = None) -> str:
    """Return the hex HMAC digest of the raw body for the given algorithm."""
    hash_ctor = _ALG_MAP.get((alg or "HMAC_SHA256_HEX").upper(), hashlib.sha256)
    return hmac.new(secret.encode("utf-8"), raw_body, hash_ctor).hexdigest()


def verify_signature(
    raw_body: bytes,
    provided_digest: str | None,
    secret: str,
    alg: str | None = None,
) -> bool:
    """Constant-time-compare the provided digest against the recomputed one."""
    if not provided_digest:
        return False
    expected = compute_digest(raw_body, secret, alg)
    return hmac.compare_digest(expected, provided_digest.strip())
