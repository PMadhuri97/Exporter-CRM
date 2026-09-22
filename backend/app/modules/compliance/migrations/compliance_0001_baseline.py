"""compliance module baseline — schema `compliance`

Squash of three sources, expressed as the final desired schema only:

  41735b67723b  compliance_approvals, compliance_cases, compliance_screenings,
                six enums, two immutability triggers
  a5b6c7d8e9f0  purpose_code_canonical, purpose_code_corridor_mapping,
                purpose_category_enum
  b6c7d8e9f0a1  sector_code_registry, sector_risk_classification,
                sector_risk_tier_enum

Everything is created inside the dedicated `compliance` schema:

  Transaction-linked (all three reference payments.transactions):
    compliance.compliance_screenings — sanctions / AML results. Append-only.
    compliance.compliance_approvals  — maker-checker decisions. Append-only.
    compliance.compliance_cases      — investigation cases. MUTABLE, see below.

  Reference registries (no cross-module reference of any kind):
    compliance.purpose_code_canonical
    compliance.purpose_code_corridor_mapping
    compliance.sector_code_registry
    compliance.sector_risk_classification

The module owns no functions and no sequences.

`compliance_cases` DELIBERATELY HAS NO IMMUTABILITY TRIGGER.
41735b67723b installs `prevent_mutation()` triggers on compliance_screenings and
compliance_approvals but not on compliance_cases, and that asymmetry is correct:
`case_status_enum` is OPEN → UNDER_REVIEW → CLOSED, and a case that cannot be
updated could never leave OPEN. The ORM declares `ComplianceCase(AppendOnlyModel)`,
which contradicts the database; the database is right and is what this baseline
reproduces. Do not "fix" this by adding a third trigger.

TWO ENUM CONVENTIONS, BOTH PRESERVED.
The six enums from 41735b67723b store UPPERCASE labels: their models use a plain
`Enum(PyEnum, name=...)`, so SQLAlchemy persists `.name`. The two registry enums
store lowercase labels: `registry.py` and `sector_registry.py` pass
`values_callable`, so SQLAlchemy persists `.value`. The split is not a mistake and
must not be normalised — the stored labels differ.

Column order reproduces the physical order in the pre-squash database. In the
three transaction-linked tables that puts `id` and `created_at` last, because the
original autogenerate emitted the AppendOnlyModel mixin columns after the
domain columns. The ORM declares them first; the database does not.

CROSS-SCHEMA DEPENDENCY: the three transaction-linked tables reference
`payments.transactions.transaction_id`, created by the payments baseline. That
baseline must be applied first. The four registry tables have no cross-schema
dependency and would be independently deployable if they were their own module.

EXTERNAL DEPENDENCY: both immutability triggers execute
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.

Constraint names reproduce what the pre-squash database holds. None of these
tables was ever renamed. Where the source migration named a constraint
explicitly (`uq_purpose_code_canonical_code`, `fk_sector_risk_classification_sector_code`,
…) that name is used; where it did not, the explicit name below is identical to
what PostgreSQL would generate.

Revision ID: compliance_0001_baseline
Revises: notifications_0001_baseline
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "compliance_0001_baseline"
down_revision: str | None = "notifications_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "compliance"
PAYMENTS_SCHEMA = "payments"


# ── Enums ─────────────────────────────────────────────────────────────────────
# UPPERCASE group — models use a plain Enum(PyEnum, name=...), so SQLAlchemy
# persists the member NAME.

screening_type_enum = postgresql.ENUM(
    "SANCTIONS_OFAC", "SANCTIONS_UN", "SANCTIONS_EU", "SANCTIONS_RBI",
    "AML_RISK", "DNFBP",
    name="screening_type_enum", schema=SCHEMA, create_type=False,
)
screening_status_enum = postgresql.ENUM(
    "PASS", "FAIL", "MANUAL_REVIEW",
    name="screening_status_enum", schema=SCHEMA, create_type=False,
)
approver_role_enum = postgresql.ENUM(
    "MAKER", "CHECKER",
    name="approver_role_enum", schema=SCHEMA, create_type=False,
)
approval_decision_enum = postgresql.ENUM(
    "APPROVED", "REJECTED",
    name="approval_decision_enum", schema=SCHEMA, create_type=False,
)
case_type_enum = postgresql.ENUM(
    "SANCTIONS_HIT", "FAILED_SETTLEMENT", "RECONCILIATION_BREAK", "DNFBP_EDD",
    name="case_type_enum", schema=SCHEMA, create_type=False,
)
case_status_enum = postgresql.ENUM(
    "OPEN", "UNDER_REVIEW", "CLOSED",
    name="case_status_enum", schema=SCHEMA, create_type=False,
)

# lowercase group — registry models pass values_callable, so SQLAlchemy persists
# the member VALUE. Do not normalise these to match the group above.
purpose_category_enum = postgresql.ENUM(
    "trade", "services", "investment", "personal", "other",
    name="purpose_category_enum", schema=SCHEMA, create_type=False,
)
sector_risk_tier_enum = postgresql.ENUM(
    "standard", "elevated", "high", "critical",
    name="sector_risk_tier_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    screening_type_enum,
    screening_status_enum,
    approver_role_enum,
    approval_decision_enum,
    case_type_enum,
    case_status_enum,
    purpose_category_enum,
    sector_risk_tier_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # one of these types later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── compliance_screenings ─────────────────────────────────────────────────
    op.create_table(
        "compliance_screenings",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("screening_type", screening_type_enum, nullable=False),
        sa.Column("status", screening_status_enum, nullable=False),
        # Unbounded VARCHAR in the source migration — not String(n).
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="compliance_screenings_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="compliance_screenings_pkey"),
        schema=SCHEMA,
    )

    # ── compliance_approvals ──────────────────────────────────────────────────
    op.create_table(
        "compliance_approvals",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("approver_role", approver_role_enum, nullable=False),
        sa.Column("approver_user_id", sa.UUID(), nullable=False),
        sa.Column("decision", approval_decision_enum, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="compliance_approvals_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="compliance_approvals_pkey"),
        # Prevents the same user approving the same transaction in any role —
        # this is what makes maker-checker structurally enforceable.
        sa.UniqueConstraint(
            "transaction_id",
            "approver_user_id",
            name="uq_compliance_approvals_transaction_approver",
        ),
        schema=SCHEMA,
    )

    # ── compliance_cases ──────────────────────────────────────────────────────
    # Mutable by design. No immutability trigger — see module docstring.
    op.create_table(
        "compliance_cases",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("case_type", case_type_enum, nullable=False),
        sa.Column("status", case_status_enum, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="compliance_cases_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="compliance_cases_pkey"),
        schema=SCHEMA,
    )

    # ── purpose_code_canonical ────────────────────────────────────────────────
    op.create_table(
        "purpose_code_canonical",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", purpose_category_enum, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="purpose_code_canonical_pkey"),
        # Explicitly named in a5b6c7d8e9f0, and load-bearing: it is the FK target
        # for purpose_code_corridor_mapping.canonical_code.
        sa.UniqueConstraint("canonical_code", name="uq_purpose_code_canonical_code"),
        schema=SCHEMA,
    )

    # ── purpose_code_corridor_mapping ─────────────────────────────────────────
    op.create_table(
        "purpose_code_corridor_mapping",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_code", sa.String(length=50), nullable=False),
        sa.Column("corridor_id", sa.String(length=50), nullable=False),
        sa.Column("external_standard", sa.String(length=50), nullable=False),
        sa.Column("external_code", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_code"],
            [f"{SCHEMA}.purpose_code_canonical.canonical_code"],
            name="purpose_code_corridor_mapping_canonical_code_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="purpose_code_corridor_mapping_pkey"),
        sa.UniqueConstraint(
            "corridor_id",
            "external_standard",
            "external_code",
            name="uq_purpose_code_mapping",
        ),
        schema=SCHEMA,
    )

    # ── sector_code_registry ──────────────────────────────────────────────────
    op.create_table(
        "sector_code_registry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("isic_code", sa.String(length=10), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="sector_code_registry_pkey"),
        # The FK from sector_risk_classification targets sector_code, which
        # Postgres permits only against a uniquely-constrained column.
        sa.UniqueConstraint("sector_code", name="uq_sector_code_registry_sector_code"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_registry_period",
        ),
        # A row stored as 'precious_stones_trade' would satisfy every other
        # constraint and then never be found by the exact-match lookup, silently
        # making the sector invisible.
        sa.CheckConstraint(
            "sector_code = upper(sector_code)",
            name="ck_sector_code_registry_sector_code_upper",
        ),
        schema=SCHEMA,
    )

    # ── sector_risk_classification ────────────────────────────────────────────
    op.create_table(
        "sector_risk_classification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("jurisdiction", sa.String(length=50), nullable=False),
        sa.Column("risk_tier", sector_risk_tier_enum, nullable=False),
        sa.Column("classification_label", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sector_code"],
            [f"{SCHEMA}.sector_code_registry.sector_code"],
            name="fk_sector_risk_classification_sector_code",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="sector_risk_classification_pkey"),
        # Scoped to the start date, not the pair: a jurisdiction may supersede its
        # own rating over time, but only once per day.
        sa.UniqueConstraint(
            "sector_code",
            "jurisdiction",
            "effective_from",
            name="uq_sector_risk_classification",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_risk_classification_period",
        ),
        # A row stored as 'fatf' would satisfy every other constraint and then
        # never be found by the FATF fallback.
        sa.CheckConstraint(
            "jurisdiction = upper(jurisdiction)",
            name="ck_sector_risk_classification_jurisdiction_upper",
        ),
        schema=SCHEMA,
    )
    # Every lookup filters on this pair before date-filtering in Python.
    op.create_index(
        "ix_sector_risk_classification_sector_code_jurisdiction",
        "sector_risk_classification",
        ["sector_code", "jurisdiction"],
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Two, not three: compliance_cases is mutable. prevent_mutation() is owned by
    # the shared root migration and lives in public — referenced schema-qualified
    # on purpose.
    op.execute(
        f"""
        CREATE TRIGGER compliance_screenings_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.compliance_screenings
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER compliance_approvals_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.compliance_approvals
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches all seven tables, their keys, the index, both triggers and
    # all eight enum types in one statement.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
