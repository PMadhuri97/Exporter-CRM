"""Resolve a sector's code in an external classification standard.

Separate from the risk lookup because it answers a different question for a
different consumer: regulatory reporting needs to know how a sector is *coded*
by a standards body, not how it is *rated* by a regulator.
"""

from dataclasses import dataclass
from datetime import date

import structlog

from app.modules.compliance.domain.policies.effectivity import is_effective_at
from app.modules.compliance.domain.ports import SectorRiskRepository

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SectorExternalCode:
    """A sector's code in one revision of one standard."""

    external_standard: str
    external_standard_version: str
    external_code: str


async def get_sector_external_code(
    sector_code: str,
    external_standard: str,
    as_of_date: date,
    repository: SectorRiskRepository,
) -> SectorExternalCode | None:
    """Return the code and revision for ``sector_code`` under ``external_standard``.

    The revision is returned alongside the code, never on its own. Standards
    reassign codes between revisions, so a report carrying "4649" without
    "ISIC Rev.4" cannot be interpreted by the regulator receiving it.

    ``None`` means no mapping is in force on ``as_of_date``. Unlike the risk
    lookup there is no defensible default — inventing a code for a regulatory
    filing is worse than filing without one — so the caller must decide.
    """
    sector_code = sector_code.strip().upper() if isinstance(sector_code, str) else sector_code
    external_standard = (
        external_standard.strip().upper()
        if isinstance(external_standard, str)
        else external_standard
    )

    if not sector_code or not external_standard or as_of_date is None:
        raise ValueError("sector_code, external_standard and as_of_date are all required")

    rows = await repository.list_external_mappings(sector_code, external_standard)
    in_force = [
        row for row in rows if is_effective_at(row.effective_from, row.effective_to, as_of_date)
    ]
    if not in_force:
        logger.warning(
            "sector_external_code_not_found",
            sector_code=sector_code,
            external_standard=external_standard,
            as_of_date=as_of_date.isoformat(),
        )
        return None

    if len(in_force) > 1:
        # Unreachable while ex_sector_code_external_mapping_period is in place.
        # Two revisions of one standard may both be mapped, but not two rows for
        # the same revision covering the same date.
        logger.warning(
            "sector_external_code_ambiguous",
            sector_code=sector_code,
            external_standard=external_standard,
            as_of_date=as_of_date.isoformat(),
            match_count=len(in_force),
        )

    mapping = max(in_force, key=lambda row: row.effective_from)
    return SectorExternalCode(
        external_standard=mapping.external_standard,
        external_standard_version=mapping.external_standard_version,
        external_code=mapping.external_code,
    )
