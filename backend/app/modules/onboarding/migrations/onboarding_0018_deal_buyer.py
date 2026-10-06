"""Deals and their buyers.

Revision ID: onboarding_0018_deal_buyer
Revises: onboarding_0016_engagement

Numbered 0018 per the migration register, and parented on 0016 because 0016 is
the head when this is written: the conversation gauge merged first, exactly as
the agreed order (0016 → 0018 → 0019) expects. Numbers are labels, not order —
``down_revision`` is the order (register §2) — and because 0016 landed first,
**nothing is re-parented here**: re-parenting falls to the later merger.

``onboarding_0018_deal_buyer`` is 26 characters, inside the register's
32-character limit on ``alembic_version.version_num``.

What it adds, all in the ``onboarding`` schema:

* ``deal_stage_enum`` — the four architecture §3.3 values.
* ``deal`` — many per company, a real foreign key to
  ``exporter_profile.customer_id`` with ``ON DELETE RESTRICT``, the stage, a
  withdrawal reason required exactly when the stage is ``WITHDRAWN``,
  and ``handed_over_at``, which the handover fills.
* ``deal_buyer`` — one row per deal (unique ``deal_id``), the buyer's name,
  country and identifiers (architecture §3.3).

**The enum is created in the ordinary transactional body**, never with
``ALTER TYPE ... ADD VALUE`` in an autocommit block: the register names that as
something that has broken this repository before, and
``onboarding_0016_engagement`` is the pattern followed here.

**Nothing on ``exporter_profile`` is touched.** The conversation gauge that
opening a deal moves is engagement's column, written through its service
(seam S1), and ``background_check`` is the background check's column in 0015,
which has not landed — this migration does not create it, and the handover guard
reads it through the published helper rather than declaring it here
(``company-record.md`` §2.4).

Downgrade drops both tables and the enum, **losing every deal and buyer row** —
that is lossy, and a deal is the record of a financing need someone worked on, so
downgrade only if you mean it. The deal stages already recorded in
``exporter_lifecycle_history`` survive: that table stores them as strings and this
migration does not touch it. The rows it leaves behind will refer to deal ids that
no longer exist, which is the honest consequence of dropping the deals — the
history is a log, not a foreign-key graph, and ``deal_id`` carries no constraint
to ``deal`` for exactly this reason (history contract §1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0018_deal_buyer"
down_revision: str | None = "onboarding_0016_engagement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The four deal stages (architecture §3.3, deal contract §1).
DEAL_STAGES = ("OPEN", "GATHERING_PAPERWORK", "HANDED_OVER", "WITHDRAWN")

deal_stage_enum = postgresql.ENUM(
    *DEAL_STAGES, name="deal_stage_enum", schema=SCHEMA, create_type=False
)

#: A withdrawal carries its reason, and nothing else does. Both
#: halves, so the column cannot fill with reasons for live deals.
_WITHDRAWAL_REASON_CONSTRAINT = (
    "(stage = 'WITHDRAWN' AND withdrawal_reason IS NOT NULL)"
    " OR (stage <> 'WITHDRAWN' AND withdrawal_reason IS NULL)"
)


def upgrade() -> None:
    deal_stage_enum.create(op.get_bind(), checkfirst=False)

    # ── 1. The deal ─────────────────────────────────────────────────────────
    op.create_table(
        "deal",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=False),
        sa.Column("stage", deal_stage_enum, nullable=False, server_default="OPEN"),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        sa.Column("handed_over_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_deal_company_id",
            # RESTRICT, not CASCADE: a company with deals must not be deletable,
            # because deleting it would destroy the record of what was financed.
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _WITHDRAWAL_REASON_CONSTRAINT, name="ck_deal_withdrawal_reason"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deal_company_recent", "deal", ["company_id", "created_at"], schema=SCHEMA
    )
    op.create_index("ix_deal_stage", "deal", ["stage"], schema=SCHEMA)

    # ── 2. The buyer ────────────────────────────────────────────────────────
    op.create_table(
        "deal_buyer",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("tax_id", sa.String(length=100), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            [f"{SCHEMA}.deal.id"],
            name="fk_deal_buyer_deal_id",
            ondelete="CASCADE",
        ),
        # One buyer per deal (deal contract §3): "the buyer" on the handover
        # payload has to be unambiguous.
        sa.UniqueConstraint("deal_id", name="uq_deal_buyer_deal_id"),
        sa.CheckConstraint("country ~ '^[A-Z]{2}$'", name="ck_deal_buyer_country_iso"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("deal_buyer", schema=SCHEMA)
    op.drop_index("ix_deal_stage", table_name="deal", schema=SCHEMA)
    op.drop_index("ix_deal_company_recent", table_name="deal", schema=SCHEMA)
    op.drop_table("deal", schema=SCHEMA)
    deal_stage_enum.drop(op.get_bind(), checkfirst=False)
