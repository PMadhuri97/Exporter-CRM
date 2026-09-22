"""Make compliance_case.sla_deadline nullable for ONBOARDING_INTAKE (ANER-4.3-S2)

Follow-up to `cases_0002_intake_type`, split out because
Postgres refuses to let a freshly `ALTER TYPE ... ADD VALUE`'d label be
referenced until that ADD VALUE has committed (see that migration's
docstring) — the `'ONBOARDING_INTAKE'` string literal below requires an
implicit cast to `case_type_enum` to evaluate the CHECK constraint, so it
cannot run in the same migration/transaction as the ADD VALUE itself.

`ONBOARDING_INTAKE` is deliberately excluded from the SLA policy, the same
way `MANUAL` already is (see `infrastructure/sla_config_loader.py`'s
`EXPECTED_CASE_TYPES` and `sla-config.yaml`'s trailing comment): nobody
internal is accountable for how long RXIL or the counterparty takes to
supply documents, so holding intake to an SLA breach doesn't mean anything
actionable. Concretely, that means an `ONBOARDING_INTAKE` case has no
`sla_deadline` at all until it transitions to `ONBOARDING_REVIEW`
(`app/modules/cases/application/case_transition_service.py`). Two schema
changes make that representable:

- `compliance_case.sla_deadline` becomes nullable (it was `NOT NULL` since
  cases_0001, when every case_type in existence had a configured SLA
  target).
- `ck_compliance_case_intake_has_no_sla_deadline` enforces the pairing at the
  database level: an `ONBOARDING_INTAKE` row must have a NULL
  `sla_deadline`. It is one-directional by design — every other case_type is
  still expected to carry a deadline set at creation, but that expectation
  lives at the application layer (as it already did before this migration),
  not as a NOT NULL column constraint, since the one case_type this migration
  is for needs to violate it.

Revision ID: cases_0003_intake_sla_null
Revises: cases_0002_intake_type
Create Date: 2026-09-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cases_0003_intake_sla_null"
down_revision: str | None = "cases_0002_intake_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "cases"


def upgrade() -> None:
    op.alter_column(
        "compliance_case",
        "sla_deadline",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        schema=SCHEMA,
    )

    op.create_check_constraint(
        "ck_compliance_case_intake_has_no_sla_deadline",
        "compliance_case",
        "case_type <> 'ONBOARDING_INTAKE' OR sla_deadline IS NULL",
        schema=SCHEMA,
    )


def downgrade() -> None:
    # A downgrade that ran after any ONBOARDING_INTAKE case existed would fail
    # the NOT NULL backfill it would need to do first — left to whoever
    # downgrades, after confirming no ONBOARDING_INTAKE row remains (or that
    # every such row already carries a non-NULL sla_deadline).
    op.drop_constraint(
        "ck_compliance_case_intake_has_no_sla_deadline",
        "compliance_case",
        schema=SCHEMA,
        type_="check",
    )
    op.alter_column(
        "compliance_case",
        "sla_deadline",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=SCHEMA,
    )
