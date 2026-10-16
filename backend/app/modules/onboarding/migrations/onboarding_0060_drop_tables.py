"""Drop the two tables the CRM retired: ``qualification_reason_code`` and
``bank_activity_finding``.

Revision ID: onboarding_0060_drop_tables
Revises: onboarding_0059_deal_reference

Why
---
* ``qualification_reason_code`` — the reasons are served from code
  (``domain/qualification_reason_codes.py``); only migrations ever changed the table.
* ``bank_activity_finding`` — nothing writes it, and no bank feed is planned.

Neither is read or written by this release or the one before it, so an instance of the
release before, still serving while a deploy replaces it, is unaffected. That is why
these two go now and the retired **columns** do not: the release before still maps
``exporter_profile.relationship_manager``, ``exporter_gstin.address`` and the result's
``reviewed_by`` / ``review_status`` / ``evidence_reference`` — ``deferred``, which keeps
them out of reads but not out of inserts — so dropping them under it would fail every
company creation and every recorded check until it stopped. This release declares them
on their tables without mapping them; ``onboarding_0061_drop_columns`` drops
them.

Guard
-----
The revision **refuses**, changing nothing, while ``bank_activity_finding`` holds a row:
it exists nowhere else. ``qualification_reason_code`` holds only the nine codes the
catalogue in code repeats.

Rollback
--------
The downgrade recreates both tables as they were, the reason codes re-seeded with the
nine rows migrations 0017 and 0031 left.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0060_drop_tables"
down_revision: str | None = "onboarding_0059_deal_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The reason codes as migrations 0017 and 0031 left them: (code, label, requires_note,
#: active). Written out, not imported: a downgrade restores what this revision dropped.
REASON_CODES: tuple[tuple[str, str, bool, bool], ...] = (
    ("deal_size_out_of_range", "Deal size outside our range", False, True),
    ("geography_not_supported", "Trade corridor we do not serve", False, False),
    ("industry_not_supported", "Industry we do not finance", False, True),
    ("insufficient_information", "Not enough information to qualify", False, True),
    ("no_export_history", "No export track record", False, False),
    ("no_export_licence", "No export licence", False, False),
    ("other", "Other (explain in the note)", True, True),
    ("revenue_below_threshold", "Revenue below the threshold", False, True),
    ("years_in_business_below_threshold", "Too few years in business", False, True),
)


def upgrade() -> None:
    findings = int(
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM {SCHEMA}.bank_activity_finding"))
        .scalar()
        or 0
    )
    if findings:
        raise RuntimeError(
            f"onboarding_0060 refuses, changing nothing: bank_activity_finding holds "
            f"{findings} row(s), which exist nowhere else. Export them, delete them, then "
            "upgrade again."
        )
    op.drop_table("bank_activity_finding", schema=SCHEMA)
    op.drop_table("qualification_reason_code", schema=SCHEMA)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    reason_codes = op.create_table(
        "qualification_reason_code",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("requires_note", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_reason_code"),
        sa.UniqueConstraint("code", name="uq_qualification_reason_code_code"),
        schema=SCHEMA,
    )
    op.execute(
        reason_codes.insert().values(
            [
                {
                    "id": sa.text("gen_random_uuid()"),
                    "code": code,
                    "label": label,
                    "requires_note": requires_note,
                    "active": active,
                }
                for code, label, requires_note, active in REASON_CODES
            ]
        )
    )

    op.create_table(
        "bank_activity_finding",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=False, server_default=sa.text("'REVIEW'")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="bank_activity_finding_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_bank_activity_finding_customer_id", "bank_activity_finding", ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_bank_activity_finding_customer_status",
        "bank_activity_finding",
        ["customer_id", "status"],
        schema=SCHEMA,
    )
