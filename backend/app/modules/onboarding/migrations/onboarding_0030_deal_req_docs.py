"""Required document categories for a deal — **owner: Developer 2** (plan P2-5a,
allocation task 2.2).

Revision ID: onboarding_0030_deal_req_docs
Revises: onboarding_0029_deal_snapshot

``onboarding_0030_deal_req_docs`` is 30 characters, inside the register's
32-character limit.

Why
---
There was no requirement concept for deals at all: categories are an enum, types
are a GitOps YAML, and the legacy ``document_requirements_service.py`` serves the
``onboarding_request`` state machine instead. So nothing stopped a deal going to
the lending team with no paperwork — the handover guard checked the company's
standing and nothing about the deal.

What it adds
------------
``onboarding.deal_required_document``, versioned and append-only like
``qualification_criterion``: one row per ``(category, document_type, version)``,
with ``active`` saying whether that version requires the document or stops
requiring it. Removing a requirement writes a new version with ``active = false``;
nothing is ever updated or deleted, so what was required when stays readable.

It reuses ``crm_document_category_enum`` from migration 0019 rather than declaring
a second list of the same ten values, and carries the provenance columns every new
table carries (plan BQ-7): ``created_by``, ``created_at``, ``source``,
``source_ref``.

**This changes behaviour**, and that is the point (IQ-10): version 1 seeds one
requirement, category ``PRE_SHIPMENT`` with ``document_type = ''`` ("any type in
the category" — a proforma invoice, purchase order, sales contract or letter of
credit all satisfy it). From this migration on, a deal with no ``AVAILABLE``
pre-shipment document cannot be handed over, and the guard says which category is
missing. Deals **already** ``HANDED_OVER`` are untouched: the guard runs on the
move, so a past handover is never re-judged.

``created_by`` is ``NULL`` on the seeded row, like the seeded qualification
criteria: no person added it.

Downgrade drops the table, **losing the record of what was required when**. The
enum is left alone — 0019 owns it, and ``crm_document`` still uses it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0030_deal_req_docs"
down_revision: str | None = "onboarding_0029_deal_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "deal_required_document"

#: 0019's enum, referenced without being created again.
_CATEGORY_ENUM = postgresql.ENUM(
    name="crm_document_category_enum", schema=SCHEMA, create_type=False
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("category", _CATEGORY_ENUM, nullable=False),
        # `''` is "any type in this category" — a sentinel rather than NULL, so
        # the unique constraint below actually bites (two NULLs never collide in
        # Postgres, which would let one requirement be added twice at a version).
        sa.Column(
            "document_type", sa.String(length=100), nullable=False, server_default=""
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        # Provenance — plan BQ-7.
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "category", "document_type", "version", name="uq_deal_required_document_key_version"
        ),
        sa.CheckConstraint(
            "document_type = '' OR btrim(document_type) = document_type",
            name="ck_deal_required_document_type_clean",
        ),
        sa.CheckConstraint("version >= 1", name="ck_deal_required_document_version"),
        schema=SCHEMA,
    )

    # Append-only, by the shared guard — the same trigger 0017's versioned tables
    # use, so a reader comparing them finds one pattern.
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_append_only "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.{TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_mutation();"
    )

    # ── Seed: version 1, one requirement (IQ-10) ─────────────────────────────
    op.bulk_insert(
        sa.table(
            TABLE,
            sa.column("category", _CATEGORY_ENUM),
            sa.column("document_type"),
            sa.column("version"),
            sa.column("active"),
            sa.column("source"),
            schema=SCHEMA,
        ),
        [
            {
                "category": "PRE_SHIPMENT",
                "document_type": "",
                "version": 1,
                "active": True,
                "source": "migration_0030_seed",
            }
        ],
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_append_only ON {SCHEMA}.{TABLE};")
    op.drop_table(TABLE, schema=SCHEMA)
