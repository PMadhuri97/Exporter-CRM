"""Shared psycopg2 helpers for compliance integration tests.

Raw SQL on purpose: the suites using this verify database-level guarantees on the
purpose-code registry. Inserting through the ORM would prove only that SQLAlchemy
declares a constraint, not that Postgres enforces one.

The test database is shared across a whole run and is never reset, so every helper
mints its own codes and no test may assume an empty table.
"""
from __future__ import annotations

import uuid


def pg_connect():
    import psycopg2

    from app.platform.configuration.config import get_settings

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def unique_code(prefix: str) -> str:
    """A canonical/external code no other test or seed file will collide with.

    Capped at 50 characters to stay inside the column width — a truncation error
    would masquerade as the constraint failure the caller is trying to observe.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"[:50]


INSERT_CANONICAL_SQL = """
    INSERT INTO compliance.purpose_code_canonical
        (id, canonical_code, description, category, effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


def canonical_params(
    canonical_code: str,
    *,
    category: str = "other",
    effective_from: str = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        canonical_code,
        "constraint-test fixture row",
        category,
        effective_from,
        effective_to,
    )


INSERT_MAPPING_SQL = """
    INSERT INTO compliance.purpose_code_corridor_mapping
        (id, canonical_code, corridor_id, external_standard, external_standard_version,
         external_code, effective_from, effective_to)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

#: The standard revision most tests do not care about. Named rather than repeated
#: so a test that *is* about versioning stands out by passing its own.
DEFAULT_STANDARD_VERSION = "RBI Purpose Code Master Circular 2024"


def mapping_params(
    canonical_code: str,
    *,
    corridor_id: str,
    external_standard: str = "RBI",
    external_standard_version: str = DEFAULT_STANDARD_VERSION,
    external_code: str,
    effective_from: str = "2024-01-01",
    effective_to: str | None = None,
):
    return (
        str(uuid.uuid4()),
        canonical_code,
        corridor_id,
        external_standard,
        external_standard_version,
        external_code,
        effective_from,
        effective_to,
    )
