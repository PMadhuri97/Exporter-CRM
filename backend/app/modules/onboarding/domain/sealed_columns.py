"""The onboarding columns sealed with AES-SIV, and what each is sealed for.

One place for the purposes, because a purpose is part of every ciphertext: a value
sealed for ``exporter_profile.pan`` only opens as ``exporter_profile.pan``, so renaming
one here would make every row written under the old name unreadable. Migration
``onboarding_0064_sealed_ids`` explains the change and its limits; the type
itself is ``app/platform/security/sealed_type.py``.

Identifiers are ``varchar(255)``; free text — an address line, a city, an email — is
``text``, because a sealed value grows with the plain value's bytes and a line written
in Devanagari is three bytes a character (``sealed_type.SEALED_WIDTH``).

A format, where a column has one, is the same rule its check constraint and the
service enforce (``tax_identifiers``): a value that fails it is written unsealed so the
constraint refuses it as before.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, and_, func, not_, or_, type_coerce

from app.modules.onboarding.domain.tax_identifiers import CIN_RE, GSTIN_RE, IEC_RE, PAN_RE
from app.platform.security.sealed_type import (
    KEYED_SQL,
    SealedJSON,
    SealedKeyedString,
    SealedString,
)

#: Eight digits — ``people._DIN`` and ``ck_exporter_contact_din``.
DIN_PATTERN = "^[0-9]{8}$"

# ── Identifiers ──────────────────────────────────────────────────────────────
CONTACT_DIN = SealedString("exporter_contact.din", pattern=DIN_PATTERN)
PROFILE_PAN = SealedString("exporter_profile.pan", pattern=PAN_RE.pattern)
PROFILE_CIN = SealedString("exporter_profile.cin", pattern=CIN_RE.pattern)
PROFILE_IEC = SealedString("exporter_profile.iec", pattern=IEC_RE.pattern)
GSTIN = SealedString("exporter_gstin.gstin", pattern=GSTIN_RE.pattern)


def _registration_key(value: str) -> str:
    # Imported here, not at the top: `company_identity` imports the entities package,
    # which imports `exporter_profile`, which imports this module.
    from app.modules.onboarding.domain.company_identity import registration_key

    return registration_key(value)


#: Shown as typed, compared normalised (``uq_exporter_profile_country_registration_*``):
#: ``<seal of registration_key(value)>|<seal of value>``, migration 0065.
PROFILE_REGISTRATION_NUMBER = SealedKeyedString(
    "exporter_profile.registration_number", normalise=_registration_key
)


def registration_number_matches(column: Any, registration_number: str) -> Any:
    """SQL true where ``column`` holds the same registration as ``registration_number``:
    letters and digits only, upper-cased, so ``KVK 12.345`` matches ``kvk-12345``.

    Two halves, one per index (migration 0065): a row written before sealing is
    compared as it always was, through
    ``upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))``, and a
    sealed row through the seal of its key.
    """
    plain = type_coerce(column, Text())
    wanted = _registration_key(registration_number)
    return or_(
        and_(
            not_(plain.op("~")(KEYED_SQL)),
            func.upper(func.regexp_replace(plain, "[^A-Za-z0-9]", "", "g")) == wanted,
        ),
        PROFILE_REGISTRATION_NUMBER.key_matches(column, registration_number),
    )


# ── A legacy deal buyer ──────────────────────────────────────────────────────
BUYER_TAX_ID = SealedString("deal_buyer.tax_id")
BUYER_REGISTRATION_NUMBER = SealedString("deal_buyer.registration_number")
BUYER_CONTACT_EMAIL = SealedString("deal_buyer.contact_email", length=None)
BUYER_CONTACT_PHONE = SealedString("deal_buyer.contact_phone")

# ── An address ───────────────────────────────────────────────────────────────
ADDRESS_LINE1 = SealedString("company_address.line1", length=None)
ADDRESS_LINE2 = SealedString("company_address.line2", length=None)
ADDRESS_CITY = SealedString("company_address.city", length=None)
ADDRESS_POSTAL_CODE = SealedString("company_address.postal_code")

# ── Copies of a buyer's identifiers ──────────────────────────────────────────
#: What a handed-over deal recorded about its buyer (``DealService._handover_snapshot``).
HANDOVER_SNAPSHOT = SealedJSON(
    "deal.handover_snapshot",
    paths=(
        ("buyer", "tax_id"),
        ("buyer", "registration_number"),
        ("buyer", "contact_email"),
        ("buyer", "contact_phone"),
    ),
    none_as_null=True,
)
#: What a BUYER check recorded about its subject (``VerificationService``).
SUBJECT_SNAPSHOT = SealedJSON(
    "verification_result.subject_snapshot",
    paths=(("tax_id",), ("registration_number",)),
)
