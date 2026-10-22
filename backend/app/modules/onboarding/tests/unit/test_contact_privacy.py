"""A contact's email and date of birth: the canonical form, and the two ciphers.

Email is compared, so it is sealed deterministically over a canonical address. A date
of birth is not, so it gets a random nonce and leaks nothing — not even a shared
birthday. That difference is the point of this module and most of this file.
"""

from __future__ import annotations

import base64
from datetime import date

import pytest

from app.modules.onboarding.domain.contact_privacy import (
    DATE_OF_BIRTH_PURPOSE,
    EMAIL_PURPOSE,
    normalise_email,
    open_date_of_birth,
    open_email,
    seal_date_of_birth,
    seal_email,
)
from app.platform.configuration.config import get_settings
from app.platform.security.field_cipher import (
    FieldDecryptionError,
    decrypt_field,
    is_deterministic_ciphertext,
    is_random_ciphertext,
)

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"a:{KEY_A}")
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")


# ── Email: canonical, then deterministic ─────────────────────────────────────


@pytest.mark.parametrize(
    "typed",
    ["jane@acme.example", "Jane@Acme.Example", "  jane@acme.example  ", "JANE@ACME.EXAMPLE"],
)
def test_one_address_spelled_four_ways_is_one_address(typed: str):
    assert normalise_email(typed) == "jane@acme.example"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_empty_address_is_nothing(value: str | None):
    assert normalise_email(value) is None
    assert seal_email(value) is None


def test_the_same_address_however_typed_seals_identically():
    """What a duplicate check on this column rests on."""
    assert seal_email("Jane@Acme.Example") == seal_email("  jane@acme.example ")


def test_two_addresses_at_one_domain_do_not_collide():
    assert seal_email("jane@acme.example") != seal_email("john@acme.example")


def test_a_sealed_address_opens_back_to_its_canonical_form():
    sealed = seal_email("  Jane@Acme.Example ")
    assert is_deterministic_ciphertext(sealed)
    assert open_email(sealed) == "jane@acme.example"


def test_sealing_an_already_sealed_address_leaves_it_alone():
    once = seal_email("jane@acme.example")
    assert seal_email(once) == once


def test_an_address_from_before_the_column_was_sealed_still_reads():
    assert open_email("jane@acme.example") == "jane@acme.example"


# ── Date of birth: random, and therefore not comparable ──────────────────────


def test_a_date_of_birth_seals_differently_every_time():
    """The whole reason it uses the other cipher. Deterministic sealing would put
    "these two people share a birthday" in the dump for no benefit, because nothing
    compares this column."""
    first = seal_date_of_birth(date(1983, 7, 14))
    second = seal_date_of_birth(date(1983, 7, 14))

    assert first != second
    assert is_random_ciphertext(first)
    assert open_date_of_birth(first) == open_date_of_birth(second) == "1983-07-14"


def test_a_date_seals_the_same_whether_given_as_a_date_or_its_iso_text():
    """Callers have both: a request body parses to a `date`, a value read back from
    the column is text."""
    assert open_date_of_birth(seal_date_of_birth(date(1983, 7, 14))) == "1983-07-14"
    assert open_date_of_birth(seal_date_of_birth("1983-07-14")) == "1983-07-14"


def test_sealing_an_already_sealed_date_leaves_it_alone():
    once = seal_date_of_birth(date(1983, 7, 14))
    assert seal_date_of_birth(once) == once


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_date_stores_nothing(value: str | None):
    assert seal_date_of_birth(value) is None


def test_a_date_from_before_the_column_was_sealed_still_reads():
    assert open_date_of_birth("1983-07-14") == "1983-07-14"


# ── Each column's seal is its own ────────────────────────────────────────────


def test_an_email_cannot_be_read_as_another_column():
    sealed = seal_email("jane@acme.example")
    with pytest.raises(FieldDecryptionError):
        open_date_of_birth(sealed.replace("d1.", "v1.", 1))


def test_a_date_of_birth_cannot_be_read_as_another_column():
    sealed = seal_date_of_birth(date(1983, 7, 14))
    with pytest.raises(FieldDecryptionError):
        decrypt_field(sealed, purpose=EMAIL_PURPOSE)


def test_the_two_ciphers_are_told_apart_by_their_own_marks():
    """What lets one column hold sealed and unsealed values at once, and what stops a
    value sealed one way being opened the other."""
    assert is_deterministic_ciphertext(seal_email("jane@acme.example"))
    assert not is_random_ciphertext(seal_email("jane@acme.example"))
    assert is_random_ciphertext(seal_date_of_birth(date(1983, 7, 14)))
    assert not is_deterministic_ciphertext(seal_date_of_birth(date(1983, 7, 14)))


def test_a_value_whose_key_is_gone_refuses_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    sealed_email = seal_email("jane@acme.example")
    sealed_dob = seal_date_of_birth(date(1983, 7, 14))
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"b:{KEY_B}")

    with pytest.raises(FieldDecryptionError):
        open_email(sealed_email)
    with pytest.raises(FieldDecryptionError):
        open_date_of_birth(sealed_dob)


def test_the_purposes_are_distinct():
    assert EMAIL_PURPOSE != DATE_OF_BIRTH_PURPOSE
