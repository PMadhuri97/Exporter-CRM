"""A company's bank accounts, proposed, approved and verified

``onboarding.company_bank_account``: one row per version of an account's details.
PENDING_APPROVAL -> PENDING_VERIFICATION -> VERIFIED, or REJECTED; a verified account
may become INACTIVE. A change is a new row naming the one it replaces (``replaces_id``).

The account number and IBAN are stored encrypted, with their last four characters
apart for display. Only a VERIFIED account may be primary, one per currency.

Revision ID: onboarding_0048_bank_accounts
Revises: onboarding_0047_addresses
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0048_bank_accounts"
down_revision: str | None = "onboarding_0047_addresses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "company_bank_account"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, postgresql.TIMESTAMP(timezone=True), nullable=True)


def _who(name: str) -> sa.Column:
    return sa.Column(name, sa.String(length=255), nullable=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_holder_name", sa.String(length=255), nullable=False),
        sa.Column("bank_name", sa.String(length=255), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("account_number_encrypted", sa.String(length=512), nullable=True),
        sa.Column("account_number_last4", sa.String(length=4), nullable=True),
        sa.Column("iban_encrypted", sa.String(length=512), nullable=True),
        sa.Column("iban_last4", sa.String(length=4), nullable=True),
        sa.Column("ifsc", sa.String(length=11), nullable=True),
        sa.Column("swift_bic", sa.String(length=11), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("ad_code", sa.String(length=20), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="PENDING_APPROVAL"
        ),
        sa.Column("replaces_id", postgresql.UUID(as_uuid=True), nullable=True),
        _who("proposed_by"),
        sa.Column("proposal_reason", sa.Text(), nullable=True),
        _who("approved_by"),
        _stamp("approved_at"),
        _who("rejected_by"),
        _stamp("rejected_at"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("verification_method", sa.String(length=24), nullable=True),
        sa.Column("evidence_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verification_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        _who("verified_by"),
        _stamp("verified_at"),
        _who("deactivated_by"),
        _stamp("deactivated_at"),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_company_bank_account_customer_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaces_id"],
            [f"{SCHEMA}.{TABLE}.id"],
            name="fk_company_bank_account_replaces",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_document_id"],
            [f"{SCHEMA}.crm_document.id"],
            name="fk_company_bank_account_evidence_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_result_id"],
            [f"{SCHEMA}.verification_result.id"],
            name="fk_company_bank_account_verification_result",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _in("account_type", ("CURRENT", "EEFC", "SAVINGS", "OTHER")),
            name="ck_company_bank_account_type",
        ),
        sa.CheckConstraint(
            _in(
                "status",
                ("PENDING_APPROVAL", "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "INACTIVE"),
            ),
            name="ck_company_bank_account_status",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR "
            + _in("verification_method", ("CANCELLED_CHEQUE", "BANK_LETTER", "PENNY_DROP")),
            name="ck_company_bank_account_method",
        ),
        sa.CheckConstraint(
            "account_number_encrypted IS NOT NULL OR iban_encrypted IS NOT NULL",
            name="ck_company_bank_account_has_number",
        ),
        sa.CheckConstraint(
            "NOT is_primary OR status = 'VERIFIED'",
            name="ck_company_bank_account_primary_verified",
        ),
        sa.CheckConstraint(
            "verified_at IS NULL OR (verification_method IS NOT NULL AND verified_by IS NOT NULL "
            "AND (evidence_document_id IS NOT NULL OR verification_result_id IS NOT NULL))",
            name="ck_company_bank_account_verified_evidence",
        ),
        sa.CheckConstraint(
            "status <> 'VERIFIED' OR verified_at IS NOT NULL",
            name="ck_company_bank_account_verified_at",
        ),
        sa.CheckConstraint(
            "status <> 'REJECTED' OR (rejection_reason IS NOT NULL "
            "AND length(btrim(rejection_reason)) > 0)",
            name="ck_company_bank_account_rejection_reason",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_company_bank_account_currency"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_company_bank_account_customer_id", TABLE, ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "uq_company_bank_account_primary_per_currency",
        TABLE,
        ["customer_id", "currency"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_company_bank_account_primary_per_currency", TABLE, schema=SCHEMA)
    op.drop_index("ix_company_bank_account_customer_id", TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
