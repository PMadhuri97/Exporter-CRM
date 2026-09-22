"""Database-level constraint violation suite for the purpose-code registry.

BUILD.md #12: every DB constraint gets a test that violates it via direct SQL and
asserts rejection. The application never writes these tables outside the seed
loader, so the database is the only thing standing between a bad reference-data
commit and a payment leaving with the wrong regulatory code on it.

Constraints verified (migration a5b6c7d8e9f0):
  ex_purpose_code_canonical_validity      no two rows for a code with overlapping windows
  ex_purpose_code_mapping_validity        same, per (code, corridor, standard, version)
  purpose_code_mapping_canonical_fk       trigger: mapping must name a real canonical code
  purpose_code_canonical_delete_restrict  trigger: ON DELETE RESTRICT, by code value
  purpose_category_enum                   only the five listed categories
  external_standard_version NOT NULL      every mapping cites its revision
  primary keys                            surrogate ids stay distinct

Every test runs inside a single transaction that is rolled back in ``finally``.
Nothing is committed, so the GitOps-seeded reference data this database also
holds is never touched.
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from app.modules.compliance.tests.integration._helpers import (
    INSERT_CANONICAL_SQL,
    INSERT_MAPPING_SQL,
    canonical_params,
    mapping_params,
    pg_connect,
    unique_code,
)

UNIQUE_VIOLATION = "23505"
NOT_NULL_VIOLATION = "23502"
FOREIGN_KEY_VIOLATION = "23503"
EXCLUSION_VIOLATION = "23P01"

V2024 = "RBI Purpose Code Master Circular 2024"
V2025 = "RBI Purpose Code Master Circular 2025"


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


# ── ex_purpose_code_canonical_validity ────────────────────────────────────────

def test_canonical_code_windows_may_not_overlap(cursor):
    """Expect: ERROR - conflicting key value violates exclusion constraint.

    Two definitions of one code in force on the same date would make the
    point-in-time lookup a coin flip, and the losing definition might carry a
    different category.
    """
    code = unique_code("OVERLAP")
    cursor.execute(
        INSERT_CANONICAL_SQL,
        canonical_params(code, effective_from="2020-01-01", effective_to="2025-01-01"),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CANONICAL_SQL,
            canonical_params(code, effective_from="2024-01-01", effective_to="2026-01-01"),
        )

    assert exc.value.pgcode == EXCLUSION_VIOLATION
    assert "ex_purpose_code_canonical_validity" in str(exc.value)


def test_canonical_code_may_be_retired_and_reinstated(cursor):
    """Non-overlapping windows are accepted — the whole reason this is an
    exclusion constraint and not UNIQUE (canonical_code)."""
    code = unique_code("REINSTATED")
    cursor.execute(
        INSERT_CANONICAL_SQL,
        canonical_params(code, effective_from="2020-01-01", effective_to="2022-01-01"),
    )
    cursor.execute(
        INSERT_CANONICAL_SQL,
        canonical_params(code, effective_from="2024-01-01", effective_to=None),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,)
    )
    assert cursor.fetchone()[0] == 2


def test_abutting_canonical_windows_are_not_an_overlap(cursor):
    """'[)' makes effective_to exclusive, so a row ending on the day the next
    begins is exactly one row in force per date. If the range were '[]' this
    would be rejected and no code could ever be superseded cleanly."""
    code = unique_code("ABUTTING")
    cursor.execute(
        INSERT_CANONICAL_SQL,
        canonical_params(code, effective_from="2020-01-01", effective_to="2024-01-01"),
    )
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code, effective_from="2024-01-01"))

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,)
    )
    assert cursor.fetchone()[0] == 2


def test_open_ended_canonical_row_blocks_any_later_window(cursor):
    """A NULL effective_to is unbounded, not merely 'no end recorded'. Anything
    starting after an open row overlaps it, so a second definition cannot be
    slipped in without first closing the current one."""
    code = unique_code("OPEN_ENDED")
    cursor.execute(
        INSERT_CANONICAL_SQL, canonical_params(code, effective_from="2020-01-01", effective_to=None)
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code, effective_from="2030-01-01"))

    assert exc.value.pgcode == EXCLUSION_VIOLATION


def test_different_canonical_codes_may_share_a_window(cursor):
    """The boundary: the constraint keys on the code, so unrelated codes are free
    to be valid simultaneously — which is the normal case."""
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(unique_code("A")))
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(unique_code("B")))


# ── ex_purpose_code_mapping_validity ──────────────────────────────────────────

def test_mapping_windows_may_not_overlap_within_a_standard_version(cursor):
    """Expect: ERROR - conflicting key value violates exclusion constraint.

    Two external codes in force for one corridor, standard and revision on the
    same date is a reverse lookup with no answer.
    """
    code = unique_code("MAP_OVERLAP")
    corridor = unique_code("CORR")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard_version=V2024,
            external_code=unique_code("X"),
            effective_from="2024-01-01",
        ),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_MAPPING_SQL,
            mapping_params(
                code,
                corridor_id=corridor,
                external_standard_version=V2024,
                external_code=unique_code("Y"),
                effective_from="2024-06-01",
            ),
        )

    assert exc.value.pgcode == EXCLUSION_VIOLATION
    assert "ex_purpose_code_mapping_validity" in str(exc.value)


def test_a_standard_revision_may_supersede_the_previous_one(cursor):
    """Closing the old mapping and starting a new one under a later revision is
    accepted. The windows abut, so exactly one is in force on any date."""
    code = unique_code("SUPERSEDE")
    corridor = unique_code("CORR")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code, effective_from="2020-01-01"))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard_version=V2024,
            external_code="P0102",
            effective_from="2024-01-01",
            effective_to="2025-01-01",
        ),
    )
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard_version=V2025,
            external_code="P0103",
            effective_from="2025-01-01",
        ),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_corridor_mapping WHERE corridor_id = %s", (corridor,)
    )
    assert cursor.fetchone()[0] == 2


def test_two_standard_versions_may_overlap_and_the_database_allows_it(cursor):
    """Documents a gap rather than asserting a guarantee.

    external_standard_version is part of the exclusion key, so the constraint
    only prevents overlap *within* one revision. Two revisions covering the same
    corridor and date are accepted here — which is why validate_purpose_code
    still raises AmbiguousPurposeCodeMappingError rather than trusting the
    database to have made that impossible.
    """
    code = unique_code("TWO_VERSIONS")
    corridor = unique_code("CORR")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard_version=V2024,
            external_code=unique_code("X"),
            effective_from="2024-01-01",
        ),
    )
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard_version=V2025,
            external_code=unique_code("Y"),
            effective_from="2024-01-01",
        ),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_corridor_mapping WHERE corridor_id = %s", (corridor,)
    )
    assert cursor.fetchone()[0] == 2, (
        "if this now fails, the exclusion key changed and the application-level "
        "ambiguity check in validate_purpose_code may be redundant"
    )


def test_same_mapping_is_allowed_on_a_different_corridor(cursor):
    """RBI's P0102 is the same string on the US-IN and EUR-IN corridors and both
    rows must coexist — otherwise adding a corridor would be impossible, which is
    the exact scenario the registry exists to support."""
    code = unique_code("SHARED")
    external = unique_code("X")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=unique_code("C1"), external_code=external),
    )
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=unique_code("C2"), external_code=external),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_corridor_mapping WHERE external_code = %s", (external,)
    )
    assert cursor.fetchone()[0] == 2


def test_same_corridor_may_carry_two_standards_at_once(cursor):
    """A corridor can be governed by more than one external standard, and the two
    numbering schemes are independent."""
    code = unique_code("TWO_STD")
    corridor = unique_code("CORR")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code, corridor_id=corridor, external_standard="RBI", external_code=unique_code("X")
        ),
    )
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(
            code,
            corridor_id=corridor,
            external_standard="SWIFT_ISO20022",
            external_code=unique_code("Y"),
        ),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_corridor_mapping WHERE corridor_id = %s", (corridor,)
    )
    assert cursor.fetchone()[0] == 2


# ── purpose_code_mapping_canonical_fk (trigger) ───────────────────────────────

def test_mapping_cannot_reference_an_unknown_canonical_code(cursor):
    """Expect: ERROR (SQLSTATE 23503) - canonical_code does not exist.

    Enforced by trigger rather than a foreign key, because the canonical table
    has no UNIQUE (canonical_code) for a FK to point at. The SQLSTATE is the
    foreign-key one so callers cannot tell the difference.
    """
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_MAPPING_SQL,
            mapping_params(
                unique_code("GHOST"),
                corridor_id=unique_code("CORR"),
                external_code=unique_code("X"),
            ),
        )

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION
    assert "does not exist" in str(exc.value)


def test_mapping_cannot_be_updated_onto_an_unknown_canonical_code(cursor):
    """The trigger fires on UPDATE too. A FK would have covered this for free; an
    INSERT-only trigger would have left the back door open."""
    code = unique_code("REPOINT")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=unique_code("CORR"), external_code=unique_code("X")),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "UPDATE compliance.purpose_code_corridor_mapping SET canonical_code = %s "
            "WHERE canonical_code = %s",
            (unique_code("GHOST"), code),
        )

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION


# ── purpose_code_canonical_delete_restrict (trigger) ──────────────────────────

def test_referenced_canonical_code_cannot_be_deleted(cursor):
    """Expect: ERROR (SQLSTATE 23503) - still referenced.

    This is why the seed loader deletes the mapping table first, and the
    guarantee that retiring a code from canonical.yaml without retiring its
    mappings fails loudly rather than orphaning them.
    """
    code = unique_code("REFERENCED")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=unique_code("CORR"), external_code=unique_code("X")),
    )

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute("DELETE FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,))

    assert exc.value.pgcode == FOREIGN_KEY_VIOLATION
    assert "still referenced" in str(exc.value)


def test_one_of_several_canonical_rows_may_be_deleted_while_mappings_exist(cursor):
    """RESTRICT guards the code, not the row.

    With two historical rows for one code, deleting either leaves the code still
    defined, so the mappings are not orphaned and the delete is allowed. A
    row-wise FK could not express this — it is why the trigger checks for a
    surviving sibling rather than simply counting mappings.
    """
    code = unique_code("TWO_ROWS")
    cursor.execute(
        INSERT_CANONICAL_SQL,
        canonical_params(code, effective_from="2020-01-01", effective_to="2024-01-01"),
    )
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code, effective_from="2024-01-01"))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=unique_code("CORR"), external_code=unique_code("X")),
    )

    cursor.execute(
        "DELETE FROM compliance.purpose_code_canonical WHERE canonical_code = %s AND effective_to IS NOT NULL",
        (code,),
    )

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,)
    )
    assert cursor.fetchone()[0] == 1


def test_unreferenced_canonical_code_can_be_deleted(cursor):
    """The boundary of RESTRICT: drop the mapping first and the parent goes,
    which is the ordering the seed loader relies on every boot."""
    code = unique_code("UNREFERENCED")
    corridor = unique_code("CORR")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))
    cursor.execute(
        INSERT_MAPPING_SQL,
        mapping_params(code, corridor_id=corridor, external_code=unique_code("X")),
    )

    cursor.execute("DELETE FROM compliance.purpose_code_corridor_mapping WHERE corridor_id = %s", (corridor,))
    cursor.execute("DELETE FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,))

    cursor.execute(
        "SELECT count(*) FROM compliance.purpose_code_canonical WHERE canonical_code = %s", (code,)
    )
    assert cursor.fetchone()[0] == 0


# ── Column-level constraints ──────────────────────────────────────────────────

def test_category_must_be_a_known_purpose_category(cursor):
    """An unrecognised category in canonical.yaml must fail the load rather than
    land in the registry."""
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            INSERT_CANONICAL_SQL,
            canonical_params(unique_code("BAD_CAT"), category="not_a_category"),
        )

    assert "purpose_category_enum" in str(exc.value)


def test_external_standard_version_is_required(cursor):
    """Every mapping must cite the revision its code came from, or a payment
    cannot be explained to a regulator once the next revision lands."""
    code = unique_code("NO_VERSION")
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))

    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(
            "INSERT INTO compliance.purpose_code_corridor_mapping "
            "(id, canonical_code, corridor_id, external_standard, external_standard_version, "
            " external_code, effective_from) "
            "VALUES (%s, %s, %s, 'RBI', NULL, %s, '2024-01-01')",
            (str(uuid.uuid4()), code, unique_code("CORR"), unique_code("X")),
        )

    assert exc.value.pgcode == NOT_NULL_VIOLATION
    assert "external_standard_version" in str(exc.value)


def test_mapping_id_is_the_primary_key(cursor):
    """Two mapping rows may differ in every business column and still collide on
    a reused surrogate id."""
    code = unique_code("PK")
    shared_id = str(uuid.uuid4())
    cursor.execute(INSERT_CANONICAL_SQL, canonical_params(code))

    first = list(mapping_params(code, corridor_id=unique_code("C1"), external_code=unique_code("X")))
    first[0] = shared_id
    cursor.execute(INSERT_MAPPING_SQL, tuple(first))

    second = list(
        mapping_params(code, corridor_id=unique_code("C2"), external_code=unique_code("Y"))
    )
    second[0] = shared_id
    with pytest.raises(psycopg2.Error) as exc:
        cursor.execute(INSERT_MAPPING_SQL, tuple(second))

    assert exc.value.pgcode == UNIQUE_VIOLATION
