"""``CompanyBankAccount`` — a bank account a company is paid into.

Each row is **one version** of an account's details. A new account, or a change to an
existing one, starts ``PENDING_APPROVAL``; once approved it is ``PENDING_VERIFICATION``;
a cheque, a bank letter or a passed bank-account verification makes it ``VERIFIED``.
It may instead be ``REJECTED``, and a verified account may later be made ``INACTIVE``.

A **change** is a new row whose ``replaces_id`` names the account it replaces. The old
one stays in force — verified, primary if it was — until the new one is verified, at
which point the old one becomes ``INACTIVE`` and hands the primary flag over.

The account number and IBAN are stored **encrypted** (``platform/security/field_cipher``),
with their last four characters kept apart for display; nothing else about an account
is secret. Only a ``VERIFIED`` account may be primary, and at most one per currency is.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

ACCOUNT_TYPES = ("CURRENT", "EEFC", "SAVINGS", "OTHER")
STATUSES = ("PENDING_APPROVAL", "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "INACTIVE")
VERIFICATION_METHODS = ("CANCELLED_CHEQUE", "BANK_LETTER", "PENNY_DROP")


#: A verified account says how, by whom, and on what evidence.
VERIFIED_EVIDENCE = (
    "verified_at IS NULL OR (verification_method IS NOT NULL AND verified_by IS NOT NULL "
    "AND (evidence_document_id IS NOT NULL OR verification_result_id IS NOT NULL))"
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class CompanyBankAccount(AnerModel):
    __tablename__ = "company_bank_account"
    __table_args__ = (
        Index("ix_company_bank_account_customer_id", "customer_id"),
        Index(
            "uq_company_bank_account_primary_per_currency",
            "customer_id",
            "currency",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        CheckConstraint(_in("account_type", ACCOUNT_TYPES), name="ck_company_bank_account_type"),
        CheckConstraint(_in("status", STATUSES), name="ck_company_bank_account_status"),
        CheckConstraint(
            f"verification_method IS NULL OR {_in('verification_method', VERIFICATION_METHODS)}",
            name="ck_company_bank_account_method",
        ),
        CheckConstraint(
            "account_number_encrypted IS NOT NULL OR iban_encrypted IS NOT NULL",
            name="ck_company_bank_account_has_number",
        ),
        # Only a verified account is paid into.
        CheckConstraint(
            "NOT is_primary OR status = 'VERIFIED'", name="ck_company_bank_account_primary_verified"
        ),
        CheckConstraint(VERIFIED_EVIDENCE, name="ck_company_bank_account_verified_evidence"),
        CheckConstraint(
            "status <> 'VERIFIED' OR verified_at IS NOT NULL",
            name="ck_company_bank_account_verified_at",
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR (rejection_reason IS NOT NULL AND length(btrim(rejection_reason)) > 0)",
            name="ck_company_bank_account_rejection_reason",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_company_bank_account_currency"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_company_bank_account_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    account_holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    account_number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    iban_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    iban_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(11), nullable=True)
    swift_bic: Mapped[str | None] = mapped_column(String(11), nullable=True)
    #: ISO 4217.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The Authorised Dealer code an exporter's bank is registered under.
    ad_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="PENDING_APPROVAL"
    )
    #: The account this version replaces; it stays in force until this one is verified.
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.company_bank_account.id",
            name="fk_company_bank_account_replaces",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(24), nullable=True)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.crm_document.id",
            name="fk_company_bank_account_evidence_document",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    verification_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.verification_result.id",
            name="fk_company_bank_account_verification_result",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["ACCOUNT_TYPES", "STATUSES", "VERIFICATION_METHODS", "CompanyBankAccount"]
