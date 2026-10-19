"""A contact's first and last name, kept apart

``exporter_contact`` gains ``first_name`` (required) and ``last_name`` (optional: plenty
of people go by one name). ``name`` stays an ordinary column in this release, kept equal
to the two by a trigger, so the release still serving during the deploy — which writes
``name`` and knows nothing of the parts — keeps adding and renaming contacts (including
the ones made from a deal's buyer details) without error:

* a write that sets the parts (this release) has ``name`` rebuilt from them;
* a write that sets only ``name`` (the old release) has the parts split from it.

Making ``name`` a computed column (``GENERATED ALWAYS ... STORED``) is left to a later
release, once nothing that writes ``name`` is still serving — the same split as the
column drops in 0060 and 0061. That migration drops the trigger and both functions.

Splitting a full name: a leading title (``Dr.``, ``Mr``, ``Shri`` …) stays with the
first name, and the last word is the last name — "Priya Ramesh Iyer" becomes "Priya
Ramesh" and "Iyer", "Dr. A. P. J. Kalam" becomes "Dr. A. P. J." and "Kalam", and a
single word (or a title and one word) is a first name with no last name. A contact made
from a deal's buyer details is named after the buyer company, not a person, so its whole
name goes into ``first_name``. A blank name — never accepted by the API, only left by
old test data — becomes "Unnamed contact", so ``first_name`` is never empty.

Revision ID: onboarding_0062_contact_names
Revises: onboarding_0061_drop_columns
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0062_contact_names"
down_revision: str | None = "onboarding_0061_drop_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_contact"
#: ``company_directory.BUYER_CONTACT_ROLE``, copied so the migration does not move with it.
BUYER_CONTACT_ROLE = "Buyer contact, from the deal's buyer details"
BLANK_NAME = "Unnamed contact"
_BUYER_ROLE_SQL = BUYER_CONTACT_ROLE.replace("'", "''")

#: The parts of a full name. Spaces are collapsed first, so "Priya  Iyer" splits the
#: same as "Priya Iyer". Titles are matched with or without the full stop.
_SPLIT_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.exporter_contact_name_parts(
    full_name text, contact_role text, OUT first_name text, OUT last_name text
) AS $func$
DECLARE
    clean text := regexp_replace(btrim(coalesce(full_name, '')), '\\s+', ' ', 'g');
    words text[];
    title_words int := 0;
BEGIN
    IF clean = '' THEN
        first_name := '{BLANK_NAME}';
        RETURN;
    END IF;
    IF contact_role IS NOT DISTINCT FROM '{_BUYER_ROLE_SQL}' THEN
        first_name := clean;
        RETURN;
    END IF;
    words := string_to_array(clean, ' ');
    WHILE title_words < array_length(words, 1)
          AND lower(rtrim(words[title_words + 1], '.')) IN (
              'dr', 'mr', 'mrs', 'ms', 'miss', 'prof', 'shri', 'sri', 'smt', 'kum'
          ) LOOP
        title_words := title_words + 1;
    END LOOP;
    IF array_length(words, 1) - title_words < 2 THEN
        first_name := clean;
        RETURN;
    END IF;
    first_name := array_to_string(words[1:array_length(words, 1) - 1], ' ');
    last_name := words[array_length(words, 1)];
END
$func$ LANGUAGE plpgsql IMMUTABLE;
"""

#: Keeps ``name`` and its parts in step while both releases write the table.
_SYNC_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.exporter_contact_sync_name()
RETURNS TRIGGER AS $func$
DECLARE
    parts record;
BEGIN
    IF (TG_OP = 'INSERT' AND NEW.first_name IS NOT NULL)
       OR (TG_OP = 'UPDATE' AND (NEW.first_name IS DISTINCT FROM OLD.first_name
                                 OR NEW.last_name IS DISTINCT FROM OLD.last_name)) THEN
        NEW.name := NEW.first_name || COALESCE(' ' || NEW.last_name, '');
    ELSIF TG_OP = 'INSERT' OR NEW.name IS DISTINCT FROM OLD.name THEN
        parts := {SCHEMA}.exporter_contact_name_parts(NEW.name, NEW.role);
        NEW.first_name := parts.first_name;
        NEW.last_name := parts.last_name;
        NEW.name := NEW.first_name || COALESCE(' ' || NEW.last_name, '');
    END IF;
    RETURN NEW;
END
$func$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("first_name", sa.String(255), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("last_name", sa.String(255), nullable=True), schema=SCHEMA)
    # Room for both parts; the old release still holds itself to 255.
    op.alter_column(TABLE, "name", type_=sa.String(511), schema=SCHEMA)
    op.execute(_SPLIT_FUNCTION)
    op.execute(
        f"""
        UPDATE {SCHEMA}.{TABLE} AS c
        SET first_name = p.first_name,
            last_name = p.last_name,
            name = p.first_name || COALESCE(' ' || p.last_name, '')
        FROM {SCHEMA}.{TABLE} AS src,
             LATERAL {SCHEMA}.exporter_contact_name_parts(src.name, src.role) AS p
        WHERE c.id = src.id
        """
    )
    op.alter_column(TABLE, "first_name", nullable=False, schema=SCHEMA)
    op.execute(_SYNC_FUNCTION)
    # BEFORE, so NOT NULL on first_name is checked after the trigger has filled it.
    op.execute(
        f"""
        CREATE TRIGGER trg_exporter_contact_sync_name
        BEFORE INSERT OR UPDATE ON {SCHEMA}.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.exporter_contact_sync_name();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_exporter_contact_sync_name ON {SCHEMA}.{TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.exporter_contact_sync_name()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.exporter_contact_name_parts(text, text)")
    op.execute(f"UPDATE {SCHEMA}.{TABLE} SET name = left(name, 255)")
    op.alter_column(TABLE, "name", type_=sa.String(255), schema=SCHEMA)
    op.drop_column(TABLE, "last_name", schema=SCHEMA)
    op.drop_column(TABLE, "first_name", schema=SCHEMA)
