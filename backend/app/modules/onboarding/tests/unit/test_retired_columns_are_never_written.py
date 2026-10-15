"""A retired column stays on its table but out of the ORM, so this release never names it.

A column is dropped one release after the code stops writing it: while a deploy replaces
the instances, the old release keeps serving against the new schema. ``deferred`` is
not enough to stop writing — the ORM still inserts an explicit ``NULL`` into every mapped
nullable column that has no default — so a retired column is declared on the table (the
metadata keeps matching the database) and left out of the mapping
(``exclude_properties``). Then a later migration can drop it under this release.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers

from app.modules.onboarding.domain.entities import (
    ExporterGstin,
    ExporterProfile,
    VerificationResult,
)

RETIRED = [
    (ExporterProfile, "relationship_manager"),
    (ExporterGstin, "address"),
    (VerificationResult, "evidence_reference"),
    (VerificationResult, "reviewed_by"),
    (VerificationResult, "review_status"),
]


@pytest.fixture(scope="module", autouse=True)
def _mappers() -> None:
    configure_mappers()


@pytest.mark.parametrize(("entity", "column"), RETIRED, ids=[c for _, c in RETIRED])
def test_a_retired_column_is_on_the_table_but_not_mapped(entity, column):
    assert column in entity.__table__.c
    assert column not in entity.__mapper__.columns
    assert not hasattr(entity, column)


@pytest.mark.parametrize(("entity", "column"), RETIRED, ids=[c for _, c in RETIRED])
def test_the_orm_never_names_a_retired_column(entity, column):
    # What the unit of work inserts: every mapped column it writes NULL into when unset.
    assert column not in entity.__mapper__._insert_cols_as_none[entity.__table__]
    # What an ORM read or write renders: the name as a whole word (`address`, not
    # `address_id`).
    named = re.compile(rf"\b{column}\b")
    dialect = postgresql.dialect()
    every_column = {c.key: None for c in entity.__mapper__.columns}
    statements = (
        select(entity),
        insert(entity).values(every_column),
        update(entity).values(every_column),
    )
    for statement in statements:
        assert not named.search(str(statement.compile(dialect=dialect)))
