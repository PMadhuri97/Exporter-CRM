"""Links and derived values the database now checks itself.

Revision ID: onboarding_0054_integrity_fks
Revises: onboarding_0053_auto_criteria

Why
---
Each rule below was already kept by the service that writes the row; none was refused
by the database. The schema audit (``docs/database-audit/audit.md`` §4.5, O7 and O8)
found them by comparing every link with its siblings:

* ``background_check_evidence.verification_review_id`` — the one evidence reference
  without a foreign key. It started without one only because the review table and this
  one were written in parallel (``docs/contracts/background-check.md`` §6.1).
* ``exporter_lifecycle_history.deal_id`` — the history row's deal, now a real deal.
* ``sanctions_run.cycle_id`` and ``verification_result.cycle_id`` — single-column links
  to ``check_cycle``, where decisions, proposals and checklist answers use the
  composite ``(cycle_id, company)`` one. A run or a result can no longer name another
  company's cycle. The result keeps its plain foreign key as well: a row with a cycle
  but no subject company is still checked for the cycle existing.
* ``sanctions_hit (run_id, list_code)`` — a hit is on a list its run screened.
* ``follow_up_completion (activity_id, customer_id)`` — the denormalised company is
  always the activity's. ``exporter_activity`` gains ``UNIQUE (id, customer_id)`` to be
  referenced, as ``check_cycle`` and ``exporter_gstin`` have.
* ``exporter_profile.identity_type`` — derived from ``pan`` and
  ``registration_number`` by ``decide_identity_type``; migration 0043 had to repair
  rows where it had drifted. Now a ``CHECK``.
* ``exporter_gstin.state_code`` — the GSTIN's first two characters, never anything
  else.

Data
----
None is written. Each rule is added ``NOT VALID`` (enforced on every row written or
changed from here on) and then validated **only if no existing row violates it**, the
0042 pattern. Where rows do, the migration prints the count and the query that lists
them and leaves that rule ``NOT VALID``; ``ALTER TABLE … VALIDATE CONSTRAINT`` finishes
the job once they are dealt with.

Rollback
--------
The downgrade drops every rule added here and restores the two single-column foreign
keys it replaced. Nothing is lost: no row changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0054_integrity_fks"
down_revision: str | None = "onboarding_0053_auto_criteria"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

IDENTITY_RULE = (
    "identity_type IS NOT DISTINCT FROM (CASE"
    " WHEN NULLIF(pan, '') IS NOT NULL THEN 'IN_PAN'"
    " WHEN NULLIF(registration_number, '') IS NOT NULL THEN 'FOREIGN_REG'"
    f" END)::{SCHEMA}.company_identity_type_enum"
)
STATE_CODE_RULE = "state_code IS NULL OR state_code = left(gstin, 2)"

#: (table, constraint, definition, query counting the rows that break it).
RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "background_check_evidence",
        "fk_background_check_evidence_verification_review_id",
        f"FOREIGN KEY (verification_review_id) REFERENCES {SCHEMA}.verification_review (id)"
        " ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.background_check_evidence t"
        " WHERE t.verification_review_id IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.verification_review r WHERE r.id = t.verification_review_id)",
    ),
    (
        "exporter_lifecycle_history",
        "fk_exporter_lifecycle_history_deal_id",
        f"FOREIGN KEY (deal_id) REFERENCES {SCHEMA}.deal (id) ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.exporter_lifecycle_history t"
        " WHERE t.deal_id IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.deal d WHERE d.id = t.deal_id)",
    ),
    (
        "sanctions_run",
        "fk_sanctions_run_cycle",
        f"FOREIGN KEY (cycle_id, company_id) REFERENCES {SCHEMA}.check_cycle (id, company_id)"
        " ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.sanctions_run t"
        " WHERE t.cycle_id IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.check_cycle c"
        " WHERE c.id = t.cycle_id AND c.company_id = t.company_id)",
    ),
    (
        "verification_result",
        "fk_verification_result_cycle_company",
        "FOREIGN KEY (cycle_id, subject_company_id)"
        f" REFERENCES {SCHEMA}.check_cycle (id, company_id) ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.verification_result t"
        " WHERE t.cycle_id IS NOT NULL AND t.subject_company_id IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.check_cycle c"
        " WHERE c.id = t.cycle_id AND c.company_id = t.subject_company_id)",
    ),
    (
        "sanctions_hit",
        "fk_sanctions_hit_run_list",
        f"FOREIGN KEY (run_id, list_code) REFERENCES {SCHEMA}.sanctions_run_list (run_id, code)"
        " ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.sanctions_hit t WHERE NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.sanctions_run_list l"
        " WHERE l.run_id = t.run_id AND l.code = t.list_code)",
    ),
    (
        "follow_up_completion",
        "fk_follow_up_completion_activity_id",
        "FOREIGN KEY (activity_id, customer_id)"
        f" REFERENCES {SCHEMA}.exporter_activity (id, customer_id) ON DELETE RESTRICT",
        f"SELECT count(*) FROM {SCHEMA}.follow_up_completion t WHERE NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.exporter_activity a"
        " WHERE a.id = t.activity_id AND a.customer_id = t.customer_id)",
    ),
    (
        "exporter_profile",
        "ck_exporter_profile_identity_type_derived",
        f"CHECK ({IDENTITY_RULE})",
        f"SELECT count(*) FROM {SCHEMA}.exporter_profile WHERE NOT ({IDENTITY_RULE})",
    ),
    (
        "exporter_gstin",
        "ck_exporter_gstin_state_code",
        f"CHECK ({STATE_CODE_RULE})",
        f"SELECT count(*) FROM {SCHEMA}.exporter_gstin WHERE NOT ({STATE_CODE_RULE})",
    ),
)

#: Single-column foreign keys the composite ones replace: (table, constraint, definition).
REPLACED: tuple[tuple[str, str, str], ...] = (
    (
        "sanctions_run",
        "fk_sanctions_run_cycle",
        f"FOREIGN KEY (cycle_id) REFERENCES {SCHEMA}.check_cycle (id)",
    ),
    (
        "follow_up_completion",
        "fk_follow_up_completion_activity_id",
        f"FOREIGN KEY (activity_id) REFERENCES {SCHEMA}.exporter_activity (id)"
        " ON DELETE RESTRICT",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Referenced by the completion's composite foreign key, so it comes first.
    op.execute(
        f"ALTER TABLE {SCHEMA}.exporter_activity "
        "ADD CONSTRAINT uq_exporter_activity_id_customer UNIQUE (id, customer_id)"
    )
    op.execute(
        "CREATE INDEX ix_background_check_evidence_verification_review_id "
        f"ON {SCHEMA}.background_check_evidence (verification_review_id) "
        "WHERE verification_review_id IS NOT NULL"
    )
    for table, name, _definition in REPLACED:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT {name}")

    for table, name, definition, violations_sql in RULES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT {name} {definition} NOT VALID")
        violations = int(bind.execute(sa.text(violations_sql)).scalar() or 0)
        if violations == 0:
            op.execute(f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}")
            continue
        listing = violations_sql.replace("count(*)", "*", 1)
        print(
            f"onboarding_0054: {violations} {table} row(s) break {name}, so it is left "
            "NOT VALID (it is enforced on every new or changed row). "
            f"List them with: {listing}; then "
            f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}."
        )


def downgrade() -> None:
    for table, name, _definition, _violations_sql in reversed(RULES):
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT IF EXISTS {name}")
    for table, name, definition in REPLACED:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT {name} {definition}")
    op.execute(
        f"DROP INDEX IF EXISTS {SCHEMA}.ix_background_check_evidence_verification_review_id"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.exporter_activity "
        "DROP CONSTRAINT IF EXISTS uq_exporter_activity_id_customer"
    )
