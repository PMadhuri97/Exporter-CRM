"""Field-level encryption for values that must never sit in the database as plain text
(a bank account number, an IBAN).

AES-256-GCM, with the column's name as associated data, so a ciphertext copied into
another column does not decrypt. A stored value reads ``v1.<key id>.<base64 nonce +
ciphertext>``: the key id lets keys rotate — new values use the first key in
``FIELD_ENCRYPTION_KEYS``, and every listed key still decrypts what it wrote.

``FIELD_ENCRYPTION_KEYS`` is ``<key id>:<base64 of 32 bytes>[,<key id>:<key>...]``
(generate a key with ``python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"``).
In a ``local`` or ``test`` environment with no keys set, a fixed development key is used
so the CRM works out of the box; anywhere else, encrypting or decrypting without a key
raises :class:`FieldEncryptionUnavailableError` (503), so nothing is ever stored
unencrypted.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.platform.configuration.config import get_settings
from app.shared.exceptions import AnerBaseException

_VERSION = "v1"
_NONCE_BYTES = 12

#: Marks a value sealed by :func:`encrypt_deterministic` rather than :func:`encrypt_field`.
#:
#: A separate marker, not a second ``v1``, because the two cannot be opened by the same
#: call: GCM carries its nonce, SIV derives one. A stored value has to say which it is,
#: or a column changing from one to the other becomes unreadable. No phone number or
#: identifier can begin ``d1.``, so this never collides with a value that was never
#: encrypted.
_DETERMINISTIC_VERSION = "d1"

#: Separates the SIV key from the GCM key derived from the same configured secret.
#:
#: One key must not drive two primitives. HKDF gives each its own, so the configured
#: ``FIELD_ENCRYPTION_KEYS`` entry stays a single 32-byte secret and nothing else about
#: key handling changes. 64 bytes because that is AES-SIV's 512-bit size, the one that
#: matches AES-256 for strength; a 32-byte SIV key would quietly be AES-128.
_SIV_INFO = b"aner-field-siv-v1"
_SIV_KEY_BYTES = 64
#: Where a missing key is tolerated, and a fixed development key stands in.
DEV_KEY_ENVIRONMENTS = frozenset({"local", "test", "testing"})
_DEV_KEY_ID = "dev"
_DEV_KEY = hashlib.sha256(b"aner-crm-local-field-encryption-key").digest()


class FieldEncryptionUnavailableError(AnerBaseException):
    """No encryption key is configured, so the value cannot be stored or read (503)."""

    def __init__(self) -> None:
        super().__init__(
            detail=(
                "Sensitive details cannot be stored or read: no field encryption key is "
                "configured (FIELD_ENCRYPTION_KEYS)"
            ),
            error_code="FIELD_ENCRYPTION_UNAVAILABLE",
            status_code=503,
        )


class FieldDecryptionError(AnerBaseException):
    """A stored value could not be decrypted with any configured key (500)."""

    def __init__(self, key_id: str) -> None:
        super().__init__(
            detail=f"A stored value could not be decrypted (key {key_id!r})",
            error_code="FIELD_DECRYPTION_FAILED",
            status_code=500,
        )


@dataclass(frozen=True)
class _Keys:
    current: str
    by_id: dict[str, bytes]


def _keys() -> _Keys:
    settings = get_settings()
    raw = (settings.FIELD_ENCRYPTION_KEYS or "").strip()
    by_id: dict[str, bytes] = {}
    order: list[str] = []
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        key_id, _, encoded = entry.partition(":")
        try:
            key = base64.b64decode(encoded, validate=True)
        except ValueError:
            key = b""
        if not key_id or len(key) != 32:
            raise ValueError("FIELD_ENCRYPTION_KEYS entries must be <key id>:<base64 of 32 bytes>")
        by_id[key_id] = key
        order.append(key_id)
    if order:
        return _Keys(order[0], by_id)
    if settings.ENVIRONMENT.strip().lower() in DEV_KEY_ENVIRONMENTS:
        return _Keys(_DEV_KEY_ID, {_DEV_KEY_ID: _DEV_KEY})
    raise FieldEncryptionUnavailableError()


def check_field_encryption_keys() -> bool:
    """Whether real keys are configured (start-up uses it to warn). Raises on a malformed
    setting, so a typo is found at start-up rather than on the first bank account."""
    try:
        keys = _keys()
    except FieldEncryptionUnavailableError:
        return False
    return keys.current != _DEV_KEY_ID


def encrypt_field(plaintext: str, *, purpose: str) -> str:
    """Encrypt ``plaintext`` for the column named by ``purpose``."""
    keys = _keys()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(keys.by_id[keys.current]).encrypt(
        nonce, plaintext.encode("utf-8"), purpose.encode("utf-8")
    )
    body = base64.b64encode(nonce + sealed).decode("ascii")
    return f"{_VERSION}.{keys.current}.{body}"


def decrypt_field(stored: str, *, purpose: str) -> str:
    """Decrypt a value :func:`encrypt_field` wrote for the same ``purpose``."""
    version, _, rest = stored.partition(".")
    key_id, _, body = rest.partition(".")
    if version != _VERSION or not key_id or not body:
        raise FieldDecryptionError(key_id or "?")
    keys = _keys()
    key = keys.by_id.get(key_id)
    if key is None:
        raise FieldDecryptionError(key_id)
    try:
        raw = base64.b64decode(body, validate=True)
        plain = AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode("utf-8"))
        return plain.decode("utf-8")
    except Exception as exc:  # a damaged value: bad base64, InvalidTag, not UTF-8
        raise FieldDecryptionError(key_id) from exc


def _siv_key(key: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=_SIV_KEY_BYTES, salt=None, info=_SIV_INFO
    ).derive(key)


def encrypt_deterministic(plaintext: str, *, purpose: str) -> str:
    """Encrypt ``plaintext`` so that the same input always gives the same output.

    AES-SIV (RFC 5297), for a column the database still has to compare: a unique
    constraint or an equality lookup needs identical values to store identically, which
    :func:`encrypt_field` deliberately prevents by drawing a fresh nonce each time.

    SIV derives its initialisation vector from the key, the plaintext and ``purpose``
    instead of taking a random one, so identical inputs land identically while different
    inputs never share a keystream. That is what makes it safe where a fixed nonce
    would be catastrophic: with GCM, two values sealed under one nonce leak the XOR of
    their plaintexts and the authentication subkey with them.

    The price is the one determinism always costs: equal values are visibly equal in the
    database. Anyone holding a dump learns which rows share a number without learning
    any number. Use :func:`encrypt_field` wherever the column is never compared — it
    gives up nothing in exchange for leaking nothing.

    ``purpose`` is authenticated, not encrypted, exactly as in :func:`encrypt_field`.
    """
    keys = _keys()
    sealed = AESSIV(_siv_key(keys.by_id[keys.current])).encrypt(
        plaintext.encode("utf-8"), [purpose.encode("utf-8")]
    )
    body = base64.b64encode(sealed).decode("ascii")
    return f"{_DETERMINISTIC_VERSION}.{keys.current}.{body}"


def decrypt_deterministic(stored: str, *, purpose: str) -> str:
    """Decrypt a value :func:`encrypt_deterministic` wrote for the same ``purpose``."""
    version, _, rest = stored.partition(".")
    key_id, _, body = rest.partition(".")
    if version != _DETERMINISTIC_VERSION or not key_id or not body:
        raise FieldDecryptionError(key_id or "?")
    keys = _keys()
    key = keys.by_id.get(key_id)
    if key is None:
        raise FieldDecryptionError(key_id)
    try:
        raw = base64.b64decode(body, validate=True)
        plain = AESSIV(_siv_key(key)).decrypt(raw, [purpose.encode("utf-8")])
        return plain.decode("utf-8")
    except Exception as exc:  # a damaged value: bad base64, InvalidTag, not UTF-8
        raise FieldDecryptionError(key_id) from exc


def is_deterministic_ciphertext(value: str | None) -> bool:
    """Whether ``value`` was written by :func:`encrypt_deterministic`.

    What lets a column hold both the converted and the not-yet-converted during a
    migration, and what a read path uses to tell a sealed value from one typed in before
    the column was encrypted.
    """
    return bool(value) and value.startswith(f"{_DETERMINISTIC_VERSION}.")


__all__ = [
    "DEV_KEY_ENVIRONMENTS",
    "FieldDecryptionError",
    "FieldEncryptionUnavailableError",
    "check_field_encryption_keys",
    "decrypt_deterministic",
    "decrypt_field",
    "encrypt_deterministic",
    "encrypt_field",
    "is_deterministic_ciphertext",
]
