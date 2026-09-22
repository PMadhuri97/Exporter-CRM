"""Resolve which risk classification governs a sector for one payment.

The registry stores what each authority says; this module decides which of those
statements applies to one question asked on one date, and reports which
authority supplied the answer.
"""

from dataclasses import dataclass
from datetime import date

import structlog

from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    RiskTier,
)
from app.modules.compliance.domain.policies.effectivity import is_effective_at
from app.modules.compliance.domain.ports import SectorRiskRepository

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SectorRiskResolution:
    """The classification in force, and which authority issued it.

    ``matched`` is what separates "no authority rates this sector" from "an
    authority rates it ``standard``". Both carry the ``standard`` tier, and a
    caller that reads the tier alone cannot tell a deliberate baseline from an
    unknown sector — which for an AML control is the difference between a
    decision and a gap.
    """

    risk_tier: RiskTier
    classification_label: str | None
    jurisdiction_type: JurisdictionType | None
    jurisdiction_value: str | None
    matched: bool


#: The answer when no authority has rated the sector on this date. Carries no
#: jurisdiction because none applied, and ``matched=False`` so the caller can
#: escalate rather than treat it as a rating.
UNCLASSIFIED = SectorRiskResolution(
    risk_tier=RiskTier.STANDARD,
    classification_label=None,
    jurisdiction_type=None,
    jurisdiction_value=None,
    matched=False,
)


def _normalise(value: str | None) -> str | None:
    """Identifiers are matched with ``=`` against upper-cased stored values."""
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


async def is_sector_code_known(
    sector_code: str, as_of_date: date, repository: SectorRiskRepository
) -> bool:
    """True if ``sector_code`` is registered and in force on ``as_of_date``.

    Independent of risk classification: a sector nobody has rated is still
    ``known`` if it exists in the taxonomy. ``get_sector_risk_classification``'s
    ``matched`` flag cannot make that distinction — a code that was never
    registered and a registered code with no classification anywhere both
    return ``matched=False``. A caller that needs to reject an unrecognised
    sector code, rather than merely treat it as unrated, needs this instead.
    """
    normalised = _normalise(sector_code) or ""
    if not normalised or as_of_date is None:
        raise ValueError("sector_code and as_of_date are both required")

    sector = await repository.get_sector(normalised)
    return sector is not None and is_effective_at(
        sector.effective_from, sector.effective_to, as_of_date
    )


async def get_sector_risk_classification(
    sector_code: str,
    corridor_id: str | None,
    country_jurisdiction: str | None,
    as_of_date: date,
    repository: SectorRiskRepository,
) -> SectorRiskResolution:
    """Return the classification governing ``sector_code``, most specific first.

    Resolution order is the ``JurisdictionType`` ladder:

      1. a corridor classification for ``corridor_id``
      2. a country classification for ``country_jurisdiction``
      3. the FATF framework classification
      4. the ``standard`` baseline, with ``matched=False``

    A rule only applies if it is in force on ``as_of_date``; a lapsed corridor
    rule falls through to the country rule exactly as if it had never existed.
    Both ``corridor_id`` and ``country_jurisdiction`` are optional — a caller
    that knows neither still gets the international view.

    Effectivity is judged against ``as_of_date``, never today. Screening a
    payment backdated to before a regulator re-rated a sector must apply the
    rating in force when the money moved.

    The resolving authority is always returned. When a compliance officer asks
    why a settlement was flagged, "high risk" is not an answer — "FATF rates
    this sector DNFBP" is.

    A missing classification is an answer, not a failure: this never raises for
    an unknown sector or jurisdiction. It raises only on a malformed sector
    code or date, which is a caller bug rather than a regulatory fact.
    """
    sector_code = _normalise(sector_code) or ""
    corridor_id = _normalise(corridor_id)
    country_jurisdiction = _normalise(country_jurisdiction)

    if not sector_code or as_of_date is None:
        raise ValueError("sector_code and as_of_date are both required")

    if not await is_sector_code_known(sector_code, as_of_date, repository):
        # Reported as unmatched, not as a rating: the caller needs to know the
        # sector itself is unknown, which usually means a customer carries a
        # code that was never registered or has been retired.
        logger.warning(
            "sector_code_not_in_force",
            sector_code=sector_code,
            as_of_date=as_of_date.isoformat(),
        )
        return UNCLASSIFIED

    candidates: list[tuple[JurisdictionType, str]] = []
    if corridor_id:
        candidates.append((JurisdictionType.CORRIDOR, corridor_id))
    if country_jurisdiction:
        candidates.append((JurisdictionType.COUNTRY, country_jurisdiction))
    candidates.append((JurisdictionType.FRAMEWORK, FATF_FRAMEWORK))

    for jurisdiction_type, jurisdiction_value in candidates:
        resolution = await _classification_in_force(
            repository, sector_code, jurisdiction_type, jurisdiction_value, as_of_date
        )
        if resolution is not None:
            return resolution

    return UNCLASSIFIED


async def _classification_in_force(
    repository: SectorRiskRepository,
    sector_code: str,
    jurisdiction_type: JurisdictionType,
    jurisdiction_value: str,
    as_of_date: date,
) -> SectorRiskResolution | None:
    """The classification governing this authority on this date, if any."""
    rows = await repository.list_classifications(
        sector_code, jurisdiction_type, jurisdiction_value
    )
    in_force = [
        row for row in rows if is_effective_at(row.effective_from, row.effective_to, as_of_date)
    ]
    if not in_force:
        return None

    if len(in_force) > 1:
        # Unreachable while ex_sector_risk_classification_period is in place —
        # the exclusion constraint makes two rows for one authority in force on
        # one date impossible. Kept because the alternative to noticing that the
        # constraint has been dropped is silently picking a risk tier at random.
        logger.warning(
            "sector_classification_ambiguous",
            sector_code=sector_code,
            jurisdiction_type=jurisdiction_type.value,
            jurisdiction_value=jurisdiction_value,
            as_of_date=as_of_date.isoformat(),
            match_count=len(in_force),
        )

    governing = max(in_force, key=lambda row: row.effective_from)
    return SectorRiskResolution(
        risk_tier=governing.risk_tier,
        classification_label=governing.classification_label,
        jurisdiction_type=governing.jurisdiction_type,
        jurisdiction_value=governing.jurisdiction_value,
        matched=True,
    )
