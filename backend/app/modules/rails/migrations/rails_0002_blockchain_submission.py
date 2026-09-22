"""create rails.blockchain_submission

Epic 2.3 / S2T3 AC5 — blockchain transaction-hash identity.

One table, one unique constraint, two indexes. Nothing speculative: no status
column, no metadata blob, no confirmation counter. This table answers exactly
one question — "have we already claimed this transaction on this rail?" — and
anything else it carried would be a second source of truth for state that
rails.leg_status_update_record already records.

Append-only, guarded by public.prevent_mutation() like the other immutable
rails tables. A claim that could be updated or deleted would make "first
observation wins" a convention rather than a guarantee.

Revision ID: rails_0002_blockchain_submission
Revises: c9d0e1f2a3b4
Create Date: 2026-08-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "rails_0002_blockchain_submission"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rails"
SETTLEMENT_SCHEMA = "settlement"


def upgrade() -> None:
    op.create_table(
        "blockchain_submission",
        sa.Column("id", sa.UUID(), nullable=False),
        # The rail that reported this transaction. Scopes the hash — a hash
        # string is not globally unique across chains, and this platform has no
        # network vocabulary to scope by.
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        # Stored verbatim. 128 covers a 66-character EVM hash and the longer
        # base58 signatures other chains use.
        sa.Column("transaction_hash", sa.String(length=128), nullable=False),
        # FK to Epic 2.2 settlement_leg.
        sa.Column("leg_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="blockchain_submission_pkey"),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            [f"{SETTLEMENT_SCHEMA}.settlement_leg.id"],
            name="blockchain_submission_leg_id_fkey",
            ondelete="RESTRICT",
        ),
        # The AC5 guard. Postgres decides who wins a concurrent race; the
        # application never reads-then-decides.
        sa.UniqueConstraint(
            "rail_id", "transaction_hash", name="uq_blockchain_submission_rail_tx"
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_blockchain_submission_leg_id",
        "blockchain_submission",
        ["leg_id"],
        unique=False,
        schema=SCHEMA,
    )
    # Supports "which rail(s) reported this hash" during reorg investigation,
    # where the rail is not known up front so the unique index cannot serve.
    op.create_index(
        "ix_blockchain_submission_tx_hash",
        "blockchain_submission",
        ["transaction_hash"],
        unique=False,
        schema=SCHEMA,
    )

    # Append-only. prevent_mutation() is owned by the shared bootstrap and is
    # already used by the other immutable rails tables (rails_0001_baseline:412).
    op.execute(
        f"""
        CREATE TRIGGER blockchain_submission_prevent_mutation
        BEFORE UPDATE OR DELETE ON {SCHEMA}.blockchain_submission
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS blockchain_submission_prevent_mutation "
        f"ON {SCHEMA}.blockchain_submission;"
    )
    op.drop_index(
        "ix_blockchain_submission_tx_hash",
        table_name="blockchain_submission",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_blockchain_submission_leg_id",
        table_name="blockchain_submission",
        schema=SCHEMA,
    )
    op.drop_table("blockchain_submission", schema=SCHEMA)
