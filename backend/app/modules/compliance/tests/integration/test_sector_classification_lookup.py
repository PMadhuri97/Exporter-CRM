"""S0T2's real classification lookup, held to the port S0T3 declares.

These began life as ``test_sector_classification_stub.py``, guarding the
Walk-phase stand-in so that swapping in the real
``get_sector_risk_classification`` would be a substitution and not a rewrite.
That swap has now happened (AL-443 gave the registry a
``jurisdiction_type``/``jurisdiction_value`` pair), so they now exercise
``SectorRegistryClassificationLookup`` against the real seeded registry.

The signature and not-found assertions carried over unchanged, which is the
point they were written to prove. Of the two precedence tests that were skipped
pending the real lookup, the country rung now resolves and is un-skipped below;
the corridor rung still cannot be proved from the shipped seed data — for a
different reason than before, recorded rather than hidden.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest
import pytest_asyncio

from app.modules.compliance.application.sector_classification import (
    SectorRegistryClassificationLookup,
)
from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.jurisdiction import JurisdictionType
from app.modules.compliance.domain.ports import SectorClassificationLookup
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    SEED_DATA_DIR,
    load_sector_registry,
)
from app.modules.compliance.infrastructure.sector_risk_repository import (
    SQLAlchemySectorRiskRepository,
)
from app.platform.database import services as database

DNFBP_SECTOR = "PRECIOUS_STONES_TRADE"
CORRIDOR = "US_IN"
US_COUNTRY_REGIME = "US_FINCEN"
AS_OF = date(2026, 8, 12)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded():
    async with database.AsyncSessionLocal() as session:
        await load_sector_registry(session, SEED_DATA_DIR)


@pytest_asyncio.fixture(loop_scope="function")
async def lookup(seeded):
    async with database.AsyncSessionLocal() as session:
        yield SectorRegistryClassificationLookup(SQLAlchemySectorRiskRepository(session))


# ── the S0T2 contract ─────────────────────────────────────────────────────────


def test_the_lookup_satisfies_the_port():
    assert isinstance(SectorRegistryClassificationLookup, type)
    # Structural, not nominal: the port is a Protocol and the adapter does not
    # inherit from it.
    assert hasattr(SectorRegistryClassificationLookup, "resolve")


def test_the_signature_matches_s0t2s_lookup():
    """S0T2 specifies
    ``get_sector_risk_classification(sector_code, corridor_id,
    country_jurisdiction, as_of_date)``. An adapter missing an argument would
    force every caller to change on the day a rung starts resolving."""
    parameters = list(
        inspect.signature(SectorRegistryClassificationLookup.resolve).parameters
    )

    assert parameters == [
        "self",
        "sector_code",
        "corridor_id",
        "country_jurisdiction",
        "as_of_date",
    ]
    assert list(inspect.signature(SectorClassificationLookup.resolve).parameters) == parameters


async def test_a_classified_sector_returns_the_tier_label_and_jurisdiction_pair(lookup):
    """AC: PRECIOUS_STONES_TRADE with no override resolves high / DNFBP and
    identifies FATF as the resolving jurisdiction."""
    resolved = await lookup.resolve(DNFBP_SECTOR, None, None, AS_OF)

    assert resolved.found is True
    assert resolved.risk_tier == "high"
    assert resolved.classification_label == "DNFBP"
    assert resolved.resolving_jurisdiction is not None
    assert resolved.resolving_jurisdiction.type is JurisdictionType.FRAMEWORK
    assert resolved.resolving_jurisdiction.value == FATF_FRAMEWORK


async def test_an_unknown_sector_is_reported_as_not_found(lookup):
    """AC: an unknown sector returns standard with an explicit not-found
    indication rather than a silent default."""
    resolved = await lookup.resolve("NO_SUCH_SECTOR", None, None, AS_OF)

    assert resolved.found is False
    assert resolved.risk_tier == "standard"
    assert resolved.classification_label is None
    assert resolved.resolving_jurisdiction is None


async def test_a_sector_predating_its_classification_is_not_found(lookup):
    """Effectivity is judged on as_of_date. Before the classification took
    effect there was nothing to find — which is not the same as a standard
    rating."""
    resolved = await lookup.resolve(DNFBP_SECTOR, None, None, date(2020, 1, 1))

    assert resolved.found is False
    assert resolved.resolving_jurisdiction is None


async def test_supplying_a_corridor_and_country_is_accepted(lookup):
    """Both arguments are part of the contract. Unlike under the stub, they now
    genuinely participate in resolution."""
    resolved = await lookup.resolve(DNFBP_SECTOR, CORRIDOR, US_COUNTRY_REGIME, AS_OF)

    assert resolved.found is True
    assert resolved.risk_tier == "high"


async def test_the_answer_is_stable_across_repeats(lookup):
    first = await lookup.resolve(DNFBP_SECTOR, CORRIDOR, None, AS_OF)
    second = await lookup.resolve(DNFBP_SECTOR, CORRIDOR, None, AS_OF)

    assert first == second


# ── precedence, now that the registry can express it ──────────────────────────


async def test_a_country_classification_outranks_the_framework(lookup):
    """S0T2 AC, and the reason the stub had to go.

    US_FINCEN rates PRECIOUS_STONES_TRADE high/DNFBP in the shipped seed data.
    The stub could not tell that row apart from FATF's and always answered
    ``framework``/``FATF``; the real lookup prefers the more specific rung.
    """
    resolved = await lookup.resolve(DNFBP_SECTOR, None, US_COUNTRY_REGIME, AS_OF)

    assert resolved.resolving_jurisdiction is not None
    assert resolved.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert resolved.resolving_jurisdiction.value == US_COUNTRY_REGIME


async def test_an_unmatched_corridor_falls_through_to_the_country_rung(lookup):
    """A corridor with no classification is not an answer — resolution
    continues down the ladder rather than stopping at the most specific rung
    that was *asked* about."""
    resolved = await lookup.resolve(DNFBP_SECTOR, CORRIDOR, US_COUNTRY_REGIME, AS_OF)

    assert resolved.resolving_jurisdiction is not None
    assert resolved.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert resolved.resolving_jurisdiction.value == US_COUNTRY_REGIME


@pytest.mark.skip(
    reason="No corridor classification is seeded for any sector. The lookup "
    "resolves the corridor rung (see test_sector_risk_lookup.py, which proves it "
    "against a fake repository); this asserts it end-to-end against the shipped "
    "seed data, so it needs a corridor row in risk-classifications.yaml. That is "
    "a compliance seed-data decision, not an engineering one."
)
async def test_a_corridor_classification_outranks_country_and_framework(lookup):
    """S0T2 AC. Requires a corridor row in the shipped seed data."""
    resolved = await lookup.resolve(DNFBP_SECTOR, CORRIDOR, US_COUNTRY_REGIME, AS_OF)

    assert resolved.resolving_jurisdiction is not None
    assert resolved.resolving_jurisdiction.type is JurisdictionType.CORRIDOR
    assert resolved.resolving_jurisdiction.value == CORRIDOR
