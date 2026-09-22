from __future__ import annotations

from datetime import date

import pytest

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.application.sector_classification import (
    SectorRegistryClassificationLookup,
)
from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.domain.jurisdiction import JurisdictionType
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.required_action import RequiredAction
from app.modules.compliance.tests.unit.test_sector_risk_lookup import (
    SECTOR,
    StubSectorRiskRepository,
    classification_row,
    sector_row,
)

AS_OF = date(2026, 8, 12)
CORRIDOR = "US_IN"
COUNTRY_REGIME = "US_FINCEN"


def _lookup(*classifications, sectors=None) -> SectorRegistryClassificationLookup:
    return SectorRegistryClassificationLookup(
        StubSectorRiskRepository(
            sectors if sectors is not None else [sector_row()],
            list(classifications),
        )
    )


FRAMEWORK_ROW = classification_row(
    JurisdictionType.FRAMEWORK, FATF_FRAMEWORK, RiskTier.HIGH, "DNFBP"
)
COUNTRY_ROW = classification_row(
    JurisdictionType.COUNTRY, COUNTRY_REGIME, RiskTier.ELEVATED, "BSA_DPMS"
)
CORRIDOR_ROW = classification_row(
    JurisdictionType.CORRIDOR, CORRIDOR, RiskTier.CRITICAL, "CORRIDOR_DESIGNATED"
)


# ── Case D — framework fallback ───────────────────────────────────────────────


async def test_the_framework_answers_when_nothing_more_specific_applies():
    resolved = await _lookup(FRAMEWORK_ROW).resolve(SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF)

    assert resolved.found is True
    assert resolved.risk_tier == "high"
    assert resolved.classification_label == "DNFBP"
    assert resolved.resolving_jurisdiction.type is JurisdictionType.FRAMEWORK
    assert resolved.resolving_jurisdiction.value == FATF_FRAMEWORK


async def test_the_framework_is_not_consulted_when_a_country_rule_exists():
    """Fallback, not default. The framework row is present and still loses."""
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW).resolve(
        SECTOR, None, COUNTRY_REGIME, AS_OF
    )

    assert resolved.resolving_jurisdiction.type is not JurisdictionType.FRAMEWORK


# ── Case B — country beats framework ──────────────────────────────────────────


async def test_a_country_classification_outranks_the_framework():
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW).resolve(
        SECTOR, None, COUNTRY_REGIME, AS_OF
    )

    assert resolved.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert resolved.resolving_jurisdiction.value == COUNTRY_REGIME
    # The tier travels with the authority that won, not with the one that lost.
    assert resolved.risk_tier == "elevated"
    assert resolved.classification_label == "BSA_DPMS"


async def test_a_country_rung_is_skipped_when_the_caller_names_no_country():
    """The country row exists but nobody asked about that regime.

    This is the state S0T3 is in today: no settlement record names a country, so
    the argument is None and the rung cannot be reached however well populated
    the registry is.
    """
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW).resolve(SECTOR, None, None, AS_OF)

    assert resolved.resolving_jurisdiction.type is JurisdictionType.FRAMEWORK


# ── Case C — corridor beats country and framework ─────────────────────────────


async def test_a_corridor_classification_outranks_country_and_framework():
    """The rung the integration suite cannot reach: no corridor row is seeded."""
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW, CORRIDOR_ROW).resolve(
        SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF
    )

    assert resolved.resolving_jurisdiction.type is JurisdictionType.CORRIDOR
    assert resolved.resolving_jurisdiction.value == CORRIDOR
    assert resolved.risk_tier == "critical"
    assert resolved.classification_label == "CORRIDOR_DESIGNATED"


async def test_an_unmatched_corridor_falls_through_rather_than_stopping():
    """Asking about a corridor that has no rule is not an answer."""
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW).resolve(
        SECTOR, "ZZ_NOWHERE", COUNTRY_REGIME, AS_OF
    )

    assert resolved.resolving_jurisdiction.type is JurisdictionType.COUNTRY


async def test_a_lapsed_corridor_rule_falls_through_to_the_country():
    """Effectivity is judged before precedence: an expired corridor rule is not
    a less-specific answer, it is no answer."""
    lapsed = classification_row(
        JurisdictionType.CORRIDOR,
        CORRIDOR,
        RiskTier.CRITICAL,
        "RETIRED",
        effective_to=date(2025, 1, 1),
    )
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW, lapsed).resolve(
        SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF
    )

    assert resolved.resolving_jurisdiction.type is JurisdictionType.COUNTRY


# ── Case E — nothing found ────────────────────────────────────────────────────


async def test_an_unrated_sector_is_reported_as_not_found():
    resolved = await _lookup(sectors=[sector_row()]).resolve(
        SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF
    )

    assert resolved.found is False
    assert resolved.resolving_jurisdiction is None
    assert resolved.classification_label is None
    # Standard, but explicitly not-found: a sector nobody rated and one rated
    # standard are different facts and must not collapse.
    assert resolved.risk_tier == "standard"


async def test_an_unknown_sector_is_reported_as_not_found():
    resolved = await _lookup(FRAMEWORK_ROW, sectors=[]).resolve(
        SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF
    )

    assert resolved.found is False
    assert resolved.resolving_jurisdiction is None


async def test_the_not_found_answer_is_stable_across_repeats():
    lookup = _lookup(sectors=[])

    answers = [await lookup.resolve(SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF) for _ in range(20)]

    assert len(set(answers)) == 1


@pytest.mark.parametrize(
    "corridor,country,expected",
    [
        (CORRIDOR, COUNTRY_REGIME, JurisdictionType.CORRIDOR),
        (None, COUNTRY_REGIME, JurisdictionType.COUNTRY),
        (None, None, JurisdictionType.FRAMEWORK),
    ],
    ids=["corridor", "country", "framework"],
)
async def test_the_resolved_rung_is_stable_across_repeats(corridor, country, expected):
    """Determinism at the boundary, per rung."""
    lookup = _lookup(FRAMEWORK_ROW, COUNTRY_ROW, CORRIDOR_ROW)

    answers = [await lookup.resolve(SECTOR, corridor, country, AS_OF) for _ in range(20)]

    assert len(set(answers)) == 1
    assert answers[0].resolving_jurisdiction.type is expected


# ── Case F — the jurisdiction reaches the action set ──────────────────────────


class _ListRepository:
    def __init__(self, rules: list[ComplianceRule]) -> None:
        self._rules = rules

    async def list_rules(self) -> list[ComplianceRule]:
        return list(self._rules)


def _dnfbp_rule() -> ComplianceRule:
    return ComplianceRule(
        rule_id="DNFBP_EDD_REQUIRED",
        description="edd for designated sectors",
        sector_risk_tier_match=RiskTier.ELEVATED,
        sector_classification_label_match="BSA_DPMS",
        required_action=RequiredAction.EDD_REQUIRED,
        action_reason="Designated sector requires enhanced due diligence.",
        effective_from=date(2024, 1, 1),
    )


async def _action_set_for(resolved):
    facts = ComplianceFacts(
        send_amount_minor=1_000_00,
        send_asset_code="USD",
        as_of_date=AS_OF,
        sector_risk_tier=resolved.risk_tier,
        classification_label=resolved.classification_label,
    )
    return await evaluate_settlement_compliance(
        facts,
        _ListRepository([_dnfbp_rule()]),
        resolving_jurisdiction=resolved.resolving_jurisdiction,
    )


async def test_the_resolved_country_jurisdiction_reaches_the_action_set():
    """The regression this phase exists to prevent.

    The retired stub reported ``framework``/``FATF`` no matter which authority
    actually answered. Here a country rule wins, and the action set must name
    *that* regime — otherwise a settlement escalated by FinCEN's rating would be
    recorded as escalated by FATF's.
    """
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW).resolve(
        SECTOR, None, COUNTRY_REGIME, AS_OF
    )

    actions = await _action_set_for(resolved)

    assert actions.edd_required is True
    assert actions.edd_trigger_rule == "DNFBP_EDD_REQUIRED"
    assert actions.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert actions.resolving_jurisdiction.value == COUNTRY_REGIME


async def test_the_action_set_jurisdiction_is_the_one_the_registry_resolved():
    """Corridor this time, to show the action set follows the resolution rather
    than any fixed rung."""
    resolved = await _lookup(FRAMEWORK_ROW, COUNTRY_ROW, CORRIDOR_ROW).resolve(
        SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF
    )

    actions = await _action_set_for(resolved)

    assert actions.resolving_jurisdiction.type is JurisdictionType.CORRIDOR
    assert actions.resolving_jurisdiction.value == CORRIDOR


async def test_a_not_found_classification_carries_no_jurisdiction_into_the_action_set():
    resolved = await _lookup(sectors=[]).resolve(SECTOR, CORRIDOR, COUNTRY_REGIME, AS_OF)

    actions = await _action_set_for(resolved)

    assert actions.resolving_jurisdiction is None
    assert actions.edd_required is False
