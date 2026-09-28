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

The other module schemas are out of scope on purpose: several belong to modules the
CRM may not edit (architecture §2.5), and their own drift is theirs to fix.
"""

from __future__ import annotations

import warnings

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
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
