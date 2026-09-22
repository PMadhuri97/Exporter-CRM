"""Add ONBOARDING_INTAKE to case_type_enum (ANER-4.3-S2)

RXIL pushes invoice/counterparty data directly, but not everything a human
reviewer needs is always present yet. `ONBOARDING_INTAKE` represents that
holding state — a case exists, but required documents/checks aren't all in —
distinct from the existing `ONBOARDING_REVIEW`, which is the same case once
everything needed is present and a human can actually decide. A case's
`case_type` moves from `ONBOARDING_INTAKE` to `ONBOARDING_REVIEW` exactly once
(`app/modules/cases/application/case_transition_service.py`).

This migration only adds the enum value. The follow-up schema changes that
*use* the new value — making `compliance_case.sla_deadline` nullable and
adding `ck_compliance_case_intake_has_no_sla_deadline` — are a separate
migration (`cases_0003_intake_sla_null`) on purpose: Postgres
refuses to let a freshly `ALTER TYPE ... ADD VALUE`'d label be referenced
(even inside a CHECK constraint's string literal, which requires an implicit
cast to the enum type) until that ADD VALUE has committed —
`psycopg2.errors.UnsafeNewEnumValueUsage: unsafe use of new value ... HINT:
New enum values must be committed before they can be used.`

That "committed" requirement bites even across migration *files*: this repo's
`migrations/env.py` wraps the whole `alembic upgrade` run in one
`context.begin_transaction()` (it does not set
`transaction_per_migration=True`), so running this migration and
`cases_0003_intake_sla_null` back to back in the same `upgrade head`
invocation — the normal case for anyone not already on `cases_0002` — would
otherwise still see the ADD VALUE as uncommitted when `cases_0003` runs. The
`settlement`/`onboarding` precedents this pattern is copied from
(`settlement/migrations/46d518356296_add_failed_status.py`,
`onboarding/migrations/45ede5960506_add_not_supported_to_kybnormalisedresult.py`)
never hit this because nothing in the same run went on to reference their new
value. `op.get_context().autocommit_block()` is Alembic's documented escape
hatch for exactly this: it forces the ambient transaction to commit, runs the
`ALTER TYPE` in its own autocommit transaction, and resumes a fresh
transaction for whatever migration runs next.

Revision ID: cases_0002_intake_type
Revises: cases_0001_case_management
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cases_0002_intake_type"
down_revision: str | None = "cases_0001_case_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "cases"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {SCHEMA}.case_type_enum ADD VALUE IF NOT EXISTS 'ONBOARDING_INTAKE'"
        )


def downgrade() -> None:
    # Postgres has no supported way to remove a value from an existing enum
    # type without recreating it — the same non-goal
    # settlement/onboarding's precedent migrations already accept.
    pass
