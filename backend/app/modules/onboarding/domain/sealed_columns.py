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

from app.modules.onboarding.domain.tax_identifiers import CIN_RE, GSTIN_RE, IEC_RE, PAN_RE
from app.platform.security.sealed_type import SealedJSON, SealedString

#: Eight digits — ``people._DIN`` and ``ck_exporter_contact_din``.
DIN_PATTERN = "^[0-9]{8}$"

# ── Identifiers ──────────────────────────────────────────────────────────────
CONTACT_DIN = SealedString("exporter_contact.din", pattern=DIN_PATTERN)
PROFILE_PAN = SealedString("exporter_profile.pan", pattern=PAN_RE.pattern)
PROFILE_CIN = SealedString("exporter_profile.cin", pattern=CIN_RE.pattern)
PROFILE_IEC = SealedString("exporter_profile.iec", pattern=IEC_RE.pattern)
GSTIN = SealedString("exporter_gstin.gstin", pattern=GSTIN_RE.pattern)

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
