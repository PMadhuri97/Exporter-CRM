"""Which registration identifies a company, and which channel created it —
**owner: Developer 3** (allocation task 3.8, plan P4-1).

Pure: no I/O, no ORM. A company stopped being "an Indian exporter we went
looking for" when a buyer became a company record (plan §8), so two questions
now have to be answered on every create path, and answered the same way on all
of them:

* **Which registration identifies it?** A PAN for an Indian company, whatever
  its own jurisdiction issues for the rest (``CompanyIdentityType``). A foreign
  company must carry that number (decision IQ-7) — the one exception is a buyer
  the P4-6 migration created, which may have nothing but a name and a country,
  because the rule cannot be met retroactively.
* **Which channel created it?** ``created_via``. ``ExporterSource`` cannot
  answer this: it mixes "how we found them" (``REFERRAL``, ``EVENT``) with
  "which channel wrote the row" (``RXIL``), and a company entered by hand and
  one imported from a CSV can both be ``source=MANUAL``. Until now the channel
  was recoverable only from the first history row's ``event_metadata.source``
  (audit §3.1), which is why ``created_via_for_history_source`` derives it from
  exactly that string: the live path and migration 0033's backfill then agree by
  construction instead of by coincidence.

``created_via`` is a ``String(64)`` column rather than a database enum on
purpose — the next channel should not need a migration — so ``CreatedVia`` here
is the list, and nothing in the database enforces it.
"""

from __future__ import annotations

from enum import StrEnum

from app.modules.onboarding.domain.entities.exporter_enums import CompanyIdentityType
from app.shared.exceptions import ValidationError

#: Longest registration number the column holds (``String(100)``).
REGISTRATION_NUMBER_MAX = 100

#: Country whose companies are identified by a PAN rather than by a foreign
#: registration number. Not a general "domestic" flag: it is the one
#: jurisdiction whose identifier formats this CRM knows (`tax_identifiers.py`).
PAN_COUNTRY = "IN"


class CreatedVia(StrEnum):
    """The channel that created a company record (plan P4-1).

    Values are written to ``exporter_profile.created_via`` as plain text; see
    the module docstring for why the column is not a database enum.
    """

    MANUAL = "MANUAL"
    CSV = "CSV"
    RXIL = "RXIL"
    DEAL_BUYER = "DEAL_BUYER"
    SAMPLE = "SAMPLE"


#: ``history_source`` (the first history row's ``event_metadata.source``) → the
#: channel it means. Migration 0033 backfills ``created_via`` with the same
#: mapping expressed as SQL; change one and the other needs the same change.
#: An unknown source deliberately yields ``None`` rather than ``MANUAL``:
#: "entered by hand" is a claim about how a company reached us, and a channel
#: nobody has mapped is not evidence of it.
_HISTORY_SOURCE_CHANNELS: dict[str, CreatedVia] = {
    "exporter_profile_service.create_lead": CreatedVia.MANUAL,
    "exporter_profile_service.create_or_get_profile": CreatedVia.MANUAL,
    "company_import.csv": CreatedVia.CSV,
    "partner_intake.rxil": CreatedVia.RXIL,
    "company_directory.create_buyer_company": CreatedVia.DEAL_BUYER,
    "sample_data": CreatedVia.SAMPLE,
}


def created_via_for_history_source(history_source: str | None) -> CreatedVia | None:
    """The channel a ``history_source`` names, or ``None`` when unmapped."""
    if history_source is None:
        return None
    return _HISTORY_SOURCE_CHANNELS.get(history_source.strip())


def registration_key(registration_number: str) -> str:
    """The form ``uq_exporter_profile_country_registration_number`` compares:
    ASCII letters and digits only, upper-cased — the index's own
    ``upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))``.

    Mirrors that expression **exactly**. A lookup that normalised differently from
    the constraint would report "no such company" for a number the insert then
    refuses as a duplicate — ``KVK 12.345`` and ``kvk-12345`` are one registration,
    and a registrar's punctuation is presentation. It used to keep every Unicode
    letter and digit (``str.isalnum``), which the index drops, so a number written
    partly in another script matched nothing and then failed the insert (R-20).
    """
    return "".join(ch for ch in registration_number if ch.isascii() and ch.isalnum()).upper()


def normalise_registration_number(value: str | None) -> str | None:
    """A registration number as stored: surrounding whitespace removed, and
    ``None`` when blank.

    Stored as the registrar writes it — punctuation and case kept, unlike a PAN
    — because it is shown back to staff and printed on documents; only
    *comparison* normalises (`registration_key`). A value with no ASCII letter or
    digit is refused rather than stored, since it could never match anything.

    Raises:
        ValidationError: the value is longer than the column, or carries no
            letters or digits.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > REGISTRATION_NUMBER_MAX:
        raise ValidationError(
            f"registration_number must be at most {REGISTRATION_NUMBER_MAX} characters"
        )
    if not registration_key(cleaned):
        # Nothing the index compares: every such number would collide on the empty key.
        raise ValidationError(
            "registration_number must contain letters or digits (A-Z, 0-9): those are "
            "what identify it"
        )
    return cleaned


def is_pan_country(country: str | None) -> bool:
    """Whether a company in this country is identified by a PAN. An unknown
    country is **not** treated as India: the older unnamed create path leaves
    ``country`` empty, and defaulting it would claim an identity nobody stated.
    """
    return (country or "").strip().upper() == PAN_COUNTRY


def decide_identity_type(
    *, pan: str | None, registration_number: str | None
) -> CompanyIdentityType | None:
    """Which registration identifies this company, from what it actually holds.

    ``None`` when it holds neither, which is not a gap to be filled by guessing:
    deciding from the country alone would mark every migrated buyer in the
    Netherlands ``FOREIGN_REG`` while its ``registration_number`` stayed empty,
    and the completion list (IQ-7) would have nothing to work from. A PAN wins
    over a registration number, because a company holding a PAN is Indian
    however it reached us.
    """
    if pan:
        return CompanyIdentityType.IN_PAN
    if registration_number:
        return CompanyIdentityType.FOREIGN_REG
    return None


class IdentityGap(StrEnum):
    """What a company with no ``identity_type`` lacks (IQ-7's completion list, R-28)."""

    #: Outside India, holding neither a PAN nor a registration number. IQ-7 requires
    #: the number; only P4-6's migrated buyers were created without one.
    REGISTRATION_NUMBER = "REGISTRATION_NUMBER"
    #: Indian, with no PAN. Not required by a rule — a lead may start without one — but
    #: the company cannot be matched by identifier until it has one.
    PAN = "PAN"
    #: No country at all (the older unnamed create path), so nothing says which
    #: identifier it should carry.
    COUNTRY = "COUNTRY"


def identity_gap(country: str | None) -> IdentityGap:
    """For a company holding neither identifier: what completing it needs."""
    cleaned = (country or "").strip().upper()
    if not cleaned:
        return IdentityGap.COUNTRY
    return IdentityGap.PAN if is_pan_country(cleaned) else IdentityGap.REGISTRATION_NUMBER


def gap_is_required(gap: IdentityGap) -> bool:
    """Whether a CRM rule requires the gap to be closed — IQ-7 for a foreign company,
    and a country for any company — rather than it being worth doing."""
    return gap is not IdentityGap.PAN


def require_foreign_registration_number(
    *,
    country: str | None,
    pan: str | None,
    registration_number: str | None,
    allow_missing: bool = False,
) -> None:
    """Decision IQ-7: a foreign company carries a registration number.

    Checked only when the country says the company is foreign *and* it holds no
    PAN — a company with a PAN is Indian whatever its ``country`` column says,
    and a company with no country at all has not claimed to be either.

    Args:
        allow_missing: for the P4-6 buyer migration and the buyer-create path it
            feeds, where a buyer may be nothing but a name and a country
            (IQ-7's one exception). Those companies keep ``identity_type NULL``
            and appear on the completion list rather than being refused.

    Raises:
        ValidationError: a foreign company holding neither identifier.
    """
    if allow_missing or pan or registration_number:
        return
    if is_pan_country(country) or not (country or "").strip():
        return
    raise ValidationError(
        "registration_number is required for a company outside India: "
        "a foreign company is identified by the number its own registrar issued"
    )


__all__ = [
    "PAN_COUNTRY",
    "REGISTRATION_NUMBER_MAX",
    "CreatedVia",
    "created_via_for_history_source",
    "decide_identity_type",
    "is_pan_country",
    "normalise_registration_number",
    "registration_key",
    "require_foreign_registration_number",
]
