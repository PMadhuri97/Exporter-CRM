"""add rails.leg_status_update_record.rail_event_id + webhook idempotency index

Epic 2.4 / S5 — inbound webhook processing must be idempotent: the same webhook
delivered more than once (rail retry logic) must produce exactly one
leg_status_update_record row.

Idempotency key = (rail_reference, rail_event_id), where rail_event_id is the
rail's own unique id for the delivery. The adapter's handle_webhook extracts it.
Poll results and on-chain events carry no such id, so the column is nullable and
the unique index is partial (WHERE rail_event_id IS NOT NULL) — those writers are
unaffected and keep appending a row per observation, exactly as before.

The column is additive on an append-only table; no backfill. The partial unique
index is the concurrency backstop: two identical webhooks racing the processor's
pre-check both try to insert, and Postgres lets exactly one through.

Revision ID: rails_0003_rail_event_id
Revises: customers_0003_entitlements
Create Date: 2026-09-07

Re-parented from onboarding_0002_orchestration onto customers_0003_entitlements:
this branch forked the revision graph at onboarding_0002_orchestration (the other
side, customers_0002_review_lifecycle -> customers_0003_entitlements, is already
on develop). Per backend/README.md a branch-only fork is healed by re-parenting
the branch-only revision onto the chain tip, not with a merge revision. The
column and index this adds live in schema `rails` and touch nothing the customers
revisions do, so ordering after them is immaterial.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic. Kept <= 32 chars — alembic_version
# stores this in a VARCHAR(32) (cf. rails_0002_blockchain_submission).
revision: str = "rails_0003_rail_event_id"
down_revision: str | None = "customers_0003_entitlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rails"
TABLE = "leg_status_update_record"
INDEX = "uq_leg_status_update_rail_ref_event"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("rail_event_id", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        INDEX,
        TABLE,
        ["rail_reference", "rail_event_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("rail_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "rail_event_id", schema=SCHEMA)
