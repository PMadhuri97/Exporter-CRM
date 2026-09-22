"""Add edd_trigger_jurisdiction to settlement, positioned after edd_trigger_rule.

AL-66 records which jurisdiction's classification actually decided the EDD
outcome — the authority a compliance officer points to when asked why a
settlement was flagged. Nullable so existing insert paths (raw-SQL test
fixtures, direct repository writes) that predate AL-66 keep working unchanged.

corridor_id and country_jurisdiction are used as compliance-evaluation
inputs by AL-66 but are not persisted as columns yet — that lands in a
follow-up story once their storage shape is settled.

Column position matches the SQLAlchemy entity, immediately after
edd_trigger_rule, which is why the column is added by rebuilding the table
rather than a plain ADD COLUMN: Postgres has no ADD COLUMN ... AFTER, and a
bare add always appends at the physical end regardless of where the ORM
model declares it — the same reasoning compliance_0002_std_versions applied
to purpose_code_corridor_mapping. settlement.id has four inbound FKs across
two modules — settlement_leg, settlement_event (settlement_0001_baseline)
and rails.leg_submission_record, rails.routing_decision_record
(rails_0001_baseline) — confirmed exhaustively by grepping every migration
in the repo for a FK targeting settlement.settlement.id, not just the ones
already known from working inside the settlement module. All four are
dropped before the rebuild and recreated after.

Revision ID: a1c2e3f4b5d6
Revises    : 9f8e7d6c5b4a
Create Date: 2026-08-20
"""
from collections.abc import Sequence

from alembic import op

SCHEMA = "settlement"
LEDGER_SCHEMA = "ledger"
RAILS_SCHEMA = "rails"
TABLE = "settlement"

# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5d6"
down_revision: str | None = "9f8e7d6c5b4a"

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_COLUMNS = (
    "id, idempotency_key, correlation_id, status, sender_account_id, "
    "beneficiary_account_id, send_amount, send_asset_code, receive_amount, "
    "receive_asset_code, fx_rate, fx_rate_locked_at, route, purpose_code, "
    "sector_code, edd_required, edd_trigger_rule, screening_reference, "
    "temporal_workflow_id, created_at, updated_at, settled_at, created_by, "
    "metadata, version"
)


def upgrade() -> None:
    # Inbound FKs reference this table by OID, which survives a rename — but
    # the table they'd end up pointing at is the one about to be dropped, so
    # they have to be dropped now and recreated against the rebuilt table.
    op.execute(f"ALTER TABLE {SCHEMA}.settlement_leg DROP CONSTRAINT settlement_leg_settlement_id_fkey")
    op.execute(f"ALTER TABLE {SCHEMA}.settlement_event DROP CONSTRAINT settlement_event_settlement_id_fkey")
    op.execute(
        f"ALTER TABLE {RAILS_SCHEMA}.leg_submission_record "
        f"DROP CONSTRAINT leg_submission_record_settlement_id_fkey"
    )
    op.execute(
        f"ALTER TABLE {RAILS_SCHEMA}.routing_decision_record "
        f"DROP CONSTRAINT routing_decision_record_settlement_id_fkey"
    )

    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} RENAME TO {TABLE}_pre_reorder")

    # Schema-scoped index-backed names must be moved aside before the rebuilt
    # table can reuse them; check/FK constraints and the trigger are scoped
    # per-table and don't collide, so they're left alone on the old table.
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE}_pre_reorder RENAME CONSTRAINT settlement_pkey TO {TABLE}_pre_reorder_pkey")
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE}_pre_reorder RENAME CONSTRAINT "
        f"uq_settlement_idempotency_key TO uq_{TABLE}_pre_reorder_idempotency_key"
    )
    for ix in (
        "ix_settlement_beneficiary_account", "ix_settlement_correlation_id",
        "ix_settlement_created_at", "ix_settlement_sender_account", "ix_settlement_status",
    ):
        op.execute(f"ALTER INDEX {SCHEMA}.{ix} RENAME TO {ix}_pre_reorder")

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.{TABLE} (
            id UUID NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL,
            correlation_id VARCHAR(255),
            status {SCHEMA}.settlement_status_enum NOT NULL DEFAULT 'initiated',
            sender_account_id UUID NOT NULL,
            beneficiary_account_id UUID NOT NULL,
            send_amount BIGINT NOT NULL,
            send_asset_code VARCHAR(16) NOT NULL,
            receive_amount BIGINT,
            receive_asset_code VARCHAR(16) NOT NULL,
            fx_rate BIGINT,
            fx_rate_locked_at TIMESTAMPTZ,
            route JSONB,
            purpose_code VARCHAR(64) NOT NULL,
            sector_code VARCHAR(64) NOT NULL,
            edd_required BOOLEAN NOT NULL,
            edd_trigger_rule VARCHAR(255),
            edd_trigger_jurisdiction VARCHAR(255),
            screening_reference UUID,
            temporal_workflow_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            settled_at TIMESTAMPTZ,
            created_by VARCHAR(255) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT settlement_pkey PRIMARY KEY (id),
            CONSTRAINT uq_settlement_idempotency_key UNIQUE (idempotency_key),
            CONSTRAINT ck_settlement_send_amount_positive CHECK (send_amount > 0),
            CONSTRAINT ck_settlement_receive_amount_positive
                CHECK (receive_amount IS NULL OR receive_amount > 0),
            CONSTRAINT ck_settlement_edd_rule_consistent
                CHECK (edd_required = (edd_trigger_rule IS NOT NULL)),
            CONSTRAINT settlement_sender_account_id_fkey FOREIGN KEY (sender_account_id)
                REFERENCES {LEDGER_SCHEMA}.ledger_account(id) ON DELETE RESTRICT,
            CONSTRAINT settlement_beneficiary_account_id_fkey FOREIGN KEY (beneficiary_account_id)
                REFERENCES {LEDGER_SCHEMA}.ledger_account(id) ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.{TABLE} ({_ORIGINAL_COLUMNS}, edd_trigger_jurisdiction)
        SELECT {_ORIGINAL_COLUMNS}, NULL
        FROM {SCHEMA}.{TABLE}_pre_reorder
        """
    )

    op.execute(f"DROP TABLE {SCHEMA}.{TABLE}_pre_reorder")

    op.execute(f"CREATE INDEX ix_settlement_correlation_id ON {SCHEMA}.{TABLE} (correlation_id)")
    op.execute(f"CREATE INDEX ix_settlement_status ON {SCHEMA}.{TABLE} (status)")
    op.execute(f"CREATE INDEX ix_settlement_sender_account ON {SCHEMA}.{TABLE} (sender_account_id)")
    op.execute(f"CREATE INDEX ix_settlement_beneficiary_account ON {SCHEMA}.{TABLE} (beneficiary_account_id)")
    op.execute(f"CREATE INDEX ix_settlement_created_at ON {SCHEMA}.{TABLE} (created_at)")

    op.execute(
        f"""
        COMMENT ON COLUMN {SCHEMA}.{TABLE}.edd_trigger_rule IS
            'The rule that triggered EDD. Populated exactly when edd_required is true '
            '(ck_settlement_edd_rule_consistent) and immutable once set '
            '(settlement_immutable_fields). Setting it post-insert therefore requires '
            'flipping edd_required in the same UPDATE.';
        """
    )
    op.execute(
        f"""
        COMMENT ON COLUMN {SCHEMA}.{TABLE}.edd_trigger_jurisdiction IS
            'The authority (framework, country, or corridor) whose sector '
            'classification fed the compliance evaluation, as returned by '
            'ComplianceActionSet.resolving_jurisdiction. Immutable once set '
            '(settlement_immutable_fields) — not required to be non-null exactly '
            'when edd_required is true, since a classification can resolve '
            'without any rule firing.';
        """
    )

    # Extend the existing immutable-fields guard (created_at, created_by, route,
    # edd_trigger_rule) to also freeze edd_trigger_jurisdiction once set — it is
    # a compliance decision recorded at creation time, same as edd_trigger_rule.
    # The function is schema-owned, not table-owned, so it survives the rebuild
    # untouched; only the trigger attaching it to the table needs recreating.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_settlement_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.created_at IS NOT NULL AND NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'settlement.created_at is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.created_by IS NOT NULL AND NEW.created_by IS DISTINCT FROM OLD.created_by THEN
                RAISE EXCEPTION 'settlement.created_by is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.route IS NOT NULL AND NEW.route IS DISTINCT FROM OLD.route THEN
                RAISE EXCEPTION 'settlement.route is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.edd_trigger_rule IS NOT NULL
                AND NEW.edd_trigger_rule IS DISTINCT FROM OLD.edd_trigger_rule THEN
                RAISE EXCEPTION 'settlement.edd_trigger_rule is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.edd_trigger_jurisdiction IS NOT NULL
                AND NEW.edd_trigger_jurisdiction IS DISTINCT FROM OLD.edd_trigger_jurisdiction THEN
                RAISE EXCEPTION 'settlement.edd_trigger_jurisdiction is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER settlement_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_settlement_immutable_fields();
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.settlement_leg
        ADD CONSTRAINT settlement_leg_settlement_id_fkey
        FOREIGN KEY (settlement_id) REFERENCES {SCHEMA}.{TABLE}(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.settlement_event
        ADD CONSTRAINT settlement_event_settlement_id_fkey
        FOREIGN KEY (settlement_id) REFERENCES {SCHEMA}.{TABLE}(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        f"""
        ALTER TABLE {RAILS_SCHEMA}.leg_submission_record
        ADD CONSTRAINT leg_submission_record_settlement_id_fkey
        FOREIGN KEY (settlement_id) REFERENCES {SCHEMA}.{TABLE}(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        f"""
        ALTER TABLE {RAILS_SCHEMA}.routing_decision_record
        ADD CONSTRAINT routing_decision_record_settlement_id_fkey
        FOREIGN KEY (settlement_id) REFERENCES {SCHEMA}.{TABLE}(id) ON DELETE RESTRICT
        """
    )


def downgrade() -> None:
    # Dropping the column removes it regardless of its physical position, so
    # this doesn't need to reverse the rebuild — just undo the column's
    # existence and the trigger clause guarding it, exactly as a plain
    # ADD COLUMN's downgrade would.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_settlement_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.created_at IS NOT NULL AND NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'settlement.created_at is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.created_by IS NOT NULL AND NEW.created_by IS DISTINCT FROM OLD.created_by THEN
                RAISE EXCEPTION 'settlement.created_by is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.route IS NOT NULL AND NEW.route IS DISTINCT FROM OLD.route THEN
                RAISE EXCEPTION 'settlement.route is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.edd_trigger_rule IS NOT NULL
                AND NEW.edd_trigger_rule IS DISTINCT FROM OLD.edd_trigger_rule THEN
                RAISE EXCEPTION 'settlement.edd_trigger_rule is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP COLUMN edd_trigger_jurisdiction")
