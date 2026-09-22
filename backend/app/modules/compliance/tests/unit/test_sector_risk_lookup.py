"""Sector risk resolution, branch by branch.

Exercised against an in-memory repository: every branch of
``get_sector_risk_classification`` is decided in Python, so a database would add
runtime without adding coverage. That the rows survive a round trip through
Postgres is proven in tests/integration/test_sector_registry_seed_loading.py.

No test here names a real regulator except FATF, which the resolution chain
knows by name. Everything else is invented on the spot — if a test had to be
edited to onboard a jurisdiction, the registry would not be doing its job.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.sector_risk_service import (
    get_sector_risk_classification,
)
from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    RiskTier,
    SectorCodeExternalMapping,
    SectorCodeRegistry,
    SectorRiskClassification,
)

SECTOR = "PRECIOUS_STONES_TRADE"
EPOCH = date(2024, 1, 1)
AS_OF = date(2026, 8, 12)


def sector_row(
    *,
    sector_code: str = SECTOR,
    effective_from: date = EPOCH,
    effective_to: date | None = None,
) -> SectorCodeRegistry:
    return SectorCodeRegistry(
        sector_code=sector_code,
        description="test sector",
        effective_from=effective_from,
        effective_to=effective_to,
    )


def classification_row(
    jurisdiction_type: JurisdictionType,
    jurisdiction_value: str,
    risk_tier: RiskTier,
    classification_label: str | None = None,
    *,
    sector_code: str = SECTOR,
    effective_from: date = EPOCH,
    effective_to: date | None = None,
) -> SectorRiskClassification:
    return SectorRiskClassification(
        sector_code=sector_code,
        jurisdiction_type=jurisdiction_type,
        jurisdiction_value=jurisdiction_value,
        risk_tier=risk_tier,
        classification_label=classification_label,
        notes="test classification",
        effective_from=effective_from,
        effective_to=effective_to,
    )


class StubSectorRiskRepository:
    """In-memory stand-in satisfying SectorRiskRepository.

    Filters on identity only, never on dates — the same division of labour the
    SQLAlchemy repository keeps, so these tests exercise the real decision logic
    rather than a simplified copy of it.
    """

    def __init__(
        self,
        sectors: list[SectorCodeRegistry],
        classifications: list[SectorRiskClassification],
        mappings: list[SectorCodeExternalMapping] | None = None,
    ) -> None:
        self._sectors = sectors
        self._classifications = classifications
        self._mappings = mappings or []

    async def get_sector(self, sector_code: str) -> SectorCodeRegistry | None:
        return next((s for s in self._sectors if s.sector_code == sector_code), None)

    async def list_classifications(
        self,
        sector_code: str,
        jurisdiction_type: JurisdictionType,
        jurisdiction_value: str,
    ) -> list[SectorRiskClassification]:
        return [
            c
            for c in self._classifications
            if c.sector_code == sector_code
            and c.jurisdiction_type == jurisdiction_type
            and c.jurisdiction_value == jurisdiction_value
        ]

    async def list_external_mappings(
        self, sector_code: str, external_standard: str
    ) -> list[SectorCodeExternalMapping]:
        return [
            m
            for m in self._mappings
            if m.sector_code == sector_code and m.external_standard == external_standard
        ]


@pytest.fixture
def repository() -> StubSectorRiskRepository:
    """A registry rated at all three tiers, so precedence is observable."""
    return StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP"),
            classification_row(JurisdictionType.COUNTRY, "US_FINCEN", RiskTier.HIGH, "DNFBP"),
            classification_row(JurisdictionType.COUNTRY, "AE_CBUAE", RiskTier.ELEVATED, "DPMS"),
            classification_row(
                JurisdictionType.CORRIDOR, "US_IN", RiskTier.CRITICAL, "CORRIDOR_RULE"
            ),
        ],
    )


# ── AC1: framework resolves, and says so ──────────────────────────────────────


async def test_no_overrides_resolves_to_the_fatf_framework(repository):
    """AC1. With neither a corridor nor a country supplied, the international
    view governs — and the answer names FATF as the authority that produced it."""
    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.HIGH
    assert resolution.classification_label == "DNFBP"
    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK
    assert resolution.jurisdiction_value == FATF_FRAMEWORK
    assert resolution.matched is True


# ── AC2/AC3: precedence ───────────────────────────────────────────────────────


async def test_corridor_takes_precedence_over_country_and_framework(repository):
    """AC2. All three tiers are populated; the corridor rule is the most
    specific statement about this payment and must win."""
    resolution = await get_sector_risk_classification(
        SECTOR, "US_IN", "US_FINCEN", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.CRITICAL
    assert resolution.jurisdiction_type is JurisdictionType.CORRIDOR
    assert resolution.jurisdiction_value == "US_IN"


async def test_country_takes_precedence_over_framework(repository):
    """AC3. AE_CBUAE rates this sector elevated where FATF rates it high. The
    national regulator governs payments it has jurisdiction over."""
    resolution = await get_sector_risk_classification(
        SECTOR, None, "AE_CBUAE", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.ELEVATED
    assert resolution.classification_label == "DPMS"
    assert resolution.jurisdiction_type is JurisdictionType.COUNTRY


async def test_unmapped_corridor_falls_through_to_country(repository):
    """A corridor nobody has written a rule for is not an answer — resolution
    continues down the ladder rather than stopping."""
    resolution = await get_sector_risk_classification(
        SECTOR, "ZZ_UNKNOWN", "US_FINCEN", AS_OF, repository
    )

    assert resolution.jurisdiction_type is JurisdictionType.COUNTRY
    assert resolution.jurisdiction_value == "US_FINCEN"


async def test_unmapped_country_falls_through_to_framework(repository):
    resolution = await get_sector_risk_classification(
        SECTOR, None, "ZZ_UNKNOWN", AS_OF, repository
    )

    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK


async def test_both_unmapped_falls_through_to_framework(repository):
    resolution = await get_sector_risk_classification(
        SECTOR, "ZZ_CORRIDOR", "ZZ_COUNTRY", AS_OF, repository
    )

    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK
    assert resolution.risk_tier is RiskTier.HIGH


# ── expiry inside the ladder ──────────────────────────────────────────────────


async def test_expired_corridor_rule_falls_through_to_country():
    """A lapsed rule is treated as never having existed. Returning it would
    govern a payment by a rating its own authority has withdrawn."""
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP"),
            classification_row(JurisdictionType.COUNTRY, "US_FINCEN", RiskTier.ELEVATED, "BSA"),
            classification_row(
                JurisdictionType.CORRIDOR,
                "US_IN",
                RiskTier.CRITICAL,
                "OLD",
                effective_to=date(2025, 1, 1),
            ),
        ],
    )

    resolution = await get_sector_risk_classification(
        SECTOR, "US_IN", "US_FINCEN", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.ELEVATED
    assert resolution.jurisdiction_type is JurisdictionType.COUNTRY


async def test_expired_country_rule_falls_through_to_framework():
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP"),
            classification_row(
                JurisdictionType.COUNTRY,
                "IN_RBI",
                RiskTier.ELEVATED,
                effective_to=date(2025, 1, 1),
            ),
        ],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, "IN_RBI", AS_OF, repository)

    assert resolution.risk_tier is RiskTier.HIGH
    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK


async def test_expired_framework_rule_returns_the_unmatched_baseline():
    """The end of the ladder. With FATF itself lapsed there is nothing left to
    inherit, so the baseline is the answer — reported as unmatched."""
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(
                JurisdictionType.FRAMEWORK,
                FATF_FRAMEWORK,
                RiskTier.HIGH,
                "DNFBP",
                effective_to=date(2025, 1, 1),
            )
        ],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is False


# ── AC4: unknown sector is explicit, not silent ───────────────────────────────


async def test_unknown_sector_returns_standard_and_reports_no_match(repository):
    """AC4. The tier alone cannot distinguish "nobody rates this" from "rated
    ordinary" — ``matched`` is what makes the gap visible to the caller."""
    resolution = await get_sector_risk_classification(
        "NO_SUCH_SECTOR", None, None, AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.classification_label is None
    assert resolution.jurisdiction_type is None
    assert resolution.jurisdiction_value is None
    assert resolution.matched is False


async def test_a_sector_rated_standard_is_reported_as_matched():
    """The other half of AC4, and the reason ``matched`` cannot be inferred from
    the tier: this sector carries the same STANDARD tier as an unknown one, but
    an authority chose it deliberately."""
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.STANDARD, "NOT_DESIGNATED"
            )
        ],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is True
    assert resolution.jurisdiction_value == FATF_FRAMEWORK


async def test_unrated_sector_returns_the_unmatched_baseline():
    """A registered sector no authority has rated."""
    repository = StubSectorRiskRepository([sector_row()], [])

    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is False


async def test_retired_sector_returns_the_unmatched_baseline():
    """The sector itself is out of its window, so no rating of it can apply."""
    repository = StubSectorRiskRepository(
        [sector_row(effective_to=date(2025, 1, 1))],
        [classification_row(JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP")],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is False


async def test_sector_not_yet_effective_returns_the_unmatched_baseline():
    repository = StubSectorRiskRepository(
        [sector_row(effective_from=date(2027, 1, 1))],
        [classification_row(JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP")],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert resolution.matched is False


# ── AC5: onboarding is data, not code ─────────────────────────────────────────


async def test_a_new_country_resolves_without_code_changes(repository):
    """AC5. AE_CBUAE appears nowhere in the implementation — only FATF is named
    in code, and only because the ladder terminates there."""
    resolution = await get_sector_risk_classification(
        SECTOR, None, "AE_CBUAE", AS_OF, repository
    )

    assert resolution.jurisdiction_value == "AE_CBUAE"
    assert resolution.matched is True


async def test_a_new_sector_resolves_without_code_changes():
    """AC5 for sectors. Nothing in the lookup enumerates which sectors exist."""
    repository = StubSectorRiskRepository(
        [sector_row(sector_code="ART_DEALERS")],
        [
            classification_row(
                JurisdictionType.COUNTRY,
                "EU_AMLD",
                RiskTier.CRITICAL,
                "OBLIGED_ENTITY",
                sector_code="ART_DEALERS",
            )
        ],
    )

    resolution = await get_sector_risk_classification(
        "ART_DEALERS", None, "EU_AMLD", AS_OF, repository
    )

    assert resolution.risk_tier is RiskTier.CRITICAL
    assert resolution.classification_label == "OBLIGED_ENTITY"


# ── effective-date boundaries (half-open: [from, to) ) ───────────────────────


async def test_classification_is_effective_on_its_first_day(repository):
    resolution = await get_sector_risk_classification(SECTOR, None, None, EPOCH, repository)

    assert resolution.risk_tier is RiskTier.HIGH


async def test_classification_is_not_effective_on_its_end_date():
    """effective_to is exclusive, matching the '[)' bound in the exclusion
    constraint. An off-by-one here would apply a withdrawn rating for a day."""
    end = date(2025, 1, 1)
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP",
                effective_to=end,
            )
        ],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, None, end, repository)

    assert resolution.matched is False


async def test_classification_is_effective_the_day_before_its_end_date():
    repository = StubSectorRiskRepository(
        [sector_row()],
        [
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP",
                effective_to=date(2025, 1, 1),
            )
        ],
    )

    resolution = await get_sector_risk_classification(
        SECTOR, None, None, date(2024, 12, 31), repository
    )

    assert resolution.risk_tier is RiskTier.HIGH


async def test_backdated_query_resolves_the_rating_then_in_force():
    """Screening a payment dated before a regulator re-rated a sector must apply
    the rating in force when the money moved, not today's."""
    repository = StubSectorRiskRepository(
        [sector_row(effective_from=date(2020, 1, 1))],
        [
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.ELEVATED, "OLD",
                effective_from=date(2020, 1, 1), effective_to=EPOCH,
            ),
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP"
            ),
        ],
    )

    historical = await get_sector_risk_classification(
        SECTOR, None, None, date(2022, 6, 1), repository
    )
    current = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    assert historical.risk_tier is RiskTier.ELEVATED
    assert historical.classification_label == "OLD"
    assert current.risk_tier is RiskTier.HIGH


# ── identifier normalisation ──────────────────────────────────────────────────


async def test_lower_case_identifiers_resolve(repository):
    """Values are matched with ``=`` against upper-cased stored rows."""
    resolution = await get_sector_risk_classification(
        SECTOR.lower(), "us_in", None, AS_OF, repository
    )

    assert resolution.jurisdiction_type is JurisdictionType.CORRIDOR


async def test_padded_identifiers_resolve(repository):
    """A stray space from a CSV import is not a different corridor."""
    resolution = await get_sector_risk_classification(
        f"  {SECTOR}  ", None, "  AE_CBUAE  ", AS_OF, repository
    )

    assert resolution.jurisdiction_value == "AE_CBUAE"


@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_blank_corridor_and_country_are_treated_as_absent(repository, blank):
    """An empty string is not a jurisdiction. Normalising it to None keeps a
    caller passing "" from searching for a corridor literally named nothing."""
    resolution = await get_sector_risk_classification(SECTOR, blank, blank, AS_OF, repository)

    assert resolution.jurisdiction_type is JurisdictionType.FRAMEWORK


# ── data shape ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier", list(RiskTier))
async def test_every_risk_tier_resolves(tier):
    repository = StubSectorRiskRepository(
        [sector_row()],
        [classification_row(JurisdictionType.COUNTRY, "ZZ", tier, "LABEL")],
    )

    resolution = await get_sector_risk_classification(SECTOR, None, "ZZ", AS_OF, repository)

    assert resolution.risk_tier is tier


async def test_resolution_is_immutable(repository):
    """Callers pass the result into screening decisions; it must not be editable
    in place by one of them."""
    resolution = await get_sector_risk_classification(SECTOR, None, None, AS_OF, repository)

    with pytest.raises(AttributeError):
        resolution.risk_tier = RiskTier.STANDARD


# ── malformed input is a caller bug, not a regulatory fact ────────────────────


@pytest.mark.parametrize("sector_code", ["", "   ", None])
async def test_missing_sector_code_is_rejected(repository, sector_code):
    with pytest.raises(ValueError):
        await get_sector_risk_classification(sector_code, None, None, AS_OF, repository)


async def test_missing_as_of_date_is_rejected(repository):
    """Guarded rather than left to fail downstream: a null date reaches the date
    comparison in is_effective_at and raises TypeError, which a global handler
    renders as a 500."""
    with pytest.raises(ValueError):
        await get_sector_risk_classification(SECTOR, None, None, None, repository)
