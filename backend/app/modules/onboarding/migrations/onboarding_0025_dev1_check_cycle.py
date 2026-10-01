"""Check cycles (plan P2-3a) and the Clear rules version on decisions (plan P2-4a) —
**owner: Developer 1** (allocation §3, tasks 1.5 and 1.6).

Revision ID: onboarding_0025_dev1_check_cycle
Revises: onboarding_0024_dev1_evidence

``onboarding_0025_dev1_check_cycle`` is exactly 32 characters, the register's limit on
``alembic_version.version_num``. P2-3a and P2-4a both add columns to
``background_check_decision``, so the plan puts them in one migration.

What it adds, all in the ``onboarding`` schema
-----------------------------------------------
* ``check_cycle`` — one row per KYC/KYB round of one company, **append-only**
  (``trg_check_cycle_append_only`` → ``public.prevent_mutation()``). ``number`` is 1, 2,
  3 … per company (``uq_check_cycle_company_number``); the current cycle is the
  highest. ``kind`` ``INITIAL`` is cycle 1 and only cycle 1; a later cycle needs a
  reason. Carries ``created_by``, ``created_at``, ``source`` and ``source_ref`` (BQ-7)
  and ``rules_version``.
* ``cycle_id`` on ``verification_result``, ``screening_review_item`` and
  ``background_check_decision`` — nullable, with a partial index each. On the
  screening row and the decision it is a **composite** foreign key onto
  ``check_cycle(id, company_id)`` (``uq_check_cycle_id_company``), so a row can only
  name a cycle of its own company. A verification result names its company only
  through ``entity_reference`` (untyped) or ``subject_company_id`` (not written yet),
  so its foreign key is on ``cycle_id`` alone and the service guarantees the company.
* ``cycle_id`` joins ``trg_verification_result_input_immutability``: set once, then
  frozen. The other two tables are append-only already.
* ``background_check_decision.rules_version`` — the Clear rules in force when the
  decision was taken (P2-4a, decision K). The service writes
  ``CLEAR_RULES_V2`` on every new decision.

Legacy rows are never updated
-----------------------------
The decision and screening tables refuse ``UPDATE`` at the database, and a protective
trigger is never switched off to backfill (plan §17.1). So existing inputs and
decisions keep ``cycle_id IS NULL`` and ``rules_version IS NULL``, and are read by the
documented rules: a ``NULL`` cycle is the company's **cycle 1**; a ``NULL`` rules
version is **``CLEAR_RULES_V1``**, the eight-item checklist.

The only data this writes is **inserts**: one ``INITIAL`` cycle-1 row for every
company that already has a company-subject verification result, a screening answer or
a background-check decision, dated at its earliest one (``started_at``), created by
``migration:onboarding_0025_dev1_check_cycle`` with ``source = 'MIGRATION'``.
``BACKFILL_INITIAL_CYCLES_SQL`` is idempotent (``ON CONFLICT DO NOTHING``), and a
test runs it on a fixture company.

Downgrade — **lossy**
---------------------
Drops the columns, the table and the trigger, and restores the immutability trigger's
previous column list. Lost: every cycle, every ``cycle_id`` and every
``rules_version`` recorded since — the rows themselves stay.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0025_dev1_check_cycle"
down_revision: str | None = "onboarding_0024_dev1_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
CYCLE = "check_cycle"
RESULT = "verification_result"
SCREENING = "screening_review_item"
DECISION = "background_check_decision"
PROFILE = "exporter_profile"

#: Who inserted a backfilled cycle 1. Not a user id: a recognisable migration actor.
MIGRATION_ACTOR = f"migration:{revision}"

#: The frozen-once-set columns on `verification_result` before and after this migration.
INPUT_COLUMNS_BEFORE = ("evidence_note", "evidence_refs", "subject_snapshot", "subject_company_id")
INPUT_COLUMNS_AFTER = (*INPUT_COLUMNS_BEFORE, "cycle_id")

#: One cycle 1 per company with any input or decision, dated at the earliest of them.
#: Inserts only, and idempotent. A company-subject result whose `entity_reference` names
#: no company (a pre-4B-4 row) has no company to hang a cycle on and is skipped.
BACKFILL_INITIAL_CYCLES_SQL = f"""
    INSERT INTO {SCHEMA}.{CYCLE}
        (id, created_at, company_id, number, kind, reason, started_at, rules_version,
         created_by, source, source_ref)
    SELECT gen_random_uuid(), now(), inputs.company_id, 1, 'INITIAL', NULL,
           min(inputs.at), NULL, :actor, 'MIGRATION', :source_ref
    FROM (
        SELECT r.entity_reference AS company_id, r.performed_at AS at
        FROM {SCHEMA}.{RESULT} r
        JOIN {SCHEMA}.{PROFILE} p ON p.customer_id = r.entity_reference
        WHERE r.entity_type = 'EXPORTER'
        UNION ALL
        SELECT s.customer_id, s.created_at FROM {SCHEMA}.{SCREENING} s
        UNION ALL
        SELECT d.company_id, d.decided_at FROM {SCHEMA}.{DECISION} d
    ) AS inputs
    GROUP BY inputs.company_id
    ON CONFLICT (company_id, number) DO NOTHING
"""


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
    # ── check_cycle ──────────────────────────────────────────────────────────
    op.create_table(
        CYCLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rules_version", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_check_cycle"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.{PROFILE}.customer_id"],
            name="fk_check_cycle_company_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "number", name="uq_check_cycle_company_number"),
        sa.UniqueConstraint("id", "company_id", name="uq_check_cycle_id_company"),
        sa.CheckConstraint("number >= 1", name="ck_check_cycle_number_positive"),
        sa.CheckConstraint(
            "kind IN ('INITIAL', 'RE_KYC', 'RE_KYB', 'FULL')", name="ck_check_cycle_kind"
        ),
        sa.CheckConstraint(
            "(number = 1) = (kind = 'INITIAL')", name="ck_check_cycle_initial_first"
        ),
        sa.CheckConstraint(
            "number = 1 OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_check_cycle_reason",
        ),
        sa.CheckConstraint("btrim(created_by) <> ''", name="ck_check_cycle_created_by"),
        sa.CheckConstraint("btrim(source) <> ''", name="ck_check_cycle_source"),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_check_cycle_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{CYCLE}
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )

    # ── cycle_id on the inputs and the decisions ─────────────────────────────
    for table in (RESULT, SCREENING, DECISION):
        op.add_column(
            table,
            sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema=SCHEMA,
        )
        op.create_index(
            f"ix_{table}_cycle_id",
            table,
            ["cycle_id"],
            schema=SCHEMA,
            postgresql_where=sa.text("cycle_id IS NOT NULL"),
        )
    op.create_foreign_key(
        "fk_verification_result_cycle_id",
        RESULT,
        CYCLE,
        ["cycle_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_screening_review_item_cycle",
        SCREENING,
        CYCLE,
        ["cycle_id", "customer_id"],
        ["id", "company_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_background_check_decision_cycle",
        DECISION,
        CYCLE,
        ["cycle_id", "company_id"],
        ["id", "company_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(_drop_input_immutability_trigger())
    op.execute(_input_immutability_trigger(INPUT_COLUMNS_AFTER))

    # ── rules_version on decisions (P2-4a) ───────────────────────────────────
    op.add_column(
        DECISION,
        sa.Column("rules_version", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )

    # ── cycle 1 for every company that already has inputs — inserts only ─────
    op.execute(
        sa.text(BACKFILL_INITIAL_CYCLES_SQL).bindparams(
            actor=MIGRATION_ACTOR, source_ref=revision
        )
    )


def downgrade() -> None:
    op.drop_column(DECISION, "rules_version", schema=SCHEMA)

    op.execute(_drop_input_immutability_trigger())
    op.execute(_input_immutability_trigger(INPUT_COLUMNS_BEFORE))
    op.drop_constraint(
        "fk_background_check_decision_cycle", DECISION, schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_screening_review_item_cycle", SCREENING, schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_verification_result_cycle_id", RESULT, schema=SCHEMA, type_="foreignkey"
    )
    for table in (RESULT, SCREENING, DECISION):
        op.drop_index(f"ix_{table}_cycle_id", table_name=table, schema=SCHEMA)
        op.drop_column(table, "cycle_id", schema=SCHEMA)

    op.execute(f"DROP TRIGGER IF EXISTS trg_check_cycle_append_only ON {SCHEMA}.{CYCLE};")
    op.drop_table(CYCLE, schema=SCHEMA)
