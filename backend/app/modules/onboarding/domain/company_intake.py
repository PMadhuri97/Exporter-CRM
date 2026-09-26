"""The internal contract for companies arriving from outside the CRM's own
screens — RXIL intake (L2-12) and bulk CSV import (L2-13). **Owner:
Developer 2.**

Every external format is translated into these shapes by its own adapter
(``infrastructure/rxil/company_package.py`` for RXIL, the CSV reader in
``application/company_import_service.py``), and nothing past the adapter knows
the external format existed. Company identity, matching, qualification and
the journey are the CRM's, applied the same way whatever the source.

``check_identity`` is the one place raw identity values become an
``IntakeIdentity``. It is built on the same normalisers manual creation uses
(``domain/tax_identifiers.py``), so a value the CRM refuses on its own screens
is refused here, and it reports every problem with a machine-readable code as
well as a message, so a bulk import can say exactly what is wrong with each
row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from app.modules.onboarding.domain.entities.qualification_enums import (
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
)
from app.modules.onboarding.domain.qualification_views import ResultEntry
from app.modules.onboarding.domain.tax_identifiers import (
    check_gstins_match_pan,
    embedded_pan,
    normalise_cin,
    normalise_country,
    normalise_gstins,
    normalise_iec,
    normalise_name,
    normalise_pan,
)
from app.shared.exceptions import ValidationError


@dataclass(frozen=True)
class Reason:
    """Why a row or package was refused, flagged or matched."""

    code: str
    message: str


@dataclass(frozen=True)
class IntakeIdentity:
    """A company's identity, normalised and checked."""

    name: str
    country: str
    pan: str | None = None
    gstins: tuple[str, ...] = ()
    iec: str | None = None
    cin: str | None = None

    @property
    def matching_pan(self) -> str | None:
        """The PAN to match on: the company's own, or — when it gave none —
        the one its GSTINs carry. Never written into ``pan``."""
        if self.pan is not None:
            return self.pan
        embedded = {embedded_pan(g) for g in self.gstins}
        return embedded.pop() if len(embedded) == 1 else None

    @property
    def has_identifier(self) -> bool:
        return any((self.pan, self.gstins, self.iec, self.cin))


def check_identity(
    *,
    name: str | None,
    country: str | None,
    pan: str | None = None,
    gstins: list[str] | tuple[str, ...] | None = None,
    iec: str | None = None,
    cin: str | None = None,
) -> tuple[IntakeIdentity | None, list[Reason]]:
    """Normalise and check raw identity values.

    Returns the identity and no reasons, or ``None`` and every reason it was
    refused — all of them, not just the first, so an operator can fix a row
    in one pass.
    """
    reasons: list[Reason] = []

    def attempt(code: str, fn, value):
        try:
            return fn(value)
        except ValidationError as exc:
            reasons.append(Reason(code, exc.detail))
            return None

    clean_name = None
    if name is None or not name.strip():
        reasons.append(Reason("MISSING_NAME", "name is required"))
    else:
        clean_name = attempt("INVALID_NAME", normalise_name, name)
    clean_country = None
    if country is None or not country.strip():
        reasons.append(Reason("MISSING_COUNTRY", "country is required"))
    else:
        clean_country = attempt("INVALID_COUNTRY", normalise_country, country)
    clean_pan = attempt("INVALID_PAN", normalise_pan, pan)
    clean_gstins = attempt("INVALID_GSTIN", normalise_gstins, list(gstins or ()))
    clean_iec = attempt("INVALID_IEC", normalise_iec, iec)
    clean_cin = attempt("INVALID_CIN", normalise_cin, cin)

    if clean_gstins:
        if clean_pan is not None:
            attempt("GSTIN_PAN_MISMATCH", lambda g: check_gstins_match_pan(clean_pan, g), clean_gstins)
        elif len({embedded_pan(g) for g in clean_gstins}) > 1:
            reasons.append(
                Reason(
                    "CONFLICTING_IDENTIFIERS",
                    "the GSTINs carry different PANs, so they cannot all belong to one company",
                )
            )

    if reasons:
        return None, reasons
    return (
        IntakeIdentity(
            name=clean_name,  # type: ignore[arg-type]
            country=clean_country,  # type: ignore[arg-type]
            pan=clean_pan,
            gstins=tuple(clean_gstins or ()),
            iec=clean_iec,
            cin=clean_cin,
        ),
        [],
    )


# ── Matching ──────────────────────────────────────────────────────────────────


class MatchKind(str, Enum):
    NEW = "NEW"  # no existing company shares an identifier
    MATCHED = "MATCHED"  # one company, confirmed by its PAN
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"  # shares identifiers, but no PAN confirms it
    CONFLICT = "CONFLICT"  # identifiers point at different companies, or disagree


@dataclass(frozen=True)
class CompanyMatch:
    kind: MatchKind
    customer_id: uuid.UUID | None = None
    candidates: tuple[uuid.UUID, ...] = ()
    reasons: tuple[Reason, ...] = ()
    #: Not a reason to stop — e.g. a GSTIN another company also holds.
    warnings: tuple[Reason, ...] = ()


# ── Partner intake (RXIL today) ───────────────────────────────────────────────


@dataclass(frozen=True)
class PartnerQualification:
    """The qualification a partner hands over — preserved exactly, never
    recomputed from the CRM's own criteria."""

    outcome: QualificationOutcomeValue
    #: Whether the partner's decision was a person's or a computer's, as the
    #: partner states it (criterion-result contract Q4).
    decided_by_kind: DecidedByKind = DecidedByKind.MANUAL
    #: Criterion-level results, each keeping the partner's own
    #: ``decided_by_kind``, evidence, reason and confidence.
    results: tuple[ResultEntry, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class PartnerCompanyIntake:
    """One company as a partner delivers it, in the CRM's own terms."""

    source: QualificationSource
    identity: IntakeIdentity
    qualification: PartnerQualification
    #: The partner's own id for this delivery, when its format carries one.
    #: Used to make a repeated delivery a no-op; never invented.
    external_reference: str | None = None
    industry: str | None = None
    website: str | None = None


__all__ = [
    "CompanyMatch",
    "IntakeIdentity",
    "MatchKind",
    "PartnerCompanyIntake",
    "PartnerQualification",
    "Reason",
    "check_identity",
]
