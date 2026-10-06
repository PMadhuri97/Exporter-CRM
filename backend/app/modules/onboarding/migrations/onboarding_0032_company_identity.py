"""Company identity and pipeline status.

Revision ID: onboarding_0032_company_identity
Revises: auth_0005_rm_role_name

``onboarding_0032_company_identity`` is 32 characters — exactly the register's limit
on ``alembic_version.version_num``, so it fits and nothing longer would.

Why
---
A company record has so far meant "an exporter we are selling to". Buyers as companies
make it mean "a company", so the same record can be a seller on one deal and a buyer on
another. Two things have to become explicit before that:

* **which registration identifies it.** An Indian company is identified by its PAN; a
  foreign one by whatever its own jurisdiction issues. "Has a PAN?" cannot stand in
  for the question, because a buyer company the migration creates may have neither
  (migrated buyers are excused), and "we do not know" must not read as "foreign".
* **whether it is in the pipeline at all.** A company that exists only because it was
  somebody's buyer is not a lead and must not appear in pipeline counts or be chased
  by sales. It is still a full company record — full-depth buyer checks screen
  and clear buyer-only companies — so this is a separate axis from the journey, not a
  new journey value.

What it adds, all on ``onboarding.exporter_profile``
---------------------------------------------------
* ``company_identity_type_enum`` and ``company_pipeline_status_enum``, both created in
  the ordinary transactional body — never ``ALTER TYPE … ADD VALUE`` in an autocommit
  block (register §2).
* ``identity_type`` (nullable), ``registration_number`` (nullable),
  ``pipeline_status`` (``NOT NULL DEFAULT 'IN_PIPELINE'``), ``created_via``,
  ``created_via_deal_id``.
* ``ExporterSource.DEAL_BUYER`` — added to the **existing**
  ``exporter_source_enum``, which is why this migration must stay transactional.
* ``ck_exporter_profile_not_in_pipeline_start``: ``NOT_IN_PIPELINE`` implies the
  journey has not started (LEAD / NOT_YET_REVIEWED / NOT_CONTACTED). In the database
  and not only in the service, because the buyer migration writes these rows directly.
* ``uq_exporter_profile_country_registration_number``: one company per
  ``(country, normalised registration_number)``. Partial — most rows are ``NULL``, and
  two companies with no number are not duplicates.
* ``ix_exporter_profile_created_via_deal_id``.

Data steps
----------
``identity_type = 'IN_PAN'`` wherever ``pan`` is already set — the only case that can
be inferred safely. Every other existing company keeps ``NULL``: the create
paths set it going forward, and backfilling a guess would make "unknown" unreadable.
``pipeline_status`` needs no backfill: the server default makes every existing company
``IN_PIPELINE``, which is what they all are.

**The check constraint is added last**, after the default has been applied, so it is
validated against rows that already satisfy it.

Rollback
--------
``pg_dump`` first. The downgrade drops the five columns, the two constraints and the
index, then the two enums it created. It **cannot** remove ``DEAL_BUYER`` from
``exporter_source_enum`` — Postgres has no ``DROP VALUE`` — so that value survives a
downgrade, harmlessly: it is simply a source nothing uses. Dropping the columns loses
every identity and pipeline fact recorded since, so downgrade only if you mean it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0032_company_identity"
down_revision: str | None = "auth_0005_rm_role_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_IDENTITY_TYPE = postgresql.ENUM(
    "IN_PAN", "FOREIGN_REG", name="company_identity_type_enum", schema=SCHEMA
)
_PIPELINE_STATUS = postgresql.ENUM(
    "IN_PIPELINE", "NOT_IN_PIPELINE", name="company_pipeline_status_enum", schema=SCHEMA
)

#: `NOT_IN_PIPELINE` means the journey has not started.
_NOT_IN_PIPELINE_START = (
    "pipeline_status <> 'NOT_IN_PIPELINE'"
    " OR (journey = 'LEAD'"
    "     AND qualification = 'NOT_YET_REVIEWED'"
    "     AND conversation = 'NOT_CONTACTED')"
)

#: Upper-cased with every non-alphanumeric stripped, so "KVK 1234-56" and "kvk123456"
#: are the same registration — which is the point of a uniqueness rule on it.
_NORMALISED = "upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))"


def upgrade() -> None:
    bind = op.get_bind()
    _IDENTITY_TYPE.create(bind, checkfirst=False)
    _PIPELINE_STATUS.create(bind, checkfirst=False)

    # `DEAL_BUYER`. In the transactional body: `ALTER TYPE … ADD VALUE` inside an autocommit
    # block has broken this repository before (register §2) — the value commits, the
    # rest of the migration does not, and `alembic_version` still names the old
    # revision. `IF NOT EXISTS` so a re-run after a failed later step is clean.
    op.execute(
        f"ALTER TYPE {SCHEMA}.exporter_source_enum ADD VALUE IF NOT EXISTS 'DEAL_BUYER';"
    )

    op.add_column(
        "exporter_profile",
        sa.Column("identity_type", _IDENTITY_TYPE, nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column(
            "pipeline_status",
            _PIPELINE_STATUS,
            nullable=False,
            server_default="IN_PIPELINE",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column("created_via", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column("created_via_deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )

    # The one identity that can be inferred: a stored PAN means an Indian company.
    # Everything else stays NULL rather than being guessed.
    op.execute(
        f"UPDATE {SCHEMA}.exporter_profile SET identity_type = 'IN_PAN'"
        " WHERE pan IS NOT NULL AND identity_type IS NULL;"
    )

    # After the default has filled `pipeline_status`, so it validates against rows
    # that already satisfy it.
    op.create_check_constraint(
        "ck_exporter_profile_not_in_pipeline_start",
        "exporter_profile",
        _NOT_IN_PIPELINE_START,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_exporter_profile_country_registration_number",
        "exporter_profile",
        ["country", sa.text(_NORMALISED)],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(
            "registration_number IS NOT NULL AND country IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_exporter_profile_created_via_deal_id",
        "exporter_profile",
        ["created_via_deal_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("created_via_deal_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exporter_profile_created_via_deal_id",
        table_name="exporter_profile",
        schema=SCHEMA,
    )
    op.drop_index(
        "uq_exporter_profile_country_registration_number",
        table_name="exporter_profile",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_exporter_profile_not_in_pipeline_start",
        "exporter_profile",
        type_="check",
        schema=SCHEMA,
    )
    for column in (
        "created_via_deal_id",
        "created_via",
        "pipeline_status",
        "registration_number",
        "identity_type",
    ):
        op.drop_column("exporter_profile", column, schema=SCHEMA)

    bind = op.get_bind()
    _PIPELINE_STATUS.drop(bind, checkfirst=False)
    _IDENTITY_TYPE.drop(bind, checkfirst=False)
    # `DEAL_BUYER` stays on `exporter_source_enum`: Postgres cannot drop an enum
    # value. Harmless — a source nothing writes.
