"""customers module baseline — schema `customers`

Squash of the customers portion of 41735b67723b (the two tables and their three
enums) together with the `beneficiary_bank_accounts.currency` widening from
b1c2d3e4f5a6, expressed as the final desired schema only.

Everything is created inside the dedicated `customers` schema:

  customers.customers                 — the settlement counterparty registry.
  customers.beneficiary_bank_accounts — payout destinations owned by a customer.

The module owns no functions, no triggers and no sequences. Both primary keys are
UUIDs supplied by the application, and neither table carries an immutability
guard: a customer's KYB status and risk rating are revised over its lifetime, and
a bank account is verified after it is created.

`customers` is the root of the platform's foreign key graph — it holds no
outbound cross-module reference of any kind. The only inbound references are the
two from payments.transactions (sender / beneficiary), which are declared by the
payments baseline, not here.

Constraint names reproduce what the pre-squash database holds. Neither table was
ever renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical (`customers_pkey`, `beneficiary_bank_accounts_pkey`,
`beneficiary_bank_accounts_customer_id_fkey`); they are spelled out only so the
baseline states the full schema rather than relying on generation rules.

Revision ID: customers_0001_baseline
Revises: messaging_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "customers_0001_baseline"
down_revision: str | None = "messaging_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "customers"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: these three models do not pass
# values_callable, so SQLAlchemy persists `.name`. The stored labels must match.

entity_type_enum = postgresql.ENUM(
    "BUYER", "SUPPLIER", "BOTH",
    name="entity_type_enum",
    schema=SCHEMA,
    create_type=False,
)
kyb_status_enum = postgresql.ENUM(
    "PENDING", "VERIFIED", "REJECTED",
    name="kyb_status_enum",
    schema=SCHEMA,
    create_type=False,
)
risk_rating_enum = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "ENHANCED",
    name="risk_rating_enum",
    schema=SCHEMA,
    create_type=False,
)

_ENUMS = (entity_type_enum, kyb_status_enum, risk_rating_enum)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # one of these types later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── customers ─────────────────────────────────────────────────────────────
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("entity_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", entity_type_enum, nullable=False),
        sa.Column("jurisdiction", sa.String(length=10), nullable=True),
        sa.Column("kyb_status", kyb_status_enum, nullable=False),
        sa.Column("risk_rating", risk_rating_enum, nullable=False),
        sa.Column("sector_classification", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("customer_id", name="customers_pkey"),
        schema=SCHEMA,
    )

    # ── beneficiary_bank_accounts ─────────────────────────────────────────────
    op.create_table(
        "beneficiary_bank_accounts",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        # String(8), not String(3): widened by b1c2d3e4f5a6 so the column can hold
        # registry asset codes such as USDC alongside ISO-4217 currencies.
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("bank_name", sa.String(length=255), nullable=True),
        sa.Column("ifsc_code", sa.String(length=20), nullable=True),
        # Stored encrypted at rest — plaintext is never persisted.
        sa.Column("account_number_encrypted", sa.String(length=512), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CASCADE, unlike every other customer-facing reference in the platform:
        # a bank account has no meaning without its customer, whereas a
        # transaction referencing that customer is a financial record and uses
        # RESTRICT.
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="beneficiary_bank_accounts_customer_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id", name="beneficiary_bank_accounts_pkey"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # CASCADE reaches both tables, their primary keys, the foreign key and the
    # three enum types in one statement, plus any foreign key another schema
    # holds into customers.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
