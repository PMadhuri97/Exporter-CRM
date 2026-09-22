"""The registry traced through one export-financing transaction.

An Indian bank is asked to fund an Indian diamond exporter against a $100,000
invoice from a US buyer. Before advancing the INR financing it has to decide
whether the exporter's line of business obliges enhanced due diligence, and be
able to say which authority made that so.

    Indian exporter (PRECIOUS_STONES_TRADE)
        -> bank evaluates the funding request
            -> sector risk lookup
                -> tier, label, AND the authority that decided it
                    -> EDD or not

Every classification below is INVENTED for the purpose of this scenario. The
shipped seed data carries FATF and US_FINCEN only; IN_RBI is pending compliance
and legal confirmation, and nothing here should be read as a statement of what
the RBI holds. The point of the suite is the resolution behaviour, not the
ratings — which is also why it uses a stub rather than the real seed files.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.sector_external_code_service import (
    get_sector_external_code,
)
from app.modules.compliance.application.sector_risk_service import (
    get_sector_risk_classification,
)
from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    RiskTier,
)
from app.modules.compliance.tests.unit.test_sector_external_code import mapping_row
from app.modules.compliance.tests.unit.test_sector_risk_lookup import (
    StubSectorRiskRepository,
    classification_row,
    sector_row,
)

EXPORTER_SECTOR = "PRECIOUS_STONES_TRADE"

#: The FATF designation this scenario's sector carries. Compared directly here
#: because ``requires_enhanced_due_diligence()`` was removed — whether a label
#: obliges EDD is now the DNFBP_EDD_REQUIRED rule's decision, and this suite is
#: about S0T2 resolution rather than about what the registry does with it.
DESIGNATED_LABEL = "DNFBP"

#: The exporter's own regulator, resolved from its country of domicile.
EXPORTER_REGULATOR = "IN_RBI"

#: India receiving from the United States. Matches the corridor ids already in
#: use for purpose codes (US_IN, UK_IN, EUR_IN).
CORRIDOR = "US_IN"

FUNDING_DATE = date(2026, 8, 12)


@pytest.fixture
def registry() -> StubSectorRiskRepository:
    """The registry as it would look once all three tiers are populated."""
    return StubSectorRiskRepository(
        [sector_row(sector_code=EXPORTER_SECTOR)],
        [
            # FATF Recommendation 22 designates dealers in precious metals and
            # stones. This row is real and ships today.
            classification_row(
                JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP",
                sector_code=EXPORTER_SECTOR,
            ),
            # ASSUMED. India's PMLA treats dealers in precious metals and stones
            # as reporting entities; the tier and label here are illustrative.
            classification_row(
                JurisdictionType.COUNTRY, EXPORTER_REGULATOR, RiskTier.HIGH,
                "PMLA_REPORTING_ENTITY", sector_code=EXPORTER_SECTOR,
            ),
            # ASSUMED. A corridor rule exists where a regulator has taken a
            # position on this sector for this specific route.
            classification_row(
                JurisdictionType.CORRIDOR, CORRIDOR, RiskTier.CRITICAL,
                "CORRIDOR_ENHANCED", sector_code=EXPORTER_SECTOR,
            ),
        ],
        [
            mapping_row("ISIC", "ISIC Rev.4", "4649", sector_code=EXPORTER_SECTOR),
            # ASSUMED code. NIC is what RBI reporting requires.
            mapping_row("NIC", "NIC-2008", "46693", sector_code=EXPORTER_SECTOR),
        ],
    )


async def test_bank_with_no_jurisdiction_context_still_gets_a_defensible_answer(registry):
    """The state the platform is in today: no corridor on the transaction, no
    regulator on the customer. The bank still learns the sector is high risk and
    that FATF is why — enough to open EDD and to justify it."""
    resolution = await get_sector_risk_classification(
        EXPORTER_SECTOR, None, None, FUNDING_DATE, registry
    )

    assert resolution.risk_tier is RiskTier.HIGH
    assert resolution.classification_label == DESIGNATED_LABEL
    assert resolution.jurisdiction_value == FATF_FRAMEWORK


async def test_the_exporters_own_regulator_governs_when_it_is_known(registry):
    """Once the exporter's domicile resolves to a regulator, the RBI's position
    supersedes the international one — the bank is Indian and answers to it."""
    resolution = await get_sector_risk_classification(
        EXPORTER_SECTOR, None, EXPORTER_REGULATOR, FUNDING_DATE, registry
    )

    assert resolution.jurisdiction_type is JurisdictionType.COUNTRY
    assert resolution.jurisdiction_value == EXPORTER_REGULATOR
    assert resolution.classification_label == "PMLA_REPORTING_ENTITY"


async def test_a_corridor_rule_governs_this_particular_route(registry):
    """The invoice is collected from a US buyer into India. A rule written for
    that route is the most specific statement anyone has made about this
    transaction, so it outranks both the RBI and FATF."""
    resolution = await get_sector_risk_classification(
        EXPORTER_SECTOR, CORRIDOR, EXPORTER_REGULATOR, FUNDING_DATE, registry
    )

    assert resolution.risk_tier is RiskTier.CRITICAL
    assert resolution.jurisdiction_type is JurisdictionType.CORRIDOR
    assert resolution.jurisdiction_value == CORRIDOR


async def test_the_answer_names_the_authority_that_produced_it(registry):
    """The reason the resolving jurisdiction is not optional. "High risk" does
    not survive a regulator asking why the bank escalated; "the RBI designates
    this sector a PMLA reporting entity" does."""
    resolution = await get_sector_risk_classification(
        EXPORTER_SECTOR, None, EXPORTER_REGULATOR, FUNDING_DATE, registry
    )

    assert (resolution.jurisdiction_type, resolution.jurisdiction_value) == (
        JurisdictionType.COUNTRY,
        EXPORTER_REGULATOR,
    )
    assert resolution.matched is True


async def test_an_unregistered_exporter_sector_is_flagged_not_waved_through(registry):
    """The case that matters most for a funding decision. A sector nobody has
    rated carries the standard tier — the same tier as a sector deliberately
    rated ordinary — so the bank must read ``matched`` rather than the tier, or
    it will approve an unknown business as though it had been cleared."""
    resolution = await get_sector_risk_classification(
        "UNREGISTERED_TRADE", None, EXPORTER_REGULATOR, FUNDING_DATE, registry
    )

    assert resolution.risk_tier is RiskTier.STANDARD
    assert resolution.matched is False
    assert resolution.classification_label != DESIGNATED_LABEL


async def test_the_financing_is_screened_against_the_date_it_was_advanced(registry):
    """Financing advanced before a regulator changed its position must be judged
    on the position in force then. A facility reviewed two years later is not
    retrospectively non-compliant because the rating moved."""
    later = StubSectorRiskRepository(
        [sector_row(sector_code=EXPORTER_SECTOR, effective_from=date(2020, 1, 1))],
        [
            classification_row(
                JurisdictionType.COUNTRY, EXPORTER_REGULATOR, RiskTier.ELEVATED,
                "EARLIER_POSITION", sector_code=EXPORTER_SECTOR,
                effective_from=date(2020, 1, 1), effective_to=date(2026, 1, 1),
            ),
            classification_row(
                JurisdictionType.COUNTRY, EXPORTER_REGULATOR, RiskTier.CRITICAL,
                "CURRENT_POSITION", sector_code=EXPORTER_SECTOR,
                effective_from=date(2026, 1, 1),
            ),
        ],
    )

    at_drawdown = await get_sector_risk_classification(
        EXPORTER_SECTOR, None, EXPORTER_REGULATOR, date(2025, 3, 1), later
    )
    at_review = await get_sector_risk_classification(
        EXPORTER_SECTOR, None, EXPORTER_REGULATOR, FUNDING_DATE, later
    )

    assert at_drawdown.classification_label == "EARLIER_POSITION"
    assert at_review.classification_label == "CURRENT_POSITION"


async def test_rbi_reporting_needs_the_nic_code_not_the_isic_one(registry):
    """The second service, and why external codes left the registry table. One
    exporter needs an ISIC code for one audience and a NIC code for RBI's
    FDI/ODI reporting — each with the revision that produced it."""
    isic = await get_sector_external_code(EXPORTER_SECTOR, "ISIC", FUNDING_DATE, registry)
    nic = await get_sector_external_code(EXPORTER_SECTOR, "NIC", FUNDING_DATE, registry)

    assert isic is not None
    assert (isic.external_code, isic.external_standard_version) == ("4649", "ISIC Rev.4")
    assert nic is not None
    assert (nic.external_code, nic.external_standard_version) == ("46693", "NIC-2008")


async def test_a_standard_nobody_has_mapped_yields_nothing_rather_than_a_guess(registry):
    """If the bank had to file under a standard the registry does not carry, the
    lookup returns None. Filing an invented code with a regulator is worse than
    filing none."""
    assert await get_sector_external_code(
        EXPORTER_SECTOR, "NAICS", FUNDING_DATE, registry
    ) is None
