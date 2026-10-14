"""A contact's first and last name, kept apart

``exporter_contact`` gains ``first_name`` (required) and ``last_name`` (optional: plenty
of people go by one name). ``name`` stays, as a column the database computes from the two
(``GENERATED ALWAYS ... STORED``), so every reader of the full name — history details,
deal views, sample data — reads what it always did, and no writer can make it disagree
with its parts.

Existing rows are split at the first run of whitespace: "Priya Ramesh Iyer" becomes
"Priya" and "Ramesh Iyer", and a single word becomes a first name with no last name. A
contact made from a deal's buyer details is named after the buyer company, not a person,
so its whole name goes into ``first_name``.

Revision ID: onboarding_0054_contact_names
Revises: onboarding_0053_auto_criteria
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0054_contact_names"
down_revision: str | None = "onboarding_0053_auto_criteria"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_contact"
#: ``company_directory.BUYER_CONTACT_ROLE``, copied so the migration does not move with it.
BUYER_CONTACT_ROLE = "Buyer contact, from the deal's buyer details"
FULL_NAME = "first_name || COALESCE(' ' || last_name, '')"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("first_name", sa.String(255), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("last_name", sa.String(255), nullable=True), schema=SCHEMA)
    # Spaces collapsed first, so "Priya  Iyer" splits the same as "Priya Iyer".
    op.execute(
        sa.text(
            f"""
            WITH split AS (
                SELECT id,
                       regexp_replace(btrim(name), '\\s+', ' ', 'g') AS clean,
                       role = :buyer_role AS is_buyer
                FROM {SCHEMA}.{TABLE}
            )
            UPDATE {SCHEMA}.{TABLE} AS c
            SET first_name = CASE WHEN s.is_buyer THEN s.clean
                                  ELSE split_part(s.clean, ' ', 1) END,
                last_name = CASE WHEN s.is_buyer THEN NULL
                                 ELSE NULLIF(substr(s.clean, strpos(s.clean || ' ', ' ') + 1), '')
                            END
            FROM split AS s
            WHERE c.id = s.id
            """
        ).bindparams(buyer_role=BUYER_CONTACT_ROLE)
    )
    op.alter_column(TABLE, "first_name", nullable=False, schema=SCHEMA)
    op.drop_column(TABLE, "name", schema=SCHEMA)
    op.add_column(
        TABLE,
        sa.Column("name", sa.String(511), sa.Computed(FULL_NAME, persisted=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.add_column(TABLE, sa.Column("full_name", sa.String(255), nullable=True), schema=SCHEMA)
    op.execute(f"UPDATE {SCHEMA}.{TABLE} SET full_name = left(name, 255)")
    op.drop_column(TABLE, "name", schema=SCHEMA)
    op.alter_column(
        TABLE, "full_name", new_column_name="name", nullable=False, schema=SCHEMA
    )
    op.drop_column(TABLE, "last_name", schema=SCHEMA)
    op.drop_column(TABLE, "first_name", schema=SCHEMA)
