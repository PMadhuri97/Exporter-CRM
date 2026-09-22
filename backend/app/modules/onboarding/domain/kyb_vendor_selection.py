"""KYB vendor selection — value normalisation and the lookup result type (S1T4).

Pure domain helpers. No database, no I/O. The application service
(:mod:`app.modules.onboarding.application.kyb_vendor_registry_service`) uses
these to normalise inputs consistently and to express the outcome of
``get_vendor_for_country``.

Manual-review representation
---------------------------
When no registered vendor covers a country/entity-type combination, the lookup
returns a :class:`KybVendorLookupResult` with ``vendor is None``. Downstream, the
onboarding orchestration engine records that as a ``kyb_vendor_result`` row with
``normalised_result = KybNormalisedResult.REQUIRES_MANUAL_REVIEW`` (the existing
platform enum member for "a human must verify this") and hands the case to a
compliance officer via Epic 5.4. This module does not invent a second
manual-review token — :data:`MANUAL_REVIEW_NORMALISED_RESULT` is exactly that
existing member, re-exported for the caller's convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.modules.onboarding.domain.entities.orchestration_enums import KybNormalisedResult

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.kyb_vendor_registration import (
        KybVendorRegistration,
    )

#: The existing platform enum member that means "no automated vendor verified
#: this — a compliance officer must (Epic 5.4)". Reused, not reinvented.
MANUAL_REVIEW_NORMALISED_RESULT = KybNormalisedResult.REQUIRES_MANUAL_REVIEW


def normalise_country(value: str) -> str:
    """ISO 3166-1 alpha-2, trimmed and upper-cased — the form stored and matched.

    Consistent with the case-insensitive matching the onboarding document
    requirements policy already uses for country codes.
    """
    return value.strip().upper()


def normalise_country_list(values: list[str]) -> list[str]:
    """Normalise a list of country codes, dropping blanks and duplicates, order-stable."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        code = normalise_country(raw)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def normalise_entity_type(value: str) -> str:
    """Onboarding entity-type vocabulary form — trimmed and upper-cased."""
    return value.strip().upper()


def normalise_entity_type_list(values: list[str]) -> list[str]:
    """Normalise a list of entity types, dropping blanks and duplicates, order-stable."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        etype = normalise_entity_type(raw)
        if etype and etype not in seen:
            seen.add(etype)
            out.append(etype)
    return out


@dataclass(frozen=True)
class KybVendorLookupResult:
    """Outcome of resolving a KYB vendor for a registration country + entity type.

    Exactly one of two shapes:

    * a match — ``vendor`` is the selected :class:`KybVendorRegistration`;
    * manual review — ``vendor is None`` and ``reason`` explains why. The caller
      routes the case to a compliance officer (Epic 5.4) and records
      :data:`MANUAL_REVIEW_NORMALISED_RESULT`.
    """

    vendor: KybVendorRegistration | None
    reason: str | None = None

    @property
    def is_manual_review(self) -> bool:
        return self.vendor is None

    @classmethod
    def matched(cls, vendor: KybVendorRegistration) -> KybVendorLookupResult:
        return cls(vendor=vendor, reason=None)

    @classmethod
    def manual_review(cls, reason: str) -> KybVendorLookupResult:
        return cls(vendor=None, reason=reason)


__all__ = [
    "MANUAL_REVIEW_NORMALISED_RESULT",
    "KybVendorLookupResult",
    "normalise_country",
    "normalise_country_list",
    "normalise_entity_type",
    "normalise_entity_type_list",
]
