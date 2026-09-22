"""``is_sector_code_known`` — existence, independent of risk classification.

``get_sector_risk_classification`` reports ``matched=False`` both for a sector
code that was never registered and for one that is registered but unrated —
by design, so a caller cannot reject the second case using ``matched`` alone.
This is the check a caller uses instead, when what it needs to know is
"does this sector code exist", not "how is it rated".
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.sector_risk_service import is_sector_code_known
from app.modules.compliance.tests.unit.test_sector_risk_lookup import (
    StubSectorRiskRepository,
    sector_row,
)

SECTOR = "PRECIOUS_STONES_TRADE"
EPOCH = date(2024, 1, 1)
AS_OF = date(2026, 8, 12)


async def test_registered_sector_is_known():
    repository = StubSectorRiskRepository([sector_row()], [])

    assert await is_sector_code_known(SECTOR, AS_OF, repository) is True


async def test_registered_but_unrated_sector_is_still_known():
    """The case ``matched`` cannot distinguish from "never registered"."""
    repository = StubSectorRiskRepository([sector_row()], [])

    assert await is_sector_code_known(SECTOR, AS_OF, repository) is True


async def test_never_registered_sector_is_unknown():
    repository = StubSectorRiskRepository([], [])

    assert await is_sector_code_known("NO_SUCH_SECTOR", AS_OF, repository) is False


async def test_retired_sector_is_unknown():
    repository = StubSectorRiskRepository(
        [sector_row(effective_to=date(2025, 1, 1))], []
    )

    assert await is_sector_code_known(SECTOR, AS_OF, repository) is False


async def test_sector_not_yet_effective_is_unknown():
    repository = StubSectorRiskRepository(
        [sector_row(effective_from=date(2027, 1, 1))], []
    )

    assert await is_sector_code_known(SECTOR, AS_OF, repository) is False


async def test_lower_case_sector_code_resolves():
    repository = StubSectorRiskRepository([sector_row()], [])

    assert await is_sector_code_known(SECTOR.lower(), AS_OF, repository) is True


@pytest.mark.parametrize("sector_code", ["", "   ", None])
async def test_missing_sector_code_is_rejected(sector_code):
    repository = StubSectorRiskRepository([sector_row()], [])

    with pytest.raises(ValueError):
        await is_sector_code_known(sector_code, AS_OF, repository)


async def test_missing_as_of_date_is_rejected():
    repository = StubSectorRiskRepository([sector_row()], [])

    with pytest.raises(ValueError):
        await is_sector_code_known(SECTOR, None, repository)
