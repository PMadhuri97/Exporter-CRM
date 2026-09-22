"""audit module baseline — schema `audit`

Squash of the audit portion of 41735b67723b (one table, one enum, one
immutability trigger) together with e5f6a7b8c9d0, which added `correlation_id`
and its index, and f6a7b8c9d0e1, which added `synced_to_sink_at`, updated the
immutability trigger, and added the insert notification trigger.
Expressed as the final desired schema only.

Everything is created inside the dedicated `audit` schema:

  audit.audit_events — write-once event record, retained 7 years.

The module owns no functions and no sequences.

Column order reproduces the physical order in the pre-squash database:
`id` and `created_at` sit in positions 6 and 7 because the original autogenerate
emitted the AppendOnlyModel mixin columns last, and `correlation_id` is position
8 because e5f6a7b8c9d0 appended it. The ORM declares them in a different order;
the database is what this baseline reproduces.

SHARED ENUM — DECISION PENDING.
`actor_type_enum` is created here because audit created it originally (41735b67723b,
for audit_events) and a1b2c3d4e5f6 explicitly declines to re-create or drop it:
"actor_type_enum already exists (audit_events). Never re-created, never dropped."
It is also used by onboarding.case_state_transition. Under schema-per-module the
onboarding baseline must either reference `audit.actor_type_enum` with
create_type=False — preserving today's single shared type and making onboarding
depend on audit — or declare its own `onboarding.actor_type_enum`. That decision
belongs to the onboarding baseline; nothing here forecloses it.
See migrations/CUTOVER_MANIFEST.md.

CROSS-SCHEMA DEPENDENCY: `transaction_id` references
`payments.transactions.transaction_id`, created by the payments baseline. That
baseline must be applied first.

EXTERNAL DEPENDENCY: `audit_events_immutable` executes
`prevent_audit_event_mutation()`, which is owned by this module.

Constraint names reproduce what the pre-squash database holds. This table was
never renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: audit_0001_baseline
Revises: payments_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "audit_0001_baseline"
down_revision: str | None = "payments_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "audit"
PAYMENTS_SCHEMA = "payments"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: the model does not pass
# values_callable, so SQLAlchemy persists `.name`. The stored labels must match.
#
# SYSTEM             — platform acting on its own; actor_id is NULL.
# COMPLIANCE_OFFICER — internal staff acting with privileged authority.
# API_CLIENT         — external caller acting on its own resources.
actor_type_enum = postgresql.ENUM(
    "SYSTEM", "COMPLIANCE_OFFICER", "API_CLIENT",
    name="actor_type_enum",
    schema=SCHEMA,
    create_type=False,
)

_ENUMS = (actor_type_enum,)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline: onboarding also consumes
    # this type, so ownership of the CREATE TYPE has to be unambiguous.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── audit_events ──────────────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        # Nullable: platform-level events are not always attached to a payment.
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", actor_type_enum, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # End-to-end trace key, auto-populated from the request's
        # X-Correlation-Id so audit events can be followed across services.
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("synced_to_sink_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="audit_events_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="audit_events_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_correlation_id",
        "audit_events",
        ["correlation_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_synced_to_sink_at",
        "audit_events",
        ["synced_to_sink_at"],
        schema=SCHEMA,
    )

    # ── Functions ─────────────────────────────────────────────────────────────
    # Tables are schema-qualified. Functions are placed inside the SCHEMA.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (OLD.id IS DISTINCT FROM NEW.id) OR
                   (OLD.created_at IS DISTINCT FROM NEW.created_at) OR
                   (OLD.transaction_id IS DISTINCT FROM NEW.transaction_id) OR
                   (OLD.correlation_id IS DISTINCT FROM NEW.correlation_id) OR
                   (OLD.event_type IS DISTINCT FROM NEW.event_type) OR
                   (OLD.actor_id IS DISTINCT FROM NEW.actor_id) OR
                   (OLD.actor_type IS DISTINCT FROM NEW.actor_type) OR
                   (OLD.payload IS DISTINCT FROM NEW.payload) THEN
                    RAISE EXCEPTION 'Table audit_events is append-only: UPDATE is only allowed on synced_to_sink_at';
                END IF;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Table audit_events is append-only: DELETE is forbidden';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.notify_audit_event()
        RETURNS trigger AS $$
        BEGIN
            NOTIFY audit_event_channel;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    op.execute(
        f"""
        CREATE TRIGGER audit_events_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.audit_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_audit_event_mutation();
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER audit_event_notify_trigger
        AFTER INSERT ON {SCHEMA}.audit_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.notify_audit_event();
        """
    )


def downgrade() -> None:
    # CASCADE reaches the table, its key, the index, the trigger and the enum
    # type in one statement. Note it also drops actor_type_enum, which
    # onboarding may depend on — order the downgrades accordingly.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
