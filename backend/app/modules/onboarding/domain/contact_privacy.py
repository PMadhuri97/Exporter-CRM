"""A contact's email address and date of birth, sealed in the columns they live in.

Companion to ``contact_phone``, which did the same for the phone number and explains
the shape in full. The short version: the column holds a ciphertext, a sealed value
announces itself by its first characters, and every read path checks before deciding
whether to decrypt.

Two fields, two ciphers, for one reason
---------------------------------------
**Email is compared**, so it is sealed deterministically (AES-SIV): the duplicate rule
asks whether this company already has a contact at this address, and a deterministic
seal is what lets identical addresses store identically. Determinism only works over a
canonical input, so the address is trimmed and lower-cased first — the comparison that
used to be ``lower(email) = lower(:wanted)`` at read time moves to write time, where
the plaintext is still visible.

**A date of birth is never compared**, so it gets the stronger cipher: AES-GCM with a
random nonce (``encrypt_field``), which leaks nothing at all — not even which two
people share a birthday. Deterministic encryption would leak that for no benefit.

This is the rule worth keeping as more columns follow: deterministic only where the
database has to match, random everywhere else.

What a date of birth becomes
----------------------------
``exporter_contact.date_of_birth`` was a ``date``. A ciphertext is text, so the column
becomes one, and the value sealed is the ISO form (``1983-07-14``) — the date's own
canonical spelling, so nothing is lost and it reads back as the same date.

The cost is that the database stops knowing it is a date: no ordering, no age
arithmetic, no range filter in SQL. Nothing did any of those (checked before the
change), and anything that needs to must do it after decrypting.
"""

from __future__ import annotations

from datetime import date

from app.platform.security.field_cipher import (
    decrypt_deterministic,
    decrypt_field,
    encrypt_deterministic,
    encrypt_field,
    is_deterministic_ciphertext,
    is_random_ciphertext,
)

#: Bound into each ciphertext as associated data, so a value sealed for one column
#: cannot be read as another's.
EMAIL_PURPOSE = "exporter_contact.email"
DATE_OF_BIRTH_PURPOSE = "exporter_contact.date_of_birth"


def normalise_email(value: str | None) -> str | None:
    """The canonical spelling of ``value``, or ``None`` when it holds nothing.

    Trimmed and lower-cased, which is exactly what the duplicate rule's
    ``func.lower(...) == email.strip().lower()`` did at read time. The domain part of
    an address is case-insensitive by specification and the local part is in every
    mail system anybody uses, so this loses nothing worth keeping.
    """
    if value is None:
        return None
    canonical = value.strip().lower()
    return canonical or None


def seal_email(value: str | None) -> str | None:
    """Normalise ``value`` and seal it deterministically, ready for the column.

    The only way an address should reach ``exporter_contact.email``. A value already
    sealed is passed through, so re-saving a contact whose email did not change cannot
    seal a ciphertext a second time.
    """
    if value is None:
        return None
    if is_deterministic_ciphertext(value):
        return value
    canonical = normalise_email(value)
    if canonical is None:
        return None
    return encrypt_deterministic(canonical, purpose=EMAIL_PURPOSE)


def open_email(stored: str | None) -> str | None:
    """The address behind a stored value.

    Tolerates one written before the column was sealed and returns it as it stands, so
    a read works whichever state a row is in.
    """
    if stored is None:
        return None
    if not is_deterministic_ciphertext(stored):
        return stored
    return decrypt_deterministic(stored, purpose=EMAIL_PURPOSE)


def seal_date_of_birth(value: date | str | None) -> str | None:
    """Seal a date of birth with a random nonce, ready for the column.

    Takes a ``date`` or its ISO string, because callers have both: the request body
    parses to a ``date``, while a value read back from the column is text.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return encrypt_field(value.isoformat(), purpose=DATE_OF_BIRTH_PURPOSE)
    if is_random_ciphertext(value):
        return value
    canonical = value.strip()
    if not canonical:
        return None
    return encrypt_field(canonical, purpose=DATE_OF_BIRTH_PURPOSE)


def open_date_of_birth(stored: str | None) -> str | None:
    """The ISO date behind a stored value, or a value written before the column was
    sealed, as it stands."""
    if stored is None:
        return None
    if not is_random_ciphertext(stored):
        return stored
    return decrypt_field(stored, purpose=DATE_OF_BIRTH_PURPOSE)


__all__ = [
    "DATE_OF_BIRTH_PURPOSE",
    "EMAIL_PURPOSE",
    "normalise_email",
    "open_date_of_birth",
    "open_email",
    "seal_date_of_birth",
    "seal_email",
]
