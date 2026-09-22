"""Database-level constraint violation suite for the sector registry.

Raw SQL on purpose (BUILD.md #12): inserting through the ORM would prove only
that SQLAlchemy declares a constraint, not that Postgres enforces one. Every
constraint the migration creates is violated here and asserted rejected, and the
boundary of each is exercised alongside it — a constraint that rejects
everything is as broken as one that rejects nothing.

The exclusion constraints get the most attention because they are why this
schema was revised. A unique key on ``effective_from`` permits two rows with
different start dates whose periods overlap, leaving two conflicting risk tiers
in force on one date; only an exclusion over ``daterange`` rejects that.

The test database is shared across a whole run and is never reset, so every test
mints its own codes and none may assume an empty table.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from app.modules.compliance.domain.entities.sector_registry import JurisdictionType, RiskTier
from app.modules.compliance.tests.integration._helpers import pg_connect, unique_code

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"
NOT_NULL_VIOLATION = "23502"
INVALID_TEXT_REPRESENTATION = "22P02"
EXCLUSION_VIOLATION = "23P01"
#: Raised by assert_sector_code_registry_immutable_fields().
ANER_IMMUTABLE = "ANER3"

INSERT_SECTOR_SQL = """
    INSERT INTO compliance.sector_code_registry
        (id, sector_code, description, effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s)
"""

INSERT_MAPPING_SQL = """
    INSERT INTO compliance.sector_code_external_mapping
        (id, sector_code, external_standard, external_standard_version, external_code,
         effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

INSERT_CLASSIFICATION_SQL = """
    INSERT INTO compliance.sector_risk_classification
        (id, sector_code, jurisdiction_type, jurisdiction_value, risk_tier,
         classification_label, notes, effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def sector_params(
    sector_code: str,
    *,
    effective_from: str = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        sector_code,
        "constraint-test fixture row",
        effective_from,
        effective_to,
    )


def mapping_params(
    sector_code: str,
    *,
    external_standard: str = "ISIC",
    external_standard_version: str | None = "ISIC Rev.4",
    external_code: str = "4649",
    effective_from: str = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        sector_code,
        external_standard,
        external_standard_version,
        external_code,
        effective_from,
        effective_to,
    )


def classification_params(
    sector_code: str,
    *,
    jurisdiction_type: str | None = "framework",
    jurisdiction_value: str | None = "FATF",
    risk_tier: str = "high",
    classification_label: str | None = "DNFBP",
    notes: str | None = "constraint-test fixture row",
    effective_from: str = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        sector_code,
        jurisdiction_type,
        jurisdiction_value,
        risk_tier,
        classification_label,
        notes,
        effective_from,
        effective_to,
    )


@pytest.fixture
def cursor():
    """A cursor on an explicit transaction that is always rolled back.

    Yielded rather than returned so the rollback still happens when a test fails
    mid-transaction — a constraint violation leaves the connection in an aborted
    state, and an un-rolled-back connection would hold locks for the rest of the
    session.
    """
    conn = pg_connect()
    try:
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


# ── btree_gist ────────────────────────────────────────────────────────────────


def test_btree_gist_extension_is_installed(cursor):
    """The exclusion constraints need it: a GiST index cannot carry the plain
    equality columns alongside the range without it, so the migration would fail
    at ADD CONSTRAINT on any database where it was missing."""
    cursor.execute("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")

    assert cursor.fetchone()[0] == 1


# ── ex_sector_risk_classification_period ──────────────────────────────────────


def test_overlapping_classification_periods_are_rejected(cursor):
    """Expect: ERROR - conflicting key value violates exclusion constraint
    "ex_sector_risk_classification_period".

    The reason this schema was revised. Both rows are for the same sector and
    authority with *different* start dates, so the old unique key on
    (sector_code, jurisdiction, effective_from) accepted them — leaving two risk
    tiers in force on every date in 2025.
    """
    code = unique_code("OVERLAP")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_CLASSIFICATION_SQL,
        classification_params(code, effective_from="2024-01-01", effective_to="2026-01-01"),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL,
            classification_params(
                code, risk_tier="critical", effective_from="2025-01-01", effective_to="2027-01-01"
            ),
        )

    assert exc.value.pgcode == EXCLUSION_VIOLATION
    assert "ex_sector_risk_classification_period" in str(exc.value)


def test_open_ended_classification_blocks_a_later_overlapping_row(cursor):
    """A NULL effective_to is an unbounded range, so anything starting after it
    overlaps. Without this, closing a rating would be optional and two open rows
    could coexist."""
    code = unique_code("OPEN_OVERLAP")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_CLASSIFICATION_SQL, classification_params(code, effective_from="2024-01-01")
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, effective_from="2025-06-01")
        )

    assert exc.value.pgcode == EXCLUSION_VIOLATION


def test_adjacent_classification_periods_are_allowed(cursor):
    """The boundary of the exclusion, and the reason the range is '[)'. One
    rating ending the day the next begins is a supersession, not a conflict —
    rejecting it would make re-rating a sector impossible."""
    code = unique_code("ADJACENT")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_CLASSIFICATION_SQL,
        classification_params(code, effective_from="2024-01-01", effective_to="2025-01-01"),
    )
    cursor.execute(
        INSERT_CLASSIFICATION_SQL,
        classification_params(code, risk_tier="critical", effective_from="2025-01-01"),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_risk_classification WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == 2


def test_same_period_under_a_different_jurisdiction_type_is_allowed(cursor):
    """jurisdiction_type is part of the exclusion key. A corridor rule and a
    framework rule are meant to coexist and be ordered by precedence — the whole
    point of the three-tier ladder."""
    code = unique_code("TYPES")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    for jtype, jvalue in (
        ("framework", "FATF"),
        ("country", "US_FINCEN"),
        ("corridor", "US_IN"),
    ):
        cursor.execute(
            INSERT_CLASSIFICATION_SQL,
            classification_params(code, jurisdiction_type=jtype, jurisdiction_value=jvalue),
        )

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_risk_classification WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == 3


def test_same_period_for_a_different_country_is_allowed(cursor):
    """Two national regulators rating one sector over the same period is normal;
    they are different authorities, not a conflict."""
    code = unique_code("COUNTRIES")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    for value in ("US_FINCEN", "IN_RBI", "AE_CBUAE", "IFSCA"):
        cursor.execute(
            INSERT_CLASSIFICATION_SQL,
            classification_params(code, jurisdiction_type="country", jurisdiction_value=value),
        )

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_risk_classification WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == 4


# ── ex_sector_code_external_mapping_period ────────────────────────────────────


def test_overlapping_external_mapping_periods_are_rejected(cursor):
    """Two codings of one sector under the same standard revision cannot both be
    in force: a regulatory report would have no basis to choose."""
    code = unique_code("MAP_OVERLAP")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, effective_from="2024-01-01", effective_to="2026-01-01"),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_MAPPING_SQL,
            mapping_params(code, external_code="4662", effective_from="2025-01-01"),
        )

    assert exc.value.pgcode == EXCLUSION_VIOLATION
    assert "ex_sector_code_external_mapping_period" in str(exc.value)


def test_two_revisions_of_one_standard_may_overlap(cursor):
    """external_standard_version is inside the exclusion key on purpose. ISIC
    Rev.3 and Rev.4 are different codings of the same sector and may both be
    mapped; only two rows for the *same* revision conflict."""
    code = unique_code("REVISIONS")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_MAPPING_SQL, mapping_params(code, external_standard_version="ISIC Rev.3")
    )
    cursor.execute(
        INSERT_MAPPING_SQL, mapping_params(code, external_standard_version="ISIC Rev.4")
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_code_external_mapping WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == 2


def test_different_standards_may_overlap(cursor):
    """A sector is coded under ISIC, NIC and NAICS at once — that is what the
    table exists for, and what the old isic_code column could not express."""
    code = unique_code("STANDARDS")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code, effective_from="2020-01-01"))
    for standard, version, value in (
        ("ISIC", "ISIC Rev.4", "4649"),
        ("NIC", "NIC-2008", "46693"),
        ("NAICS", "NAICS 2022", "423940"),
        ("NACE", "NACE Rev.2", "46.72"),
    ):
        cursor.execute(
            INSERT_MAPPING_SQL,
            mapping_params(
                code,
                external_standard=standard,
                external_standard_version=version,
                external_code=value,
            ),
        )

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_code_external_mapping WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == 4


# ── effective_from immutability trigger ───────────────────────────────────────


def test_effective_from_cannot_be_changed(cursor):
    """Moving the date a sector started silently rewrites which historical
    payments were in scope for its classifications."""
    code = unique_code("IMMUTABLE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "UPDATE compliance.sector_code_registry SET effective_from = %s "
            "WHERE sector_code = %s",
            ("2020-01-01", code),
        )

    assert exc.value.pgcode == ANER_IMMUTABLE
    assert "effective_from is immutable" in str(exc.value)


def test_sector_code_cannot_be_changed(cursor):
    """Renaming in place would repoint every mapping and classification through
    the foreign key without any of them being touched."""
    code = unique_code("RENAME")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "UPDATE compliance.sector_code_registry SET sector_code = %s WHERE sector_code = %s",
            (unique_code("RENAMED"), code),
        )

    assert exc.value.pgcode == ANER_IMMUTABLE


def test_effective_to_can_be_changed(cursor):
    """The boundary of the trigger: closing a sector is the one legitimate
    update, which is why public.prevent_mutation() would be too strong here."""
    code = unique_code("CLOSEABLE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    cursor.execute(
        "UPDATE compliance.sector_code_registry SET effective_to = %s WHERE sector_code = %s",
        ("2027-01-01", code),
    )

    cursor.execute(
        "SELECT effective_to FROM compliance.sector_code_registry WHERE sector_code = %s", (code,)
    )
    assert str(cursor.fetchone()[0]) == "2027-01-01"


# ── enums ─────────────────────────────────────────────────────────────────────


def test_jurisdiction_type_must_be_a_known_type(cursor):
    """An unrecognised type must fail the load rather than land in the registry
    as an authority the resolution ladder cannot rank."""
    code = unique_code("BAD_JTYPE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, jurisdiction_type="continent")
        )

    assert exc.value.pgcode == INVALID_TEXT_REPRESENTATION
    assert "jurisdiction_type_enum" in str(exc.value)


@pytest.mark.parametrize("jurisdiction_type", [t.value for t in JurisdictionType])
def test_every_declared_jurisdiction_type_is_accepted(cursor, jurisdiction_type):
    """All three members the domain declares must exist in the database type. A
    type added in Python but not in a migration would fail only when a regulator
    first used it."""
    code = unique_code("JTYPE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(
        INSERT_CLASSIFICATION_SQL,
        classification_params(code, jurisdiction_type=jurisdiction_type),
    )

    cursor.execute(
        "SELECT jurisdiction_type FROM compliance.sector_risk_classification "
        "WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == jurisdiction_type


def test_risk_tier_must_be_a_known_tier(cursor):
    code = unique_code("BAD_TIER")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, risk_tier="catastrophic")
        )

    assert exc.value.pgcode == INVALID_TEXT_REPRESENTATION
    assert "sector_risk_tier_enum" in str(exc.value)


@pytest.mark.parametrize("tier", [t.value for t in RiskTier])
def test_every_declared_risk_tier_is_accepted(cursor, tier):
    code = unique_code("TIER")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(INSERT_CLASSIFICATION_SQL, classification_params(code, risk_tier=tier))

    cursor.execute(
        "SELECT risk_tier FROM compliance.sector_risk_classification WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == tier


# ── uq_sector_code_registry_sector_code ───────────────────────────────────────


def test_sector_code_must_be_unique(cursor):
    """sector_code is the target of both child foreign keys and the key
    customers are matched on."""
    code = unique_code("DUPE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    assert exc.value.pgcode == UNIQUE_VIOLATION
    assert "uq_sector_code_registry_sector_code" in str(exc.value)


# ── check constraints ─────────────────────────────────────────────────────────


def test_sector_period_must_not_end_before_it_starts(cursor):
    """A backwards window makes the row permanently unmatchable, so the sector
    silently disappears rather than failing loudly."""
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_SECTOR_SQL,
            sector_params(
                unique_code("BACK"), effective_from="2024-01-01", effective_to="2023-01-01"
            ),
        )

    assert exc.value.pgcode == CHECK_VIOLATION
    assert "ck_sector_code_registry_period" in str(exc.value)


def test_sector_period_must_not_start_and_end_on_the_same_day(cursor):
    """The window is half-open, so a same-day row is in force for zero days."""
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_SECTOR_SQL,
            sector_params(
                unique_code("ZERO"), effective_from="2024-01-01", effective_to="2024-01-01"
            ),
        )

    assert exc.value.pgcode == CHECK_VIOLATION


def test_sector_code_must_be_upper_case(cursor):
    """A lower-case code satisfies every other constraint and is then never
    found by the exact-match lookup."""
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_SECTOR_SQL, sector_params(unique_code("lower").lower()))

    assert exc.value.pgcode == CHECK_VIOLATION
    assert "ck_sector_code_registry_sector_code_upper" in str(exc.value)


def test_jurisdiction_value_must_be_upper_case(cursor):
    """A row stored as 'fatf' is never matched by the framework tier, dropping
    every unmapped jurisdiction to the standard rating."""
    code = unique_code("JCASE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, jurisdiction_value="fatf")
        )

    assert exc.value.pgcode == CHECK_VIOLATION
    assert "ck_sector_risk_classification_jurisdiction_upper" in str(exc.value)


def test_external_standard_must_be_upper_case(cursor):
    code = unique_code("SCASE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_MAPPING_SQL, mapping_params(code, external_standard="isic"))

    assert exc.value.pgcode == CHECK_VIOLATION
    assert "ck_sector_code_external_mapping_standard_upper" in str(exc.value)


def test_external_standard_version_keeps_its_published_casing(cursor):
    """The boundary of the constraint above. Only the standard *name* is
    normalised — 'ISIC Rev.4' is a published label, and upper-casing it would
    change what the platform reports to a regulator."""
    code = unique_code("VERSION_CASE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL, mapping_params(code, external_standard_version="ISIC Rev.4")
    )

    cursor.execute(
        "SELECT external_standard_version FROM compliance.sector_code_external_mapping "
        "WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] == "ISIC Rev.4"


# ── foreign keys (ON DELETE RESTRICT) ─────────────────────────────────────────


def test_classification_cannot_reference_an_unknown_sector(cursor):
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_CLASSIFICATION_SQL, classification_params(unique_code("GHOST")))

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION
    assert "fk_sector_risk_classification_sector_code" in str(exc.value)


def test_external_mapping_cannot_reference_an_unknown_sector(cursor):
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_MAPPING_SQL, mapping_params(unique_code("GHOST")))

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION
    assert "fk_sector_code_external_mapping_sector_code" in str(exc.value)


def test_sector_referenced_by_a_classification_cannot_be_deleted(cursor):
    """Why the seed loader deletes both children before the parent."""
    code = unique_code("REF_CLASS")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(INSERT_CLASSIFICATION_SQL, classification_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "DELETE FROM compliance.sector_code_registry WHERE sector_code = %s", (code,)
        )

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION


def test_sector_referenced_by_an_external_mapping_cannot_be_deleted(cursor):
    """The second child, which the previous schema did not have — deleting the
    classifications alone is no longer enough to free the parent."""
    code = unique_code("REF_MAP")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(INSERT_MAPPING_SQL, mapping_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "DELETE FROM compliance.sector_code_registry WHERE sector_code = %s", (code,)
        )

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION
    assert "sector_code_external_mapping" in str(exc.value)


def test_unreferenced_sector_can_be_deleted(cursor):
    """The boundary of RESTRICT, and the ordering the seed loader relies on."""
    code = unique_code("UNREF")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(INSERT_CLASSIFICATION_SQL, classification_params(code))
    cursor.execute(INSERT_MAPPING_SQL, mapping_params(code))

    cursor.execute(
        "DELETE FROM compliance.sector_risk_classification WHERE sector_code = %s", (code,)
    )
    cursor.execute(
        "DELETE FROM compliance.sector_code_external_mapping WHERE sector_code = %s", (code,)
    )
    cursor.execute("DELETE FROM compliance.sector_code_registry WHERE sector_code = %s", (code,))

    cursor.execute(
        "SELECT count(*) FROM compliance.sector_code_registry WHERE sector_code = %s", (code,)
    )
    assert cursor.fetchone()[0] == 0


# ── NOT NULL and nullable columns ─────────────────────────────────────────────


def test_classification_jurisdiction_type_is_required(cursor):
    """Without a type the row cannot be ranked by the resolution ladder."""
    code = unique_code("NO_JTYPE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, jurisdiction_type=None)
        )

    assert exc.value.pgcode == NOT_NULL_VIOLATION


def test_classification_jurisdiction_value_is_required(cursor):
    code = unique_code("NO_JVALUE")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CLASSIFICATION_SQL, classification_params(code, jurisdiction_value=None)
        )

    assert exc.value.pgcode == NOT_NULL_VIOLATION


def test_external_standard_version_is_required(cursor):
    """A code without its revision is ambiguous, so the column cannot be null."""
    code = unique_code("NO_VERSION")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_MAPPING_SQL, mapping_params(code, external_standard_version=None))

    assert exc.value.pgcode == NOT_NULL_VIOLATION


def test_classification_label_may_be_null(cursor):
    """A regime may rate a sector without publishing a label for it."""
    code = unique_code("NULL_LABEL")
    cursor.execute(INSERT_SECTOR_SQL, sector_params(code))
    cursor.execute(
        INSERT_CLASSIFICATION_SQL,
        classification_params(code, risk_tier="elevated", classification_label=None),
    )

    cursor.execute(
        "SELECT classification_label FROM compliance.sector_risk_classification "
        "WHERE sector_code = %s",
        (code,),
    )
    assert cursor.fetchone()[0] is None
