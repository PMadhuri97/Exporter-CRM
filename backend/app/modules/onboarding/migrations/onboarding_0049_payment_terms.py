"""Payment terms, a company's default term, and a deal's value, currency and term

``onboarding.payment_term`` is the list administrators keep under Settings → Rules.
Versioned: an edit or a retirement writes a new version of the term (same ``code``,
``version + 1``) and marks the old one superseded (``is_current`` false), so a deal
keeps the exact term it was agreed on. Seeded with the common terms.

``exporter_profile.default_payment_term_id`` is a company's default; a new deal takes
the current version of it. ``deal`` gains ``value_amount``, ``currency`` (ISO 4217),
``payment_term_id`` and ``payment_term_override_reason`` (why a deal differs from its
company's default).

A closed deal's value, currency and term no longer change: they join the columns
``prevent_terminal_deal_change()`` freezes. The function is restated whole, as 0039
left it plus these four.

Revision ID: onboarding_0049_payment_terms
Revises: auth_0008_bank_permissions
Create Date: 2026-10-09
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0049_payment_terms"
down_revision: str | None = "auth_0008_bank_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
KINDS = ("ADVANCE", "LC_SIGHT", "LC_USANCE", "DP", "DA", "OPEN_ACCOUNT")
#: The kinds that run for a number of days.
DAYS_KINDS = ("LC_USANCE", "DA", "OPEN_ACCOUNT")

# (code, label, kind, days)
SEED = (
    ("ADVANCE", "Advance payment", "ADVANCE", None),
    ("LC_SIGHT", "LC at sight", "LC_SIGHT", None),
    ("LC_USANCE_60", "LC usance 60 days", "LC_USANCE", 60),
    ("LC_USANCE_90", "LC usance 90 days", "LC_USANCE", 90),
    ("DP", "Documents against payment (DP)", "DP", None),
    ("DA_30", "DA 30 days", "DA", 30),
    ("DA_60", "DA 60 days", "DA", 60),
    ("DA_90", "DA 90 days", "DA", 90),
    ("OA_30", "Open account 30 days", "OPEN_ACCOUNT", 30),
    ("OA_60", "Open account 60 days", "OPEN_ACCOUNT", 60),
    ("OA_90", "Open account 90 days", "OPEN_ACCOUNT", 90),
)

_DEAL_COLUMNS = (
    "value_amount",
    "currency",
    "payment_term_id",
    "payment_term_override_reason",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _freeze_function(*, with_terms: bool) -> str:
    """0039's function, with the deal's terms frozen too when ``with_terms``."""
    terms = (
        "".join(
            f"            OR NEW.{column} IS DISTINCT FROM OLD.{column}\n"
            for column in _DEAL_COLUMNS
        )
        if with_terms
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_terminal_deal_change()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND (NEW.stage IS DISTINCT FROM OLD.stage
            OR NEW.handed_over_at IS DISTINCT FROM OLD.handed_over_at
            OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
            OR NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.seller_gst_registration_id IS DISTINCT FROM OLD.seller_gst_registration_id
{terms}            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;

    -- 0039's rule: the buyer company may be filled in on a closed deal, never changed.
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND OLD.buyer_company_id IS NOT NULL
       AND NEW.buyer_company_id IS DISTINCT FROM OLD.buyer_company_id
    THEN
        RAISE EXCEPTION
            'deal %: its buyer company is what the lending team was given and does not change',
            OLD.id;
    END IF;

    -- 0029's rule, restated because CREATE OR REPLACE rewrites the whole body.
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND OLD.handover_snapshot IS NOT NULL
       AND NEW.handover_snapshot IS DISTINCT FROM OLD.handover_snapshot
    THEN
        RAISE EXCEPTION
            'deal %: its handover snapshot is what the lending team was given and does not change',
            OLD.id;
    END IF;

    RETURN NEW;
END;
$fn$;
"""


def upgrade() -> None:
    op.create_table(
        "payment_term",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("code", "version", name="uq_payment_term_code_version"),
        sa.CheckConstraint(_in("kind", KINDS), name="ck_payment_term_kind"),
        sa.CheckConstraint(
            f"(({_in('kind', DAYS_KINDS)}) AND days IS NOT NULL AND days > 0) "
            f"OR (NOT ({_in('kind', DAYS_KINDS)}) AND days IS NULL)",
            name="ck_payment_term_days",
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_payment_term_code"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_payment_term_current_code",
        "payment_term",
        ["code"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_current"),
    )
    table = sa.table(
        "payment_term",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("version", sa.Integer),
        sa.column("label", sa.String),
        sa.column("kind", sa.String),
        sa.column("days", sa.Integer),
        sa.column("created_by", sa.String),
        schema=SCHEMA,
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "version": 1,
                "label": label,
                "kind": kind,
                "days": days,
                "created_by": "seed",
            }
            for code, label, kind, days in SEED
        ],
    )

    op.add_column(
        "exporter_profile",
        sa.Column("default_payment_term_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_exporter_profile_default_payment_term",
        "exporter_profile",
        "payment_term",
        ["default_payment_term_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.add_column("deal", sa.Column("value_amount", sa.Numeric(18, 2), nullable=True), schema=SCHEMA)
    op.add_column("deal", sa.Column("currency", sa.String(length=3), nullable=True), schema=SCHEMA)
    op.add_column(
        "deal",
        sa.Column("payment_term_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "deal", sa.Column("payment_term_override_reason", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_deal_payment_term",
        "deal",
        "payment_term",
        ["payment_term_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_deal_value_amount", "deal", "value_amount IS NULL OR value_amount >= 0", schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_deal_currency", "deal", "currency IS NULL OR currency ~ '^[A-Z]{3}$'", schema=SCHEMA
    )
    # A value means nothing without its currency.
    op.create_check_constraint(
        "ck_deal_value_has_currency",
        "deal",
        "value_amount IS NULL OR currency IS NOT NULL",
        schema=SCHEMA,
    )
    op.execute(_freeze_function(with_terms=True))


def downgrade() -> None:
    op.execute(_freeze_function(with_terms=False))
    for name in ("ck_deal_value_has_currency", "ck_deal_currency", "ck_deal_value_amount"):
        op.drop_constraint(name, "deal", schema=SCHEMA)
    op.drop_constraint("fk_deal_payment_term", "deal", schema=SCHEMA)
    for column in reversed(_DEAL_COLUMNS):
        op.drop_column("deal", column, schema=SCHEMA)
    op.drop_constraint(
        "fk_exporter_profile_default_payment_term", "exporter_profile", schema=SCHEMA
    )
    op.drop_column("exporter_profile", "default_payment_term_id", schema=SCHEMA)
    op.drop_index("uq_payment_term_current_code", "payment_term", schema=SCHEMA)
    op.drop_table("payment_term", schema=SCHEMA)
