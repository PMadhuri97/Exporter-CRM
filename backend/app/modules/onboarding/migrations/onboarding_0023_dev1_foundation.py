"""Compliance foundation (F1): the company a verification result is about, and the
current Clear's expiry on the company — **owner: Developer 1** (allocation §3, F1).

Revision ID: onboarding_0023_dev1_foundation
Revises: onboarding_0022_integrity

``onboarding_0023_dev1_foundation`` is 31 characters, inside the register's
32-character limit on ``alembic_version.version_num``. Named ``<number>_<lane>_<topic>``
(allocation §2.2). F1 merges first, so it takes the first free number.

What it adds, all in the ``onboarding`` schema
-----------------------------------------------
* ``verification_result.subject_company_id`` — nullable ``uuid``, foreign key to
  ``exporter_profile.customer_id`` (``RESTRICT``), with a partial index. The company a
  result is *about*, whatever role that company plays in a deal (seam v2,
  ``docs/contracts/background-check.md`` §12). Nothing writes it yet: company-keyed
  checks are plan P4-5, and the buyer migration (P4-6) fills it on legacy ``BUYER``
  rows.
* **Set once, then frozen.** ``trg_verification_result_input_immutability`` is
  re-created with ``subject_company_id`` added to its column list. The trigger function
  (``prevent_field_mutation_when_set()``) lets a ``NULL`` become a value and refuses
  every change after that, including back to ``NULL`` — exactly what P4-6 needs to
  fill legacy rows without being able to re-point a result later.
* ``exporter_profile.background_check_expires_at`` — nullable ``timestamptz`` with a
  partial index: when the current ``CLEAR`` stops being current (decision E). Written
  by plan P3-3a; until then it stays ``NULL`` and ``ComplianceFactsReader`` uses the
  legacy rule (the clearing decision + one year, BQ-5).

Both columns are added by DDL. ``ADD COLUMN`` fires no row trigger, so no protected
row is updated.

Downgrade restores the trigger's previous column list and drops both columns and their
indexes. **Lossy** since plan P4-5 and P3-3a write both columns: the subject company
of every result and every company's current Clear expiry are dropped (both are
re-derivable: an `EXPORTER` result is about `entity_reference`; the expiry from the
clearing decision). Before then it was lossless.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0023_dev1_foundation"
down_revision: str | None = "onboarding_0022_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
RESULT = "verification_result"
PROFILE = "exporter_profile"

#: The frozen-once-set columns before and after this migration.
INPUT_COLUMNS_BEFORE = ("evidence_note", "evidence_refs", "subject_snapshot")
INPUT_COLUMNS_AFTER = (*INPUT_COLUMNS_BEFORE, "subject_company_id")


def _input_immutability_trigger(columns: Sequence[str]) -> str:
    arguments = ", ".join(f"'{column}'" for column in columns)
    return f"""
        CREATE TRIGGER trg_verification_result_input_immutability
        BEFORE UPDATE ON {SCHEMA}.{RESULT}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set({arguments});
        """


def _drop_input_immutability_trigger() -> str:
    return (
        f"DROP TRIGGER IF EXISTS trg_verification_result_input_immutability "
        f"ON {SCHEMA}.{RESULT};"
    )


def upgrade() -> None:
    op.add_column(
        RESULT,
        sa.Column("subject_company_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_verification_result_subject_company_id",
        RESULT,
        PROFILE,
        ["subject_company_id"],
        ["customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_result_subject_company_id",
        RESULT,
        ["subject_company_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("subject_company_id IS NOT NULL"),
    )
    op.execute(_drop_input_immutability_trigger())
    op.execute(_input_immutability_trigger(INPUT_COLUMNS_AFTER))

    op.add_column(
        PROFILE,
        sa.Column("background_check_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_profile_background_check_expires_at",
        PROFILE,
        ["background_check_expires_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("background_check_expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exporter_profile_background_check_expires_at", table_name=PROFILE, schema=SCHEMA
    )
    op.drop_column(PROFILE, "background_check_expires_at", schema=SCHEMA)

    op.execute(_drop_input_immutability_trigger())
    op.execute(_input_immutability_trigger(INPUT_COLUMNS_BEFORE))
    op.drop_index("ix_verification_result_subject_company_id", table_name=RESULT, schema=SCHEMA)
    op.drop_constraint(
        "fk_verification_result_subject_company_id", RESULT, schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column(RESULT, "subject_company_id", schema=SCHEMA)
