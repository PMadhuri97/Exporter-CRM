"""Trade history: relationships, invoices and their outcomes.

Revision ID: onboarding_0037_trade_history
Revises: onboarding_0036_deal_branch

Why
---
What two companies have traded before is the strongest evidence a trade-finance
decision has, and the CRM has nowhere to record it. Three tables:

* ``trade_relationship`` — one row per ordered ``(seller, buyer)`` pair. Ordered, not
  symmetric: A selling to B is a different relationship from B selling to A.
  **No column on ``deal``** (no ``deal.relationship_id``): a deal already names
  both parties, so a stored link
  would be a second copy of the same fact able to drift from it.
* ``trade_invoice`` — a fact about the past, with its **identity frozen** once
  written. ``deal_id`` is nullable, because past trade predates us.
* ``trade_invoice_outcome`` — append-only superseding chain, the same shape
  ``verification_review`` uses: a payment story is a sequence of things we learned,
  and the earlier belief stays part of the record.

Three rules the database holds, not just the service
----------------------------------------------------
#. **An invoice's identity is immutable.** ``relationship_id``, ``invoice_number``,
   ``invoice_date``, ``amount``, ``currency`` and ``deal_id`` cannot change once set
   (``prevent_field_mutation_when_set``, the pattern 0002 already uses). An invoice
   whose amount could be edited afterwards is not evidence of anything.
#. **Outcomes are append-only.** ``UPDATE`` and ``DELETE`` are refused outright by
   ``public.prevent_mutation()``, the function this schema's other append-only tables
   use. A correction is a new row naming the one it supersedes.
#. **The chain is a line, not a tree.** One head per invoice
   (``uq_trade_invoice_outcome_first``, partial on ``supersedes_outcome_id IS NULL``)
   and one row superseding each earlier row
   (``uq_trade_invoice_outcome_supersedes``). Together they stop two people each
   correcting the same outcome without seeing the other's.

Currency is stored and never converted, so there is no rate column and no
reporting currency; ``ck_trade_invoice_currency`` holds it to ISO 4217's shape,
because a code nobody can look up is permanent nonsense in a column that is never
recomputed.

No data steps: three new tables. The relationship backfill for existing deals is
``backfill_trade_relationships`` and runs separately, after the buyer migration.

Rollback
--------
The downgrade drops the three tables (invoices and outcomes first, by FK order) and
the two enums. Everything recorded about past trade goes with them, so ``pg_dump``
first and mean it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0037_trade_history"
down_revision: str | None = "onboarding_0036_deal_branch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_PAYMENT_STATUS = postgresql.ENUM(
    "PAID",
    "UNPAID",
    "PARTIAL",
    "DISPUTED",
    "UNKNOWN",
    name="trade_payment_status_enum",
    schema=SCHEMA,
    # Created explicitly in `upgrade`, so `create_table` must not try again:
    # a `postgresql.ENUM` passed to a Column creates its type by default, and the
    # second attempt is a DuplicateObject that aborts the whole migration.
    create_type=False,
)
_PROOF_STATUS = postgresql.ENUM(
    "CLAIMED",
    "PROVEN",
    name="trade_proof_status_enum",
    schema=SCHEMA,
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    _PAYMENT_STATUS.create(bind, checkfirst=False)
    _PROOF_STATUS.create(bind, checkfirst=False)

    # ── trade_relationship ───────────────────────────────────────────────────
    op.create_table(
        "trade_relationship",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("seller_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["seller_company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_trade_relationship_seller",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["buyer_company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_trade_relationship_buyer",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "seller_company_id", "buyer_company_id", name="uq_trade_relationship_pair"
        ),
        sa.CheckConstraint(
            "seller_company_id <> buyer_company_id",
            name="ck_trade_relationship_not_self",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_trade_relationship_seller",
        "trade_relationship",
        ["seller_company_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_trade_relationship_buyer",
        "trade_relationship",
        ["buyer_company_id", "created_at"],
        schema=SCHEMA,
    )

    # ── trade_invoice ────────────────────────────────────────────────────────
    op.create_table(
        "trade_invoice",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            [f"{SCHEMA}.trade_relationship.id"],
            name="fk_trade_invoice_relationship",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "relationship_id", "invoice_number", name="uq_trade_invoice_number"
        ),
        sa.UniqueConstraint("id", "relationship_id", name="uq_trade_invoice_id_relationship"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_trade_invoice_currency"),
        sa.CheckConstraint("amount > 0", name="ck_trade_invoice_amount_positive"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_trade_invoice_relationship",
        "trade_invoice",
        ["relationship_id", sa.text("invoice_date DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_trade_invoice_deal",
        "trade_invoice",
        ["deal_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("deal_id IS NOT NULL"),
    )
    # An invoice's identity is frozen once written. `prevent_field_mutation_when_set`
    # allows NULL -> a value once, which matters for `deal_id`: an invoice recorded as
    # past trade can later be tied to the deal that produced it, and never re-tied.
    op.execute(
        f"""
        CREATE TRIGGER trg_trade_invoice_identity_immutability
        BEFORE UPDATE ON {SCHEMA}.trade_invoice
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set(
            'relationship_id', 'invoice_number', 'invoice_date', 'amount', 'currency',
            'deal_id'
        );
        """
    )

    # ── trade_invoice_outcome ────────────────────────────────────────────────
    op.create_table(
        "trade_invoice_outcome",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_status", _PAYMENT_STATUS, nullable=False),
        sa.Column("amount_paid", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "proof_status", _PROOF_STATUS, nullable=False, server_default="CLAIMED"
        ),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=True),
        sa.Column("recorded_by", sa.String(255), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("supersedes_outcome_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            [f"{SCHEMA}.trade_invoice.id"],
            name="fk_trade_invoice_outcome_invoice",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "invoice_id", name="uq_trade_invoice_outcome_id_invoice"),
        sa.UniqueConstraint(
            "supersedes_outcome_id", name="uq_trade_invoice_outcome_supersedes"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_outcome_id", "invoice_id"],
            [
                f"{SCHEMA}.trade_invoice_outcome.id",
                f"{SCHEMA}.trade_invoice_outcome.invoice_id",
            ],
            name="fk_trade_invoice_outcome_supersedes",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "supersedes_outcome_id IS NULL OR supersedes_outcome_id <> id",
            name="ck_trade_invoice_outcome_not_self",
        ),
        sa.CheckConstraint(
            "supersedes_outcome_id IS NULL"
            " OR (evidence_note IS NOT NULL AND btrim(evidence_note) <> '')",
            name="ck_trade_invoice_outcome_supersede_note",
        ),
        sa.CheckConstraint(
            "amount_paid IS NULL OR amount_paid >= 0",
            name="ck_trade_invoice_outcome_amount_paid",
        ),
        sa.CheckConstraint(
            "payment_status <> 'PARTIAL' OR amount_paid IS NOT NULL",
            name="ck_trade_invoice_outcome_partial_amount",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_trade_invoice_outcome_first",
        "trade_invoice_outcome",
        ["invoice_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes_outcome_id IS NULL"),
    )
    op.create_index(
        "ix_trade_invoice_outcome_invoice",
        "trade_invoice_outcome",
        ["invoice_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    # Append-only, by the same function every other append-only table here uses.
    op.execute(
        f"""
        CREATE TRIGGER trg_trade_invoice_outcome_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.trade_invoice_outcome
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_trade_invoice_outcome_append_only "
        f"ON {SCHEMA}.trade_invoice_outcome;"
    )
    op.drop_table("trade_invoice_outcome", schema=SCHEMA)
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_trade_invoice_identity_immutability "
        f"ON {SCHEMA}.trade_invoice;"
    )
    op.drop_table("trade_invoice", schema=SCHEMA)
    op.drop_table("trade_relationship", schema=SCHEMA)

    bind = op.get_bind()
    _PROOF_STATUS.drop(bind, checkfirst=False)
    _PAYMENT_STATUS.drop(bind, checkfirst=False)
