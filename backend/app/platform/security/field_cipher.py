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

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.platform.configuration.config import get_settings
from app.shared.exceptions import AnerBaseException

_VERSION = "v1"
_NONCE_BYTES = 12
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
    raw = base64.b64decode(body)
    try:
        plain = AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode("utf-8"))
    except Exception as exc:  # cryptography raises InvalidTag
        raise FieldDecryptionError(key_id) from exc
    return plain.decode("utf-8")


__all__ = [
    "DEV_KEY_ENVIRONMENTS",
    "FieldDecryptionError",
    "FieldEncryptionUnavailableError",
    "check_field_encryption_keys",
    "decrypt_field",
    "encrypt_field",
]
