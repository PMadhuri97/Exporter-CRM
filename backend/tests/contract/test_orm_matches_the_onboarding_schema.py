"""The ORM describes the ``onboarding`` schema exactly as the migrations built it.

``alembic revision --autogenerate`` writes a migration from the difference between
``Base.metadata`` and the database. Anything a migration created but no model
declares therefore comes back as a proposal to **drop** it — and a reviewer skimming
a generated file can merge that. Before this test, the proposals included
``uq_exporter_profile_pan`` (decision 4: no two companies share a PAN) and the two
constraints that keep a company's qualification outcomes one chain
(``uq_qualification_outcome_supersedes_once``,
``uq_qualification_outcome_first_per_company``).

This runs the same comparison ``migrations/env.py`` does (``compare_type=True``),
limited to the CRM's own schema, against the database the suite runs on — which
``alembic upgrade head`` built. A new migration that adds an index or constraint
without the matching model declaration, or a model change without a migration,
fails here instead of in someone's generated file.

Alembic's comparison does not look at primary keys, ``CHECK`` constraints or server
defaults, so three more tests compare those directly with ``pg_catalog``. Before them,
12 ``CHECK`` constraints (PAN, CIN, GSTIN formats among them), a primary key and a
dozen defaults existed only in the database.

The other module schemas are out of scope on purpose: several belong to modules the
CRM may not edit (architecture §2.5), and their own drift is theirs to fix.
"""

from __future__ import annotations

import warnings

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, FetchedValue, create_engine, text
from sqlalchemy.pool import NullPool

import app.modules.onboarding.domain.entities  # noqa: F401 — registers every CRM model
from app.platform.configuration.config import get_settings
from app.platform.database.models import Base

SCHEMA = "onboarding"


def _include_name(name, type_, parent_names) -> bool:
    # Reflect only the CRM's schema; everything else is another module's.
    return name == SCHEMA if type_ == "schema" else True


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return (obj.schema or "public") == SCHEMA and name != "alembic_version"
    return True


def test_the_orm_matches_the_onboarding_schema():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, poolclass=NullPool)
    try:
        with engine.connect() as connection, warnings.catch_warnings():
            # Alembic cannot compare expression indexes (`created_at DESC`) and says
            # so with a warning per index; they are still declared, and a missing
            # one would still show up as a removed index.
            warnings.simplefilter("ignore")
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "include_schemas": True,
                    "include_name": _include_name,
                    "include_object": _include_object,
                },
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert not differences, (
        "The ORM and the onboarding schema disagree; autogenerate would emit these "
        "operations. Declare the object on its model (or write the migration):\n  "
        + "\n  ".join(repr(difference) for difference in differences)
    )


# ── What compare_metadata does not compare ──────────────────────────────────────


def _onboarding_tables():
    return [table for table in Base.metadata.tables.values() if table.schema == SCHEMA]


def _catalog(sql: str) -> dict[str, set[str]]:
    """``{table: {name, ...}}`` from a query returning ``(table, name)`` rows."""
    engine = create_engine(get_settings().DATABASE_SYNC_URL, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(sql), {"schema": SCHEMA}).all()
    finally:
        engine.dispose()
    found: dict[str, set[str]] = {}
    for table, name in rows:
        found.setdefault(table, set()).add(name)
    return found


def _disagreements(declared: dict[str, set[str]], built: dict[str, set[str]]) -> list[str]:
    return [
        f"{table}: model {sorted(declared.get(table, set()))}, "
        f"database {sorted(built.get(table, set()))}"
        for table in sorted(set(declared) | set(built))
        if declared.get(table, set()) != built.get(table, set())
    ]


def _report(heading: str, wrong: list[str]) -> str:
    return heading + ":\n  " + "\n  ".join(wrong)


def test_every_primary_key_matches():
    built = _catalog(
        "SELECT c.relname, a.attname FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)"
        " WHERE i.indisprimary AND n.nspname = :schema"
    )
    declared = {
        table.name: {column.name for column in table.primary_key.columns}
        for table in _onboarding_tables()
    }
    wrong = _disagreements(declared, built)
    assert not wrong, _report("Primary keys differ between the models and the database", wrong)


def test_every_check_constraint_is_declared():
    built = _catalog(
        "SELECT c.relname, k.conname FROM pg_constraint k"
        " JOIN pg_class c ON c.oid = k.conrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE k.contype = 'c' AND n.nspname = :schema"
    )
    declared = {
        table.name: {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint) and constraint.name
        }
        for table in _onboarding_tables()
    }
    declared = {table: names for table, names in declared.items() if names}
    wrong = _disagreements(declared, built)
    assert not wrong, _report(
        "CHECK constraints differ between the models and the database. Declare each on "
        "its model under the migration's name",
        wrong,
    )


def test_every_server_default_is_declared():
    built = _catalog(
        "SELECT c.relname, a.attname FROM pg_attrdef d"
        " JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum"
        " JOIN pg_class c ON c.oid = d.adrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = :schema AND NOT a.attisdropped"
    )
    # A bare `FetchedValue()` declares a value a trigger sets, not a column default
    # (`exporter_contact.name` until it becomes a computed column), so the database has
    # no default to match it. A real default (`DefaultClause`) or a computed column
    # (`Computed`, which Postgres keeps in `pg_attrdef`) is still compared.
    declared = {
        table.name: {
            column.name
            for column in table.columns
            if column.server_default is not None
            and type(column.server_default) is not FetchedValue
        }
        for table in _onboarding_tables()
    }
    declared = {table: names for table, names in declared.items() if names}
    wrong = _disagreements(declared, built)
    assert not wrong, _report(
        "Columns with a database default differ between the models and the database "
        "(declare `server_default=` on the column)",
        wrong,
    )
