"""A contact's phone number: one canonical spelling, then encrypted.

Why a canonical spelling at all
-------------------------------
``exporter_contact.phone`` holds a deterministic ciphertext, so two rows match only
when their *stored* values are byte-identical. The number as typed is not: the same
line arrives as ``+91 98765 43210``, ``09876543210`` and ``9876543210`` depending on
who entered it. Encrypt those three as they came and they are three different
ciphertexts, which is the same as not matching at all.

So the number is normalised **before** it is sealed, and what the column holds is the
canonical form of the line rather than the characters somebody typed. The comparison
the database used to do at read time — strip the punctuation, drop a trunk zero,
compare the endings — moves to write time, where it can still see the plaintext.

The canonical form
------------------
``+`` followed by digits, country code included, which is E.164 without the length
rules::

    +91 98765 43210  ──▶  +919876543210
    09876543210      ──▶  +919876543210
    9876543210       ──▶  +919876543210
    +1 415 555 0132  ──▶  +14155550132

Reached by: keep the digits (and a leading ``+``); a number that came with ``+`` or
with a country code is already international; a bare national number gets
``DEFAULT_COUNTRY_CODE`` in front, after one trunk ``0`` is dropped.

**The country code is an assumption, and it is the one to challenge.** This CRM's
companies are Indian exporters, so a bare 10-digit number is read as Indian. A bare
number that is not Indian normalises wrongly, and because the result is what gets
stored, that is not recoverable by a later read.

What this is not
----------------
Not a phone-number library. ``phonenumbers`` (libphonenumber) knows every country's
length and prefix rules and is what this should become if numbers outside India start
arriving in quantity. The rule here is deliberately small and written down, so that
what it does and does not do is legible.

It also does not reproduce one thing the old SQL comparison did: a 7-digit fragment
such as ``2345678`` used to match the full number ``9872345678`` by suffix. It no
longer does. That drops a class of false duplicates — two different lines sharing an
ending were called the same number — but it is a behaviour change, not only a fix.
"""

from __future__ import annotations

from app.platform.security.field_cipher import (
    decrypt_deterministic,
    encrypt_deterministic,
    is_deterministic_ciphertext,
)

#: Bound into the ciphertext as associated data, so a phone number sealed here cannot
#: be read as any other column's value.
PHONE_PURPOSE = "exporter_contact.phone"

#: Prefixed to a national number that arrives without a country code. India: the
#: companies on this CRM are Indian exporters (see the module docstring's caveat).
DEFAULT_COUNTRY_CODE = "91"

#: How many digits a national Indian number has, trunk zero excluded.
NATIONAL_NUMBER_DIGITS = 10

#: Below this, a value is an extension or a fragment rather than a line, and is kept
#: as its digits with no country code invented for it.
SIGNIFICANT_DIGITS = 7


def normalise_phone(value: str | None) -> str | None:
    """The canonical spelling of ``value``, or ``None`` when it holds no digits.

    Deterministic by construction: the same line in any spelling returns the same
    string, which is what makes the encrypted column comparable.
    """
    if value is None:
        return None

    raw = value.strip()
    international = raw.startswith("+")
    digits = "".join(character for character in raw if character.isdigit())
    if not digits:
        return None

    if international:
        # It said which country it belongs to; believe it.
        return f"+{digits}"

    if digits.startswith("0"):
        # A trunk prefix is a domestic dialling convention, not part of the number.
        digits = digits.lstrip("0")
        if not digits:
            return None

    if len(digits) == NATIONAL_NUMBER_DIGITS:
        return f"+{DEFAULT_COUNTRY_CODE}{digits}"

    if digits.startswith(DEFAULT_COUNTRY_CODE) and (
        len(digits) == len(DEFAULT_COUNTRY_CODE) + NATIONAL_NUMBER_DIGITS
    ):
        # Already carried its country code, just without the `+`.
        return f"+{digits}"

    if len(digits) < SIGNIFICANT_DIGITS:
        # An extension. Kept whole and marked as not a line, so it is never mistaken
        # for a national number that a country code should be guessed for.
        return digits

    # Longer or shorter than a national number and not recognisably Indian: kept as
    # its digits rather than guessed at. Two identical such numbers still match each
    # other, which is all the column promises.
    return f"+{digits}" if len(digits) > NATIONAL_NUMBER_DIGITS else digits


def seal_phone(value: str | None) -> str | None:
    """Normalise ``value`` and encrypt it, ready for the column.

    The only way a phone number should reach ``exporter_contact.phone``. Normalising
    here rather than at each call site is what keeps the determinism honest: a caller
    that sealed the raw string would store a value nothing else could match.

    A value already sealed is passed through, so re-saving a contact whose phone was
    not among the fields that changed does not encrypt the ciphertext a second time.
    """
    if value is None:
        return None
    if is_deterministic_ciphertext(value):
        return value
    canonical = normalise_phone(value)
    if canonical is None:
        return None
    return encrypt_deterministic(canonical, purpose=PHONE_PURPOSE)


def open_phone(stored: str | None) -> str | None:
    """The canonical number behind a stored value.

    Tolerates a value written before the column was encrypted and returns it as it
    stands, so a read works while a backfill is still running. Everything sealed says
    so in its own first characters, which is what makes that distinction possible.
    """
    if stored is None:
        return None
    if not is_deterministic_ciphertext(stored):
        return stored
    return decrypt_deterministic(stored, purpose=PHONE_PURPOSE)


__all__ = [
    "DEFAULT_COUNTRY_CODE",
    "PHONE_PURPOSE",
    "open_phone",
    "seal_phone",
    "NATIONAL_NUMBER_DIGITS",
    "SIGNIFICANT_DIGITS",
    "normalise_phone",
]
