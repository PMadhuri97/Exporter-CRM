"""A company's identifiers — name, country and the Indian tax IDs:
normalising and checking them (L2-03, L2-06).

**Owner: Developer 2.** Pure functions — no I/O — so the service, the sample
data and later the bulk import (L2-13) all apply the same rules
(``docs/contracts/company-record.md`` §4). The database repeats each format
check as a ``CHECK`` constraint (migration 0014), so a value that skips the
service is still refused.

Normalising means: surrounding whitespace removed, letters upper-cased. An
empty or whitespace-only value normalises to ``None`` ("not given").
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.shared.exceptions import ValidationError

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
IEC_RE = re.compile(r"^[A-Z0-9]{10}$")
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")


def _normalise(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def normalise_name(value: str | None) -> str | None:
    """A company name with surrounding whitespace removed; blank is refused."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError("name must not be blank")
    if len(cleaned) > 255:
        raise ValidationError("name must be at most 255 characters")
    return cleaned


def normalise_country(value: str | None) -> str | None:
    """An ISO 3166-1 alpha-2 country code, upper-cased (`IN`)."""
    country = _normalise(value)
    if country is not None and not COUNTRY_RE.match(country):
        raise ValidationError("country must be a two-letter ISO 3166-1 code, e.g. IN")
    return country


def normalise_pan(value: str | None) -> str | None:
    """A PAN, normalised and checked: 5 letters, 4 digits, 1 letter."""
    pan = _normalise(value)
    if pan is not None and not PAN_RE.match(pan):
        raise ValidationError("pan must be 10 characters: 5 letters, 4 digits, 1 letter")
    return pan


def normalise_iec(value: str | None) -> str | None:
    """An importer-exporter code, normalised and checked: 10 letters or digits."""
    iec = _normalise(value)
    if iec is not None and not IEC_RE.match(iec):
        raise ValidationError("iec must be 10 letters or digits")
    return iec


def normalise_cin(value: str | None) -> str | None:
    """A company registration number, normalised and checked (21 characters)."""
    cin = _normalise(value)
    if cin is not None and not CIN_RE.match(cin):
        raise ValidationError(
            "cin must be 21 characters: L or U, 5 digits, 2-letter state, "
            "4-digit year, 3 letters, 6 digits"
        )
    return cin


def normalise_gstins(values: Iterable[str] | None) -> list[str]:
    """A company's GSTINs, each normalised and checked, in the order given.

    Blank entries are dropped. The same GSTIN twice is refused: one company
    holds each registration once.
    """
    gstins: list[str] = []
    for value in values or ():
        gstin = _normalise(value)
        if gstin is None:
            continue
        if not GSTIN_RE.match(gstin):
            raise ValidationError(
                f"gstin {gstin!r} must be 15 characters: 2-digit state code, the "
                "10-character PAN, 1 entity character, Z, 1 check character"
            )
        if gstin in gstins:
            raise ValidationError(f"gstin {gstin!r} is listed twice")
        gstins.append(gstin)
    return gstins


def embedded_pan(gstin: str) -> str:
    """The PAN a GSTIN carries in characters 3 to 12."""
    return gstin[2:12]


def check_gstins_match_pan(pan: str | None, gstins: Iterable[str]) -> None:
    """Every GSTIN must embed the company's PAN, when the company has one.

    With no PAN, the GSTINs must still all embed the *same* PAN: GSTINs
    carrying two PANs cannot belong to one company (bulk import and RXIL
    intake refuse them too, as ``CONFLICTING_IDENTIFIERS``). The embedded PAN
    is used for duplicate matching only, and is never written into ``pan``.
    """
    if pan is None:
        embedded = sorted({embedded_pan(gstin) for gstin in gstins})
        if len(embedded) > 1:
            raise ValidationError(
                "these GSTINs carry different PANs "
                f"({', '.join(embedded)}), so they cannot all belong to one company"
            )
        return
    mismatched = [gstin for gstin in gstins if embedded_pan(gstin) != pan]
    if mismatched:
        raise ValidationError(
            f"gstin {mismatched[0]!r} does not contain this company's PAN "
            "(characters 3 to 12 of a GSTIN are the PAN)"
        )


__all__ = [
    "CIN_RE",
    "COUNTRY_RE",
    "GSTIN_RE",
    "IEC_RE",
    "PAN_RE",
    "check_gstins_match_pan",
    "embedded_pan",
    "normalise_cin",
    "normalise_country",
    "normalise_gstins",
    "normalise_iec",
    "normalise_name",
    "normalise_pan",
]
