"""The phone number's canonical spelling, and the deterministic seal over it.

The normalisation is what makes the encryption useful: a deterministic cipher matches
byte-identical inputs only, so the same line typed three ways has to arrive here as
one string before it is sealed.
"""

from __future__ import annotations

import base64

import pytest

from app.modules.onboarding.domain.contact_phone import (
    PHONE_PURPOSE,
    normalise_phone,
    open_phone,
    seal_phone,
)
from app.platform.configuration.config import get_settings
from app.platform.security.field_cipher import (
    FieldDecryptionError,
    decrypt_deterministic,
    encrypt_deterministic,
    is_deterministic_ciphertext,
)

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"a:{KEY_A}")
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")


# ── The canonical spelling ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "typed",
    ["+91 98765 43210", "09876543210", "9876543210", "919876543210", "+91-98765-43210"],
)
def test_one_line_spelled_five_ways_is_one_number(typed: str):
    """The whole point: these five reach the column as the same string, so the
    duplicate rule can compare them with plain equality."""
    assert normalise_phone(typed) == "+919876543210"


def test_two_cities_sharing_an_ending_stay_two_numbers():
    """The rule this replaced matched by suffix, which called these one line and
    refused the second as a duplicate. They are a Bangalore number and a Chennai one."""
    assert normalise_phone("080 2234 5678") != normalise_phone("044 2234 5678")


def test_a_number_that_says_its_country_is_believed():
    assert normalise_phone("+1 415 555 0132") == "+14155550132"
    assert normalise_phone("+44 20 7946 0958") == "+442079460958"


def test_an_extension_keeps_its_digits_and_gains_no_country_code():
    """Too short to be a line. Guessing a country code for it would invent a number."""
    assert normalise_phone("2345678") == "2345678"


@pytest.mark.parametrize("value", [None, "", "   ", "abc", "---"])
def test_nothing_dialable_is_nothing(value: str | None):
    assert normalise_phone(value) is None


# ── Sealing ──────────────────────────────────────────────────────────────────


def test_a_sealed_number_opens_back_to_its_canonical_form():
    sealed = seal_phone("+91 98765 43210")
    assert is_deterministic_ciphertext(sealed)
    assert open_phone(sealed) == "+919876543210"


def test_the_same_line_seals_identically_however_it_was_typed():
    """What `UNIQUE` and equality matching rest on. `encrypt_field` would give three
    different values here, which is why this column is not sealed with it."""
    assert seal_phone("+91 98765 43210") == seal_phone("09876543210") == seal_phone("9876543210")


def test_two_different_numbers_do_not_collide():
    assert seal_phone("9876543210") != seal_phone("9876543211")


def test_sealing_an_already_sealed_value_leaves_it_alone():
    """A contact saved again without touching its phone must not seal the ciphertext
    a second time — that would store something no key could open to a number."""
    once = seal_phone("9876543210")
    assert seal_phone(once) == once


def test_a_value_from_before_the_column_was_sealed_still_reads():
    """What lets a read work while the backfill is mid-flight."""
    assert open_phone("098 7654 3210") == "098 7654 3210"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_nothing_to_seal_stores_nothing(value: str | None):
    assert seal_phone(value) is None


# ── The guarantees the cipher itself carries ─────────────────────────────────


def test_a_phone_ciphertext_cannot_be_read_as_another_column():
    """The column name is authenticated, so a value moved to another column fails
    rather than decrypting into the wrong field."""
    sealed = seal_phone("9876543210")
    with pytest.raises(FieldDecryptionError):
        decrypt_deterministic(sealed, purpose="exporter_contact.email")


def test_the_siv_key_is_not_the_gcm_key():
    """Derived with HKDF, so one configured secret never drives two primitives. If
    they were the same key the two ciphertexts would share their key id and material;
    this asserts the deterministic one cannot be opened as a GCM value."""
    from app.platform.security.field_cipher import decrypt_field

    sealed = encrypt_deterministic("9876543210", purpose=PHONE_PURPOSE)
    with pytest.raises(FieldDecryptionError):
        decrypt_field(sealed, purpose=PHONE_PURPOSE)


def test_a_value_written_under_an_older_key_still_opens(monkeypatch: pytest.MonkeyPatch):
    """Rotation: the new key writes, the old one still reads what it wrote."""
    sealed = seal_phone("9876543210")
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"b:{KEY_B},a:{KEY_A}")

    assert open_phone(sealed) == "+919876543210"
    # And the new key is the one writing now, so the same number stores differently
    # than it did before the rotation — which is why a rotation must be all-or-nothing
    # while this column carries a unique constraint.
    assert seal_phone("9876543210") != sealed


def test_a_value_whose_key_is_gone_refuses_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    sealed = seal_phone("9876543210")
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"b:{KEY_B}")

    with pytest.raises(FieldDecryptionError):
        open_phone(sealed)
