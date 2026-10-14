"""A company's people: contacts, directors and beneficial owners on one row each.

``exporter_contact`` holds every person at a company, with roles (migration 0057). The
rules here are the database's CHECKs said once more in words, so a request that breaks
one is refused with a sentence (422) instead of reaching the database as a 500:

* a person has at least one role;
* only a contact can be the primary contact;
* a DIN belongs to a director, an ownership share and a control type to a beneficial
  owner;
* a DIN is eight digits, an ownership share is between 0 and 100, and a country is two
  capital letters.

Taking a role away clears the fields that belong only to it (``ROLE_FIELDS``), so a
former director keeps no DIN and a former owner no share; the history row names the
role change.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.modules.onboarding.domain.entities.exporter_contact import (
    CONTROL_TYPES,
    IDENTIFICATION_TYPES,
    ExporterContact,
)
from app.shared.exceptions import ValidationError

CONTACT = "CONTACT"
DIRECTOR = "DIRECTOR"
UBO = "UBO"

#: Role name -> the column that holds it.
ROLE_COLUMNS: dict[str, str] = {CONTACT: "is_contact", DIRECTOR: "is_director", UBO: "is_ubo"}

#: The fields only one role may carry, cleared when that role is taken away.
ROLE_FIELDS: dict[str, tuple[str, ...]] = {
    DIRECTOR: ("din",),
    UBO: ("ownership_pct", "control_type"),
}

#: The associated data a person's identification number is sealed with
#: (``platform/security/field_cipher``).
IDENTIFICATION_PURPOSE = "exporter_contact.identification_number"

#: The person fields a request may set, besides the roles and the identification number.
PERSON_FIELDS = (
    "date_of_birth",
    "nationality",
    "residence_country",
    "din",
    "ownership_pct",
    "control_type",
    "identification_type",
)

_DIN = re.compile(r"^[0-9]{8}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")


def roles_of(person: ExporterContact) -> list[str]:
    """The person's roles, in a fixed order."""
    return [role for role, column in ROLE_COLUMNS.items() if getattr(person, column)]


def is_person_of_interest(person: ExporterContact) -> bool:
    """A director or beneficial owner: someone the sanctions screening covers."""
    return bool(person.is_director or person.is_ubo)


def clear_fields_of_removed_roles(person: ExporterContact) -> None:
    for role, fields in ROLE_FIELDS.items():
        if not getattr(person, ROLE_COLUMNS[role]):
            for name in fields:
                setattr(person, name, None)


def check_person(person: ExporterContact) -> None:
    """Refuse a person the database would refuse, with the reason in words."""
    if not roles_of(person):
        raise ValidationError("A person needs at least one role: contact, director or beneficial owner")
    if person.is_primary_contact and not person.is_contact:
        raise ValidationError("Only a contact can be the primary contact")
    if person.din is not None:
        if not person.is_director:
            raise ValidationError("A DIN belongs to a director")
        if not _DIN.match(person.din):
            raise ValidationError("A DIN is eight digits")
    if person.ownership_pct is not None:
        if not person.is_ubo:
            raise ValidationError("An ownership share belongs to a beneficial owner")
        if not Decimal(0) <= Decimal(person.ownership_pct) <= Decimal(100):
            raise ValidationError("An ownership share is between 0 and 100")
    if person.control_type is not None:
        if not person.is_ubo:
            raise ValidationError("A control type belongs to a beneficial owner")
        if person.control_type not in CONTROL_TYPES:
            raise ValidationError(f"Control type must be one of {', '.join(CONTROL_TYPES)}")
    for name in ("nationality", "residence_country"):
        value = getattr(person, name)
        if value is not None and not _COUNTRY.match(value):
            raise ValidationError(f"{name.replace('_', ' ').capitalize()} is a two-letter country code")
    if person.identification_type is not None and person.identification_type not in IDENTIFICATION_TYPES:
        raise ValidationError(
            f"Identification type must be one of {', '.join(IDENTIFICATION_TYPES)}"
        )
    if (person.identification_type is None) != (person.identification_encrypted is None):
        raise ValidationError("An identification number needs its type, and a type its number")


__all__ = [
    "CONTACT",
    "DIRECTOR",
    "IDENTIFICATION_PURPOSE",
    "PERSON_FIELDS",
    "ROLE_COLUMNS",
    "ROLE_FIELDS",
    "UBO",
    "check_person",
    "clear_fields_of_removed_roles",
    "is_person_of_interest",
    "roles_of",
]
