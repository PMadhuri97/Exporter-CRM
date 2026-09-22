"""gateway module baseline — schema `gateway`

Creates the gateway module's schema and its first table:

  gateway.api_request_logs — append-only record of every request the API
  gateway's request-handling pipeline observed (ANER-4.4-S1T1). One row per
  request to a path the gateway owns (`/health`, `/v{n}/...`): correlation
  ID, method, path, status code, resolved duration, and an optional
  customer_id reference. No request/response body column by design — see
  app/modules/gateway/domain/entities/gateway.py.

The immutability trigger reuses the shared `public.prevent_mutation()`
function (a0b1c2d3e4f5) rather than defining a gateway-owned one, the same
pattern onboarding_event and case_state_transition already use.

Revision ID: gateway_0001_baseline
Revises: 0a772fd562e8
Create Date: 2026-09-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "gateway_0001_baseline"
down_revision: str | None = "0a772fd562e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "gateway"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── api_request_logs ─────────────────────────────────────────────────────
    op.create_table(
        "api_request_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        # No FK: no authentication exists yet in this slice, so this column is
        # always NULL today. See the entity docstring.
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="api_request_logs_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_request_logs_correlation_id",
        "api_request_logs",
        ["correlation_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_request_logs_customer_id",
        "api_request_logs",
        ["customer_id"],
        schema=SCHEMA,
    )

    # ── Trigger ───────────────────────────────────────────────────────────────
    # A freshly created, empty table — plain (non-CONCURRENT) index/trigger
    # creation is safe under BUILD.md #14, which reserves CONCURRENTLY for
    # tables that may already hold production data.
    op.execute(
        f"""
        CREATE TRIGGER api_request_logs_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.api_request_logs
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches the table, its primary key, both indexes and the
    # trigger in one statement. public.prevent_mutation() is not this
    # module's to drop — it is owned by a0b1c2d3e4f5 and shared by seven
    # other schemas.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
