"""The deal's new columns — **owner: Developer 2** (allocation F2).

Revision ID: onboarding_0028_deal_foundation
Revises: onboarding_0027_dev1_expiry

``onboarding_0028_deal_foundation`` is 31 characters, inside the register's
32-character limit on ``alembic_version.version_num``.

**Numbered 0028, after Developer 1's 0023–0027.** This was first written as 0025
on ``onboarding_0022_integrity``, before Developer 1's compliance PR merged with
0023–0027 of its own. Merged as it was, the chain had two heads and two files
labelled 0025, 0026 and 0027, so ``dev1-handover.md`` §6 had the next lane to
merge renumber from 0028 and parent on the head at that moment,
``onboarding_0027_dev1_expiry``. 0029 and 0030 follow it.

What it adds, all on ``onboarding.deal``
----------------------------------------
* ``buyer_company_id`` — nullable FK to ``exporter_profile.customer_id``
  (``RESTRICT``, like the seller's): the buyer becomes an ordinary company record
  (plan P4-4). Nullable because every deal in the database today has its buyer in
  ``deal_buyer`` instead, and the migration that fills this column is P4-6.
  ``ck_deal_buyer_is_not_the_seller`` refuses a deal a company sells to itself on.
* ``handover_snapshot JSONB`` — what the lending team was given, written at the
  moment of the handover (plan P2-7). Filled and frozen by 0029; this revision
  only makes the column exist.
* ``seller_gst_registration_id`` — nullable FK to ``exporter_gstin.id``, the
  branch a deal is invoiced from (plan P6-6). **Verified before writing this:**
  ``exporter_gstin`` inherits ``AnerModel``, so ``id`` is a real UUID primary key
  and no key had to be agreed with Developer 3.

**No trigger change here.** ``prevent_terminal_deal_change()`` is extended once
per column that needs freezing, by the task that starts writing it: 0029 for
``handover_snapshot``, P4-4 for ``buyer_company_id`` and P6-6 for
``seller_gst_registration_id``. Freezing a column nothing writes yet would only
make the backfills in those tasks harder.

Additive and reversible: downgrade drops the three columns and loses whatever was
in them. Nothing writes them until 0029, so a downgrade run immediately after this
one loses nothing at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0028_deal_foundation"
down_revision: str | None = "onboarding_0027_dev1_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: A company does not sell to itself. Written as a NULL-tolerant check because the
#: column is nullable for every legacy deal.
_NOT_THE_SELLER = "buyer_company_id IS NULL OR buyer_company_id <> company_id"


def upgrade() -> None:
    op.add_column(
        "deal",
        sa.Column("buyer_company_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "deal",
        # `none_as_null`, like `qualification_criterion.allowed_values`: "no
        # snapshot" is SQL NULL, never the JSON value `null`, so the set-once
        # trigger in 0029 has one absence to compare against instead of two.
        sa.Column("handover_snapshot", postgresql.JSONB(none_as_null=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "deal",
        sa.Column(
            "seller_gst_registration_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_deal_buyer_company_id",
        "deal",
        "exporter_profile",
        ["buyer_company_id"],
        ["customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        # RESTRICT, the same as the seller's FK: a company someone bought from is
        # part of the record of what was financed, and deleting it would destroy
        # that silently.
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_deal_seller_gst_registration_id",
        "deal",
        "exporter_gstin",
        ["seller_gst_registration_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_deal_buyer_is_not_the_seller", "deal", _NOT_THE_SELLER, schema=SCHEMA
    )
    # "This company's deals as the buyer, newest first" — the read P4-8 serves,
    # the mirror of `ix_deal_company_recent`.
    op.create_index(
        "ix_deal_buyer_company_recent",
        "deal",
        ["buyer_company_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_deal_buyer_company_recent", table_name="deal", schema=SCHEMA)
    op.drop_constraint(
        "ck_deal_buyer_is_not_the_seller", "deal", type_="check", schema=SCHEMA
    )
    op.drop_constraint(
        "fk_deal_seller_gst_registration_id", "deal", type_="foreignkey", schema=SCHEMA
    )
    op.drop_constraint(
        "fk_deal_buyer_company_id", "deal", type_="foreignkey", schema=SCHEMA
    )
    op.drop_column("deal", "seller_gst_registration_id", schema=SCHEMA)
    op.drop_column("deal", "handover_snapshot", schema=SCHEMA)
    op.drop_column("deal", "buyer_company_id", schema=SCHEMA)
