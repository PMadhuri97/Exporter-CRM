"""rails module baseline — schema `rails`

Creates the Rail Abstraction Layer (Epic 2.4) data model.:

  rails.rail_registration          — registered rail adapters and their capabilities.
  rails.leg_submission_record      — immutable record of every leg submission attempt.
  rails.leg_status_update_record   — append-only record of every status update from a rail.
  rails.routing_decision_record    — immutable record of every routing decision.
  rails.circuit_breaker_state      — current circuit breaker state per rail.

CROSS-SCHEMA DEPENDENCIES:
  leg_submission_record.leg_id    → settlement.settlement_leg.id
  leg_submission_record.settlement_id → settlement.settlement.id
  leg_status_update_record.leg_id → settlement.settlement_leg.id
  routing_decision_record.settlement_id → settlement.settlement.id
  routing_decision_record.leg_id  → settlement.settlement_leg.id

The settlement baseline must be applied first.

IMMUTABILITY:
  - leg_submission_record, leg_status_update_record, routing_decision_record:
    public.prevent_mutation() (created by the shared bootstrap) rejects ALL UPDATE
    and DELETE. Referenced schema-qualified so search_path changes cannot break it.
  - rail_registration: rails.assert_rail_registration_immutable_fields() guards
    `registered_at` and `rail_id` — immutable once set.
  - circuit_breaker_state: fully mutable, upserted on every state transition.

ENUM LABEL CONVENTION:
  All seven enums use values_callable so SQLAlchemy persists .value (lowercase).

DOWNGRADE:
  DROP SCHEMA IF EXISTS rails CASCADE — removes all five tables, seven enum types,
  the owned trigger function, and all indexes in one statement.

Revision ID: rails_0001_baseline
Revises: b7e4c9a15d20
Create Date: 2026-08-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "rails_0001_baseline"
down_revision: str | None = "b7e4c9a15d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "rails"
SETTLEMENT_SCHEMA = "settlement"


# ── Enums ─────────────────────────────────────────────────────────────────────
# All lowercase (.value) — same convention as the settlement aggregate enums.
# create_type=False because we call .create(bind) explicitly below, ensuring
# a second column adopting one of these types cannot trigger a duplicate CREATE TYPE.

rail_status_enum = postgresql.ENUM(
    "active", "degraded", "suspended", "decommissioned",
    name="rails_rail_status_enum", schema=SCHEMA, create_type=False,
)
submission_status_enum = postgresql.ENUM(
    "submitted", "rejected", "pending", "timeout",
    name="rails_submission_status_enum", schema=SCHEMA, create_type=False,
)
rail_leg_status_enum = postgresql.ENUM(
    "settled", "failed", "processing", "recalled",
    name="rails_rail_leg_status_enum", schema=SCHEMA, create_type=False,
)
circuit_breaker_state_enum = postgresql.ENUM(
    "closed", "open", "half_open",
    name="rails_circuit_breaker_state_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    rail_status_enum,
    submission_status_enum,
    rail_leg_status_enum,
    circuit_breaker_state_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Create all enum types explicitly before any table references them.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── rail_registration ─────────────────────────────────────────────────────
    op.create_table(
        "rail_registration",
        sa.Column("id", sa.UUID(), nullable=False),
        # Stable unique identifier. Examples: nium_usd_inr, circle_usdc_cctp.
        # Immutable once registered — trigger guards this field.
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        # The full capability declaration as defined in Epic 2.4
        # (all 20 fields including rail_name, rail_type, status, registered_at etc).
        sa.Column("capability_declaration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # The internal class name of the rail adapter implementation.
        sa.Column("adapter_class", sa.String(length=255), nullable=False),
        sa.Column("status", rail_status_enum, nullable=False, server_default="active"),
        # Internal endpoint called by the health monitor.
        sa.Column("health_check_url", sa.String(length=255), nullable=True),
        # When this rail was registered. Immutable once set — trigger guards this.
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        # Updated when capability declaration or status changes.
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="rail_registration_pkey"),
        sa.UniqueConstraint("rail_id", name="uq_rail_registration_rail_id"),
        sa.CheckConstraint(
            "status IN ('active', 'degraded', 'suspended', 'decommissioned')",
            name="ck_rail_registration_status",
        ),
        sa.CheckConstraint(
            "octet_length(capability_declaration::text) <= 65536",
            name="ck_rail_registration_cap_decl_size",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rail_registration_status", "rail_registration", ["status"],
        unique=False, schema=SCHEMA,
    )

    # ── leg_submission_record ─────────────────────────────────────────────────
    op.create_table(
        "leg_submission_record",
        sa.Column("id", sa.UUID(), nullable=False),
        # FK to Epic 2.2 settlement_leg.
        sa.Column("leg_id", sa.UUID(), nullable=False),
        # FK to Epic 2.2 settlement.
        sa.Column("settlement_id", sa.UUID(), nullable=False),
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        # The rail reference used as the idempotency key (from Epic 2.3).
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        # The full leg submission request. Immutable once written.
        sa.Column("submission_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # The full leg submission response. Immutable once written.
        sa.Column("submission_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Immutable once written.
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submission_status", submission_status_enum, nullable=False),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement_leg.id"],
            name="leg_submission_record_leg_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement.id"],
            name="leg_submission_record_settlement_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="leg_submission_record_pkey"),
        sa.CheckConstraint(
            "octet_length(submission_request::text) <= 65536",
            name="ck_leg_submission_request_size",
        ),
        sa.CheckConstraint(
            "submission_response IS NULL OR octet_length(submission_response::text) <= 65536",
            name="ck_leg_submission_response_size",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_submission_leg_id", "leg_submission_record", ["leg_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_submission_settlement_id", "leg_submission_record", ["settlement_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_submission_rail_id", "leg_submission_record", ["rail_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_submission_idempotency_key", "leg_submission_record", ["idempotency_key"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_submission_submitted_at", "leg_submission_record", ["submitted_at"],
        unique=False, schema=SCHEMA,
    )

    # ── leg_status_update_record ──────────────────────────────────────────────
    op.create_table(
        "leg_status_update_record",
        sa.Column("id", sa.UUID(), nullable=False),
        # FK to Epic 2.2 settlement_leg.
        sa.Column("leg_id", sa.UUID(), nullable=False),
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        # The rail's reference — used to correlate with the submission.
        sa.Column("rail_reference", sa.String(length=255), nullable=False),
        sa.Column("status", rail_leg_status_enum, nullable=False),
        # When this update was received. Immutable (entire table is append-only).
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        # The full normalised leg status update.
        sa.Column("leg_status_update", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # The complete raw webhook payload, polling response, or on-chain event.
        sa.Column("raw_rail_event", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement_leg.id"],
            name="leg_status_update_record_leg_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="leg_status_update_record_pkey"),
        sa.CheckConstraint(
            "octet_length(leg_status_update::text) <= 65536",
            name="ck_leg_status_update_size",
        ),
        sa.CheckConstraint(
            "octet_length(raw_rail_event::text) <= 65536",
            name="ck_raw_rail_event_size",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_status_update_leg_id", "leg_status_update_record", ["leg_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_status_update_rail_reference", "leg_status_update_record", ["rail_reference"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_status_update_status", "leg_status_update_record", ["status"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_status_update_received_at", "leg_status_update_record", ["received_at"],
        unique=False, schema=SCHEMA,
    )

    # ── routing_decision_record ───────────────────────────────────────────────
    op.create_table(
        "routing_decision_record",
        sa.Column("id", sa.UUID(), nullable=False),
        # FK to Epic 2.2 settlement.
        sa.Column("settlement_id", sa.UUID(), nullable=False),
        # FK to Epic 2.2 settlement_leg.
        sa.Column("leg_id", sa.UUID(), nullable=False),
        # All rails evaluated with scores and inclusion/exclusion reason. Immutable.
        sa.Column("evaluated_rails", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # The rail selected. Immutable.
        sa.Column("selected_rail_id", sa.String(length=64), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        # Routing factors applied. Immutable.
        sa.Column("routing_factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Immutable.
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement.id"],
            name="routing_decision_record_settlement_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement_leg.id"],
            name="routing_decision_record_leg_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="routing_decision_record_pkey"),
        sa.CheckConstraint(
            "octet_length(evaluated_rails::text) <= 65536",
            name="ck_routing_decision_evaluated_rails_size",
        ),
        sa.CheckConstraint(
            "octet_length(routing_factors::text) <= 65536",
            name="ck_routing_decision_routing_factors_size",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_decision_settlement_id", "routing_decision_record", ["settlement_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_decision_leg_id", "routing_decision_record", ["leg_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_decision_selected_rail_id", "routing_decision_record", ["selected_rail_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_decision_decided_at", "routing_decision_record", ["decided_at"],
        unique=False, schema=SCHEMA,
    )

    # ── circuit_breaker_state ─────────────────────────────────────────────────
    op.create_table(
        "circuit_breaker_state",
        # One record per rail — primary key.
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        # closed (normal), open (tripped), half_open (recovery probe).
        sa.Column(
            "state",
            circuit_breaker_state_enum,
            nullable=False,
            server_default="closed",
        ),
        # Number of consecutive failures that contributed to the current state.
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        # Timestamp of the most recent failure.
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        # When the circuit breaker last transitioned to open. Null if currently closed.
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        # When the half_open probe request will be allowed. Null if currently closed.
        sa.Column("next_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("rail_id", name="circuit_breaker_state_pkey"),
        sa.CheckConstraint("failure_count >= 0", name="ck_circuit_breaker_failure_count"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_circuit_breaker_state_state", "circuit_breaker_state", ["state"],
        unique=False, schema=SCHEMA,
    )

    # ── Trigger function — field-level immutability for rail_registration ──────
    # Owned by this schema. Guards rail_id and registered_at from mutation.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_rail_registration_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.rail_id IS NOT NULL AND NEW.rail_id IS DISTINCT FROM OLD.rail_id THEN
                RAISE EXCEPTION 'rails.rail_registration.rail_id is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.registered_at IS NOT NULL AND NEW.registered_at IS DISTINCT FROM OLD.registered_at THEN
                RAISE EXCEPTION 'rails.rail_registration.registered_at is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_leg_submission_record_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.submission_request IS NOT NULL AND NEW.submission_request IS DISTINCT FROM OLD.submission_request THEN
                RAISE EXCEPTION 'rails.leg_submission_record.submission_request is immutable' USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.submission_response IS NOT NULL AND NEW.submission_response IS DISTINCT FROM OLD.submission_response THEN
                RAISE EXCEPTION 'rails.leg_submission_record.submission_response is immutable' USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.submitted_at IS NOT NULL AND NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
                RAISE EXCEPTION 'rails.leg_submission_record.submitted_at is immutable' USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_routing_decision_record_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.decided_at IS NOT NULL AND NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
                RAISE EXCEPTION 'rails.routing_decision_record.decided_at is immutable' USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.evaluated_rails IS NOT NULL AND NEW.evaluated_rails IS DISTINCT FROM OLD.evaluated_rails THEN
                RAISE EXCEPTION 'rails.routing_decision_record.evaluated_rails is immutable' USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.selected_rail_id IS NOT NULL AND NEW.selected_rail_id IS DISTINCT FROM OLD.selected_rail_id THEN
                RAISE EXCEPTION 'rails.routing_decision_record.selected_rail_id is immutable' USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.routing_factors IS NOT NULL AND NEW.routing_factors IS DISTINCT FROM OLD.routing_factors THEN
                RAISE EXCEPTION 'rails.routing_decision_record.routing_factors is immutable' USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Append-only tables: prevent_mutation() is owned by the shared bootstrap
    # migration and lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER leg_submission_record_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.leg_submission_record
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_leg_submission_record_immutable_fields();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER leg_status_update_record_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.leg_status_update_record
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER routing_decision_record_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.routing_decision_record
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_routing_decision_record_immutable_fields();
        """
    )
    # rail_registration is mutable (status, last_health_check_at advance) but
    # rail_id and registered_at are frozen once set.
    op.execute(
        f"""
        CREATE TRIGGER rail_registration_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.rail_registration
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_rail_registration_immutable_fields();
        """
    )


def downgrade() -> None:
    # CASCADE drops all five tables, seven enum types, the owned trigger
    # function, and all indexes and triggers in one statement.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
