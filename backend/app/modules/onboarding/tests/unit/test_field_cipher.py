"""Field encryption: a value round-trips, is bound to its column, survives a key
rotation, and is never stored without a key outside local and test."""

from __future__ import annotations

import base64

import pytest

from app.platform.configuration.config import get_settings
from app.platform.security.field_cipher import (
    FieldDecryptionError,
    FieldEncryptionUnavailableError,
    decrypt_field,
    encrypt_field,
)

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch):
    def use(value: str, environment: str = "production") -> None:
        monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", value)
        monkeypatch.setattr(get_settings(), "ENVIRONMENT", environment)

    return use


def test_a_value_round_trips_and_is_not_stored_in_clear(keys):
    keys(f"a:{KEY_A}")
    stored = encrypt_field("50200012345678", purpose="bank.number")

    assert "50200012345678" not in stored
    assert stored.startswith("v1.a.")
    assert decrypt_field(stored, purpose="bank.number") == "50200012345678"
    assert encrypt_field("50200012345678", purpose="bank.number") != stored, "a fresh nonce each time"


def test_a_value_is_bound_to_its_column(keys):
    keys(f"a:{KEY_A}")
    stored = encrypt_field("50200012345678", purpose="bank.number")
    with pytest.raises(FieldDecryptionError):
        decrypt_field(stored, purpose="bank.iban")


def test_a_rotated_key_still_reads_what_the_old_one_wrote(keys):
    keys(f"a:{KEY_A}")
    old = encrypt_field("x", purpose="p")
    keys(f"b:{KEY_B},a:{KEY_A}")

    assert decrypt_field(old, purpose="p") == "x"
    assert encrypt_field("x", purpose="p").startswith("v1.b.")


def test_without_a_key_nothing_is_stored_outside_local_and_test(keys):
    keys("", environment="production")
    with pytest.raises(FieldEncryptionUnavailableError):
        encrypt_field("x", purpose="p")
    keys("", environment="local")
    assert decrypt_field(encrypt_field("x", purpose="p"), purpose="p") == "x"


def test_a_malformed_key_is_refused(keys):
    keys("a:short")
    with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEYS"):
        encrypt_field("x", purpose="p")
