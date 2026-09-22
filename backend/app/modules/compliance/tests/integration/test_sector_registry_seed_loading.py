"""Sector registry acceptance criteria against a real database.

Covers the seed loader and the SQLAlchemy repository end to end: YAML on disk to
three tables to both lookup services. The decision logic is covered branch by
branch in tests/unit against an in-memory repository; what only a database can
prove is here — that the loader writes rows the repository can read back, that
two Postgres enums round trip as domain enums, and that effectivity survives
Postgres date columns.

## Why this suite restores the seed data

``load_sector_registry`` truncates all three tables and re-inserts. There is no
per-test transaction rollback in this codebase (see backend/conftest.py) — tests
commit against a shared Postgres. Pointing the loader at a tmp_path fixture
therefore replaces the real GitOps reference data for the rest of the run.

The module-scoped fixture below reloads the real GitOps directory on teardown
and asserts the restore worked. Teardown runs even when a test fails, so a
broken assertion cannot strand the fake data either.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.compliance.application.sector_external_code_service import (
    get_sector_external_code,
)
from app.modules.compliance.application.sector_risk_service import (
    get_sector_risk_classification,
)
from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    RiskTier,
    SectorCodeExternalMapping,
    SectorCodeRegistry,
    SectorRiskClassification,
)
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    SEED_DATA_DIR,
    load_sector_registry,
)
from app.modules.compliance.infrastructure.sector_risk_repository import (
    SQLAlchemySectorRiskRepository,
)

# Imported as a module, not `from ... import AsyncSessionLocal`: the session-scoped
# autouse fixture in backend/conftest.py rebinds that attribute to a NullPool
# sessionmaker, and a name bound at import time would keep the pooled original.
from app.platform.database import services as database

SECTOR = "PRECIOUS_STONES_TRADE"
AS_OF = date(2026, 8, 12)

FIXTURE_SECTORS = [SECTOR, "RETIRED_SECTOR", "UNRATED_SECTOR", "LOWERCASE_SECTOR"]

SECTORS_YAML = """
# Predates its classifications: a sector must be in force for the whole span its
# ratings cover, or a backdated query resolves to the baseline because the
# sector did not yet exist rather than because nothing rated it.
- sector_code: PRECIOUS_STONES_TRADE
  description: "Wholesale trade in diamonds, precious metals, and gemstones"
  effective_from: 2020-01-01
- sector_code: RETIRED_SECTOR
  description: "Retired sector"
  effective_from: 2020-01-01
  effective_to: 2024-01-01
- sector_code: UNRATED_SECTOR
  description: "Registered but never classified"
  effective_from: 2020-01-01
- sector_code: lowercase_sector
  description: "Written in lower case on purpose"
  effective_from: 2020-01-01
"""

MAPPINGS_YAML = """
- sector_code: PRECIOUS_STONES_TRADE
  external_standard: ISIC
  external_standard_version: "ISIC Rev.4"
  external_code: "4649"
  effective_from: 2024-01-01
# A superseded revision, closed the day Rev.4 begins.
- sector_code: PRECIOUS_STONES_TRADE
  external_standard: ISIC
  external_standard_version: "ISIC Rev.3"
  external_code: "5190"
  effective_from: 2020-01-01
  effective_to: 2024-01-01
- sector_code: PRECIOUS_STONES_TRADE
  external_standard: nace
  external_standard_version: "NACE Rev.2"
  external_code: "46.72"
  effective_from: 2020-01-01
"""

CLASSIFICATIONS_YAML = """
- sector_code: PRECIOUS_STONES_TRADE
  jurisdiction_type: framework
  jurisdiction_value: FATF
  risk_tier: high
  classification_label: DNFBP
  notes: "FATF Recommendation 22"
  effective_from: 2020-01-01
- sector_code: PRECIOUS_STONES_TRADE
  jurisdiction_type: country
  jurisdiction_value: AE_CBUAE
  risk_tier: elevated
  classification_label: DPMS
  notes: "Test country tier"
  effective_from: 2020-01-01
- sector_code: PRECIOUS_STONES_TRADE
  jurisdiction_type: corridor
  jurisdiction_value: US_IN
  risk_tier: critical
  notes: "Test corridor tier, no label published"
  effective_from: 2020-01-01
- sector_code: PRECIOUS_STONES_TRADE
  jurisdiction_type: country
  jurisdiction_value: EXPIRED_REGIME
  risk_tier: critical
  classification_label: STALE
  notes: "Lapsed local rating"
  effective_from: 2020-01-01
  effective_to: 2024-01-01
- sector_code: lowercase_sector
  jurisdiction_type: framework
  jurisdiction_value: fatf
  risk_tier: high
  classification_label: DNFBP
  notes: "Identifiers written in lower case on purpose"
  effective_from: 2020-01-01
"""


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory):
    """The fixture registry on disk, in the layout the loader expects."""
    path = tmp_path_factory.mktemp("sectors")
    (path / "sector-codes.yaml").write_text(SECTORS_YAML)
    (path / "external-mappings.yaml").write_text(MAPPINGS_YAML)
    (path / "risk-classifications.yaml").write_text(CLASSIFICATIONS_YAML)
    return path


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_registry(seed_dir):
    """Install the fixture registry for this module, then restore the real one.

    Module-scoped because the load is a full rewrite of three tables and the
    tests only read. Each session is opened and closed inside this fixture
    rather than held across the ``yield``: fixtures and tests run on different
    event loops here, and an asyncpg connection cannot be used from a loop other
    than the one that created it.
    """
    async with database.AsyncSessionLocal() as session:
        await load_sector_registry(session, seed_dir)

    try:
        yield seed_dir
    finally:
        async with database.AsyncSessionLocal() as session:
            await load_sector_registry(session, SEED_DATA_DIR)

            restored = await session.execute(
                select(SectorCodeRegistry.sector_code).where(
                    SectorCodeRegistry.sector_code == SECTOR
                )
            )
            assert restored.scalar_one_or_none() == SECTOR, (
                "GitOps seed data was not restored; the shared test database is "
                "still holding this suite's fixture sectors"
            )

            leaked = await session.execute(
                select(SectorCodeRegistry.sector_code).where(
                    SectorCodeRegistry.sector_code.in_(
                        [code for code in FIXTURE_SECTORS if code != SECTOR]
                    )
                )
            )
            assert leaked.scalars().all() == [], "fixture sectors survived the restore"


@pytest_asyncio.fixture(loop_scope="function")
async def repository(seeded_registry):
    """A repository on a session belonging to the running test's own event loop."""
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemySectorRiskRepository(session)


# ── seed loading ──────────────────────────────────────────────────────────────


async def test_seed_data_loads_into_all_three_tables(repository):
    sectors = await repository.session.execute(select(SectorCodeRegistry))
    mappings = await repository.session.execute(select(SectorCodeExternalMapping))
    classifications = await repository.session.execute(select(SectorRiskClassification))

    assert len(sectors.scalars().all()) == 4
    assert len(mappings.scalars().all()) == 3
    assert len(classifications.scalars().all()) == 5


async def test_reloading_the_same_seed_is_idempotent(repository, seeded_registry):
    """The loader runs on every boot, so a second load must leave one copy.

    The reload itself is half the assertion: were the loader to append instead
    of replace, it would die on uq_sector_code_registry_sector_code — or, for
    the children, on an exclusion constraint.
    """
    async with database.AsyncSessionLocal() as other:
        await load_sector_registry(other, seeded_registry)

    repository.session.expire_all()
    rows = (await repository.session.execute(select(SectorCodeRegistry))).scalars().all()
    codes = [r.sector_code for r in rows]

    assert len(codes) == len(set(codes))
    assert len(codes) == 4


async def test_concurrent_reloads_do_not_collide(repository, seeded_registry):
    """Two replicas booting at once must not corrupt the registry (BUILD.md #6).

    Without the advisory lock this is a real failure: under READ COMMITTED the
    second transaction's DELETE cannot see the first's uncommitted rows, so it
    deletes nothing, both insert, and the later commit dies. Two sessions, two
    connections, genuinely overlapping — a single session would serialise on its
    own connection and prove nothing.
    """

    async def reload():
        async with database.AsyncSessionLocal() as session:
            await load_sector_registry(session, seeded_registry)

    await asyncio.gather(reload(), reload())

    repository.session.expire_all()
    sectors = (await repository.session.execute(select(SectorCodeRegistry))).scalars().all()
    mappings = (
        await repository.session.execute(select(SectorCodeExternalMapping))
    ).scalars().all()
    classifications = (
        await repository.session.execute(select(SectorRiskClassification))
    ).scalars().all()

    assert len(sectors) == 4
    assert len(mappings) == 3
    assert len(classifications) == 5


# ── column round trips ────────────────────────────────────────────────────────


async def test_jurisdiction_type_round_trips_as_the_domain_enum(repository):
    """The Postgres type stores lowercase values; the ORM must hand back
    JurisdictionType members, or the precedence comparison silently fails."""
    rows = await repository.list_classifications(SECTOR, JurisdictionType.CORRIDOR, "US_IN")

    assert len(rows) == 1
    assert rows[0].jurisdiction_type is JurisdictionType.CORRIDOR
    assert rows[0].risk_tier is RiskTier.CRITICAL


async def test_lower_case_identifiers_are_upper_cased_on_load(repository):
    """A sector or jurisdiction seeded in lower case would satisfy every
    constraint and then never be found."""
    sector = await repository.get_sector("LOWERCASE_SECTOR")
    rows = await repository.list_classifications(
        "LOWERCASE_SECTOR", JurisdictionType.FRAMEWORK, "FATF"
    )

    assert sector is not None
    assert len(rows) == 1
    assert rows[0].jurisdiction_value == "FATF"


async def test_external_standard_is_upper_cased_but_version_is_not(repository):
    """The asymmetry that matters: the standard name is an identifier the lookup
    matches on, the revision is a published label reported to a regulator."""
    rows = await repository.list_external_mappings(SECTOR, "NACE")

    assert len(rows) == 1
    assert rows[0].external_standard == "NACE"
    assert rows[0].external_standard_version == "NACE Rev.2"


async def test_external_code_round_trips_as_text(repository):
    rows = await repository.list_external_mappings(SECTOR, "ISIC")

    codes = {r.external_code for r in rows}
    assert codes == {"4649", "5190"}
    assert all(isinstance(r.external_code, str) for r in rows)


async def test_null_classification_label_round_trips(repository):
    """The corridor row rates the sector without publishing a label."""
    rows = await repository.list_classifications(SECTOR, JurisdictionType.CORRIDOR, "US_IN")

    assert rows[0].classification_label is None


async def test_effective_dates_round_trip_as_dates(repository):
    """Postgres DATE columns must come back as date objects — is_effective_at
    compares them directly and would raise on strings."""
    rows = await repository.list_classifications(
        SECTOR, JurisdictionType.COUNTRY, "EXPIRED_REGIME"
    )

    assert rows[0].effective_from == date(2020, 1, 1)
    assert rows[0].effective_to == date(2024, 1, 1)


# ── acceptance criteria through the real database ─────────────────────────────


async def test_no_overrides_resolves_to_fatf(repository):
    """AC1, end to end: YAML to Postgres to repository to lookup."""
    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.HIGH
    assert resolution.classification_label == "DNFBP"
    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK
    assert resolution.jurisdiction_value == "FATF"
    assert resolution.matched is True


async def test_corridor_takes_precedence(repository):
    """AC2."""
    resolution = await get_sector_risk_classification(
        SECTOR, "US_IN", "AE_CBUAE", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.CRITICAL
    assert resolution.jurisdiction_type is JurisdictionType.CORRIDOR


async def test_country_takes_precedence_over_framework(repository):
    """AC3."""
    resolution = await get_sector_risk_classification(
        SECTOR, None, "AE_CBUAE", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.ELEVATED
    assert resolution.jurisdiction_type is JurisdictionType.COUNTRY


async def test_expired_country_rule_falls_through_to_framework(repository):
    resolution = await get_sector_risk_classification(
        SECTOR, None, "EXPIRED_REGIME", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.HIGH
    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK


async def test_unknown_sector_reports_no_match(repository):
    """AC4."""
    resolution = await get_sector_risk_classification(
        "NO_SUCH_SECTOR", None, None, AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is False


async def test_unrated_sector_reports_no_match(repository):
    resolution = await get_sector_risk_classification("UNRATED_SECTOR", None, None, AS_OF, repository)

    assert resolution.matched is False


async def test_retired_sector_reports_no_match(repository):
    resolution = await get_sector_risk_classification("RETIRED_SECTOR", None, None, AS_OF, repository)

    assert resolution.matched is False


async def test_backdated_query_resolves_the_rating_then_in_force(repository):
    """EXPIRED_REGIME governed this sector in 2022 and must still do so for a
    payment dated then, even though it has since lapsed."""
    resolution = await get_sector_risk_classification(
        SECTOR, None, "EXPIRED_REGIME", date(2022, 6, 1), repository
    )

    assert resolution.risk_tier is RiskTier.CRITICAL
    assert resolution.classification_label == "STALE"


# ── external code lookup ──────────────────────────────────────────────────────


async def test_external_code_returns_code_and_version(repository):
    """AC6."""
    result = await get_sector_external_code(SECTOR, "ISIC", AS_OF, repository)

    assert result is not None
    assert result.external_code == "4649"
    assert result.external_standard_version == "ISIC Rev.4"


async def test_superseded_revision_resolves_for_a_historical_date(repository):
    """Rev.3 closed the day Rev.4 opened, so each governs its own era. Both rows
    coexist only because external_standard_version is in the exclusion key."""
    result = await get_sector_external_code(SECTOR, "ISIC", date(2022, 6, 1), repository)

    assert result is not None
    assert result.external_code == "5190"
    assert result.external_standard_version == "ISIC Rev.3"


async def test_unmapped_standard_returns_none(repository):
    assert await get_sector_external_code(SECTOR, "NAICS", AS_OF, repository) is None
