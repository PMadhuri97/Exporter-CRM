"""Resolving a sector's code in an external classification standard.

The revision is the point of this suite. A code without the revision that
produced it is ambiguous, and the consumer is regulatory reporting — the one
place where filing an unqualified or invented value has consequences outside the
platform.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.sector_external_code_service import (
    get_sector_external_code,
)
from app.modules.compliance.domain.entities.sector_registry import SectorCodeExternalMapping
from app.modules.compliance.tests.unit.test_sector_risk_lookup import (
    SECTOR,
    StubSectorRiskRepository,
    sector_row,
)

EPOCH = date(2024, 1, 1)
AS_OF = date(2026, 8, 12)


def mapping_row(
    external_standard: str,
    external_standard_version: str,
    external_code: str,
    *,
    sector_code: str = SECTOR,
    effective_from: date = EPOCH,
    effective_to: date | None = None,
) -> SectorCodeExternalMapping:
    return SectorCodeExternalMapping(
        sector_code=sector_code,
        external_standard=external_standard,
        external_standard_version=external_standard_version,
        external_code=external_code,
        effective_from=effective_from,
        effective_to=effective_to,
    )


@pytest.fixture
def repository() -> StubSectorRiskRepository:
    """One sector coded under three standards at once."""
    return StubSectorRiskRepository(
        [sector_row()],
        [],
        [
            mapping_row("ISIC", "ISIC Rev.4", "4649"),
            mapping_row("NIC", "NIC-2008", "46693"),
            mapping_row("NACE", "NACE Rev.2", "46.72"),
        ],
    )


async def test_returns_the_code_and_its_standard_version(repository):
    """AC6. The revision travels with the code, always."""
    result = await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository)

    assert result is not None
    assert result.external_code == "4649"
    assert result.external_standard_version == "ISIC Rev.4"
    assert result.external_standard == "ISIC"


async def test_each_standard_resolves_independently(repository):
    """The failure the old ``isic_code`` column made unavoidable: one sector
    needs an ISIC code for one regulator and a NIC code for another."""
    isic = await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository)
    nic = await get_sector_external_code(SECTOR, "NIC", AS_OF, repository)

    assert isic is not None and isic.external_code == "4649"
    assert nic is not None and nic.external_code == "46693"


async def test_a_new_standard_resolves_without_code_changes(repository):
    """AC5. NACE appears nowhere in the implementation — adding a standard is a
    seed-data row."""
    result = await get_sector_external_code(SECTOR, "NACE", AS_OF, repository)

    assert result is not None
    assert result.external_code == "46.72"
    assert result.external_standard_version == "NACE Rev.2"


async def test_unmapped_standard_returns_none(repository):
    """No default is invented. Filing a guessed code with a regulator is worse
    than filing none, so the caller has to decide what to do about it."""
    assert await get_sector_external_code(SECTOR, "NAICS", AS_OF, repository) is None


async def test_unknown_sector_returns_none(repository):
    assert await get_sector_external_code("NO_SUCH", "ISIC", AS_OF, repository) is None


async def test_superseded_revision_is_not_returned():
    """A standard revised mid-history. Reporting for a date before the revision
    must carry the code that was published then."""
    repository = StubSectorRiskRepository(
        [sector_row(effective_from=date(2020, 1, 1))],
        [],
        [
            mapping_row(
                "ISIC", "ISIC Rev.3", "5190",
                effective_from=date(2020, 1, 1), effective_to=EPOCH,
            ),
            mapping_row("ISIC", "ISIC Rev.4", "4649"),
        ],
    )

    historical = await get_sector_external_code(SECTOR, "ISIC", date(2022, 6, 1), repository)
    current = await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository)

    assert historical is not None
    assert historical.external_code == "5190"
    assert historical.external_standard_version == "ISIC Rev.3"
    assert current is not None
    assert current.external_code == "4649"
    assert current.external_standard_version == "ISIC Rev.4"


async def test_expired_mapping_returns_none():
    repository = StubSectorRiskRepository(
        [sector_row()],
        [],
        [mapping_row("ISIC", "ISIC Rev.4", "4649", effective_to=date(2025, 1, 1))],
    )

    assert await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository) is None


async def test_mapping_is_not_effective_on_its_end_date():
    """Half-open, matching the exclusion constraint's '[)' bound."""
    end = date(2025, 1, 1)
    repository = StubSectorRiskRepository(
        [sector_row()], [], [mapping_row("ISIC", "ISIC Rev.4", "4649", effective_to=end)]
    )

    assert await get_sector_external_code(SECTOR, "ISIC", end, repository) is None


async def test_lower_case_standard_resolves(repository):
    result = await get_sector_external_code(SECTOR.lower(), "isic", AS_OF, repository)

    assert result is not None
    assert result.external_code == "4649"


async def test_result_is_immutable(repository):
    result = await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository)

    with pytest.raises(AttributeError):
        result.external_code = "0000"


@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_missing_sector_code_is_rejected(repository, blank):
    with pytest.raises(ValueError):
        await get_sector_external_code(blank, "ISIC", AS_OF, repository)


@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_missing_standard_is_rejected(repository, blank):
    with pytest.raises(ValueError):
        await get_sector_external_code(SECTOR, blank, AS_OF, repository)
