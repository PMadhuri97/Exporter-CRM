"""The Walk-phase seed data says what the ticket says it says.

Reference data is edited by hand and reviewed as YAML, so the rows are asserted
here rather than only through the loader. A regulator label silently dropped
from risk-classifications.yaml would otherwise change screening outcomes with
nothing in the diff to catch it.

Two absences are asserted as deliberately as the presences. An unverified
country rating and a guessed external code are both worse than nothing, and a
test is the only thing that stops one being added without the review that was
supposed to precede it.
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from app.modules.compliance.domain.entities.sector_registry import JurisdictionType, RiskTier
from app.modules.compliance.infrastructure.sector_registry_seed_loader import SEED_DATA_DIR

SECTOR = "PRECIOUS_STONES_TRADE"


def _load(name: str) -> list[dict]:
    return yaml.safe_load((SEED_DATA_DIR / name).read_text()) or []


@pytest.fixture(scope="module")
def sectors() -> list[dict]:
    return _load("sector-codes.yaml")


@pytest.fixture(scope="module")
def mappings() -> list[dict]:
    return _load("external-mappings.yaml")


@pytest.fixture(scope="module")
def classifications() -> list[dict]:
    return _load("risk-classifications.yaml")


def test_seed_directory_has_all_three_files():
    """The loader resolves this path by walking up from its own file, so a moved
    module breaks the boot silently unless something asserts the path."""
    assert SEED_DATA_DIR.is_dir()
    for name in ("sector-codes.yaml", "external-mappings.yaml", "risk-classifications.yaml"):
        assert (SEED_DATA_DIR / name).is_file(), name


# ── sector_code_registry ──────────────────────────────────────────────────────


def test_precious_stones_trade_is_registered(sectors):
    row = next(s for s in sectors if s["sector_code"] == SECTOR)

    assert row["description"] == "Wholesale trade in diamonds, precious metals, and gemstones"
    assert row.get("effective_to") is None


def test_no_sector_carries_an_external_code(sectors):
    """The change this revision exists for. An external code on the registry is
    the coupling that forced a schema change per corridor."""
    for row in sectors:
        assert "isic_code" not in row, row["sector_code"]
        assert "external_code" not in row, row["sector_code"]


def test_every_sector_code_is_unique(sectors):
    codes = [s["sector_code"] for s in sectors]

    assert len(codes) == len(set(codes))


def test_every_sector_declares_a_start_date(sectors):
    for row in sectors:
        assert isinstance(row.get("effective_from"), date), row["sector_code"]


# ── sector_code_external_mapping ──────────────────────────────────────────────


def test_isic_rev4_mapping_is_seeded(mappings):
    row = next(
        m for m in mappings if m["sector_code"] == SECTOR and m["external_standard"] == "ISIC"
    )

    assert row["external_standard_version"] == "ISIC Rev.4"
    assert row["external_code"] == "4649"


def test_external_codes_and_versions_are_quoted(mappings):
    """YAML reads a bare 4649 as an integer and both columns are VARCHAR. The
    loader coerces, but quoting is the first line of defence and easy to lose."""
    for row in mappings:
        assert isinstance(row["external_code"], str), row
        assert isinstance(row["external_standard_version"], str), row


def test_every_mapping_declares_its_standard_version(mappings):
    """A code without its revision cannot be interpreted by the regulator
    receiving it, so the column is NOT NULL and the seed must supply it."""
    for row in mappings:
        assert row.get("external_standard_version"), row


def test_no_two_mappings_share_a_sector_standard_and_version(mappings):
    """ex_sector_code_external_mapping_period would reject the overlap at boot;
    failing here names the offending file instead."""
    keys = [
        (m["sector_code"], m["external_standard"], m["external_standard_version"])
        for m in mappings
    ]

    assert len(keys) == len(set(keys))


def test_nic_and_naics_are_not_guessed(mappings):
    """Both are pending the reference-data request. get_sector_external_code
    returns None for an unmapped standard, so a report that needs one fails
    visibly rather than filing an invented code with a regulator."""
    seeded = {m["external_standard"] for m in mappings}

    assert "NIC" not in seeded
    assert "NAICS" not in seeded


# ── sector_risk_classification ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("jurisdiction_type", "jurisdiction_value"),
    [("framework", "FATF"), ("country", "US_FINCEN")],
)
def test_walk_phase_classification(classifications, jurisdiction_type, jurisdiction_value):
    """The two rows the ticket ships. Both rate the sector high/DNFBP."""
    row = next(
        c
        for c in classifications
        if c["sector_code"] == SECTOR
        and c["jurisdiction_type"] == jurisdiction_type
        and c["jurisdiction_value"] == jurisdiction_value
    )

    assert row["risk_tier"] == "high"
    assert row["classification_label"] == "DNFBP"


def test_in_rbi_is_not_shipped_unverified(classifications):
    """The prior version shipped a placeholder tier of ``elevated`` for IN_RBI
    that nobody had verified. With no row, resolution falls through to the FATF
    framework tier — a documented international position. A guessed row instead
    asserts that India's regulator holds a view it may not hold, at country
    tier, which outranks FATF."""
    assert not any(c["jurisdiction_value"] == "IN_RBI" for c in classifications)


def test_every_jurisdiction_type_is_a_known_type(classifications):
    valid = {t.value for t in JurisdictionType}

    for row in classifications:
        assert row["jurisdiction_type"] in valid, row


def test_every_risk_tier_is_a_known_tier(classifications):
    valid = {t.value for t in RiskTier}

    for row in classifications:
        assert row["risk_tier"] in valid, row


def test_dnfbp_is_never_asserted_without_an_authority(classifications):
    """DNFBP is FATF's label, not a universal category. Any row carrying it must
    name the authority that says so — that separation is the point of the
    ticket."""
    for row in classifications:
        if row.get("classification_label") == "DNFBP":
            assert row["jurisdiction_type"]
            assert row["jurisdiction_value"]


def test_every_classification_explains_itself(classifications):
    """notes carries why a regime rates a sector as it does. An unexplained
    classification cannot be reviewed by whoever inherits it."""
    for row in classifications:
        assert row.get("notes"), row


def test_no_two_classifications_share_a_sector_and_authority(classifications):
    """ex_sector_risk_classification_period rejects overlapping periods for one
    authority; since every seeded row is open-ended, one row per authority is
    the only shape that loads."""
    keys = [
        (c["sector_code"], c["jurisdiction_type"], c["jurisdiction_value"])
        for c in classifications
    ]

    assert len(keys) == len(set(keys))


def test_a_framework_classification_exists_for_every_classified_sector(classifications):
    """The resolution ladder terminates at the framework tier. A sector rated
    only by one national regulator resolves to the unmatched baseline
    everywhere else, which is a quiet under-escalation rather than an error."""
    by_sector: dict[str, set[str]] = {}
    for row in classifications:
        by_sector.setdefault(row["sector_code"], set()).add(row["jurisdiction_type"])

    for sector_code, types in by_sector.items():
        assert JurisdictionType.FRAMEWORK.value in types, sector_code


# ── cross-file integrity ──────────────────────────────────────────────────────


def test_every_child_row_references_a_registered_sector(sectors, mappings, classifications):
    """Both foreign keys would reject this at boot. Catching it here points at
    the YAML rather than at the transaction."""
    registered = {s["sector_code"] for s in sectors}

    for row in mappings + classifications:
        assert row["sector_code"] in registered, row


def test_seeded_identifiers_are_upper_case(sectors, mappings, classifications):
    """The loader upper-cases these on the way in and CHECK constraints enforce
    it, but the seed files are the reviewable artefact — two spellings of FATF
    in one file is a reviewer's problem before it is a database's.

    external_standard_version is excluded on purpose: 'ISIC Rev.4' is a
    published label, not an identifier the platform matches on.
    """
    for row in sectors:
        assert row["sector_code"] == row["sector_code"].upper(), row

    for row in mappings:
        assert row["sector_code"] == row["sector_code"].upper(), row
        assert row["external_standard"] == row["external_standard"].upper(), row

    for row in classifications:
        assert row["sector_code"] == row["sector_code"].upper(), row
        assert row["jurisdiction_value"] == row["jurisdiction_value"].upper(), row


def test_no_window_is_inverted(sectors, mappings, classifications):
    """ck_*_period on all three tables."""
    for row in sectors + mappings + classifications:
        if row.get("effective_to") is not None:
            assert row["effective_to"] > row["effective_from"], row
