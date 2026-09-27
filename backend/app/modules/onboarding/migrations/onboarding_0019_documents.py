"""Documents on a company or on a deal (L3-09).

Revision ID: onboarding_0019_documents
Revises: onboarding_0018_deal_buyer

Numbered 0019 per the migration register, parented on 0018 as the register's
agreed order (0016 → 0018 → 0019) expects. ``onboarding_0019_documents`` is 25
characters, inside the register's 32-character limit on
``alembic_version.version_num``.

What it adds, all in the ``onboarding`` schema:

* ``crm_document_category_enum`` — the ten fixed architecture §3.4 categories.
* ``crm_document_source_enum`` — ``RXIL``, ``EXPORTER_UPLOAD``, ``INTERNAL``,
  ``SYSTEM``.
* ``crm_document_scan_status_enum`` — ``PENDING_SCAN``, ``AVAILABLE``,
  ``QUARANTINED``, ``SCAN_FAILED``.
* ``crm_document`` — owned by a company **or** a deal, with
  ``ck_crm_document_one_owner`` requiring exactly one; the category, the type (a
  settings value, so a plain string), the source, the file's own details, the scan
  status and scanner, and the **relative storage key only** (decision D8).

**Document types are not an enum and get no table.** Architecture §3.4 makes them
settings: ``deployments/gitops/reference-data/crm/documents/document-types.yaml``,
validated at the service boundary. Adding a type is a GitOps change, not a
migration — which is the property this migration exists to preserve.

**All three enums are created in the ordinary transactional body**, never with
``ALTER TYPE ... ADD VALUE`` in an autocommit block: the register names that as
something that has broken this repository before.

**Nothing here stores a cloud address.** ``storage_key`` is relative and unique,
so the provider can change without touching a row, and two rows can never point at
one object — which would make a delete ambiguous and a download unattributable.

Downgrade drops the table and the three enums, **losing every document row**. The
objects themselves are untouched: they live on disk (or, later, in S3) under keys
this table was the only index for, so a downgrade orphans them rather than
deleting them. That is deliberate — deleting a customer's paperwork because a
migration was rolled back would be worse — but it means a downgrade leaves files
behind that nothing can find. Lossy in both directions; downgrade only if you mean
it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0019_documents"
down_revision: str | None = "onboarding_0018_deal_buyer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: Architecture §3.4's ten categories. Which owner each belongs to is a rule in
#: `document_enums.py`, not a column: it never varies per row.
CATEGORIES = (
    "ENTITY_KYC",
    "COMPLIANCE_SCREENING",
    "COMPANY_MARKET_REVIEW",
    "PRE_SHIPMENT",
    "SHIPPING",
    "CUSTOMS_AND_REGULATORY",
    "BUYER",
    "BANKING",
    "INSURANCE",
    "OTHER",
)
SOURCES = ("RXIL", "EXPORTER_UPLOAD", "INTERNAL", "SYSTEM")
SCAN_STATUSES = ("PENDING_SCAN", "AVAILABLE", "QUARANTINED", "SCAN_FAILED")

category_enum = postgresql.ENUM(
    *CATEGORIES, name="crm_document_category_enum", schema=SCHEMA, create_type=False
)
source_enum = postgresql.ENUM(
    *SOURCES, name="crm_document_source_enum", schema=SCHEMA, create_type=False
)
scan_status_enum = postgresql.ENUM(
    *SCAN_STATUSES, name="crm_document_scan_status_enum", schema=SCHEMA, create_type=False
)
_ENUMS = (category_enum, source_enum, scan_status_enum)

#: Architecture §3.4: a document belongs either to a company or to a deal.
#: `num_nonnulls` rather than a hand-written pair of IS NULL clauses — one
#: expression that stays correct if a third owner kind is ever added.
_ONE_OWNER_CONSTRAINT = "num_nonnulls(company_id, deal_id) = 1"


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "crm_document",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", category_enum, nullable=False),
        # A settings value (architecture §3.4), so a string: adding a type is a
        # GitOps change, not a migration.
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "scan_status", scan_status_enum, nullable=False, server_default="PENDING_SCAN"
        ),
        sa.Column("scanner_name", sa.String(length=100), nullable=True),
        # Relative only — decision D8. No bucket, no host, no `s3://`.
        sa.Column("storage_key", sa.String(length=500), nullable=False),
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
            name="fk_crm_document_company_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            [f"{SCHEMA}.deal.id"],
            name="fk_crm_document_deal_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_ONE_OWNER_CONSTRAINT, name="ck_crm_document_one_owner"),
        sa.UniqueConstraint("storage_key", name="uq_crm_document_storage_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_crm_document_company_recent",
        "crm_document",
        ["company_id", "uploaded_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_crm_document_deal_recent",
        "crm_document",
        ["deal_id", "uploaded_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_crm_document_scan_status", "crm_document", ["scan_status"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_crm_document_scan_status", table_name="crm_document", schema=SCHEMA)
    op.drop_index("ix_crm_document_deal_recent", table_name="crm_document", schema=SCHEMA)
    op.drop_index(
        "ix_crm_document_company_recent", table_name="crm_document", schema=SCHEMA
    )
    op.drop_table("crm_document", schema=SCHEMA)
    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=False)
