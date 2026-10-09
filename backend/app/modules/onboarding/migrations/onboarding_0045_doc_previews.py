"""A document's on-screen preview: its state and where the PDF copy is kept

People read documents on screen; only holders of `documents:download` may save a
copy. A PDF, an image or a text file is shown as it is. A Word, Excel or PowerPoint
file is converted to PDF the first time someone opens it, and the PDF is kept beside
the original so the next reader does not wait:

* ``preview_status`` — NULL until a conversion is attempted, then ``READY`` (the PDF
  is at ``preview_storage_key``) or ``UNAVAILABLE`` (the conversion failed or no
  converter is installed; the original is untouched and the screen says "Preview
  unavailable").
* ``preview_storage_key`` — set exactly when the status is ``READY``.

Neither column is part of the document's identity, so the identity trigger
(``trg_crm_document_identity_immutability``) leaves them writable.

Revision ID: onboarding_0045_doc_previews
Revises: auth_0007_business_permissions
Create Date: 2026-10-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0045_doc_previews"
down_revision: str | None = "auth_0007_business_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    op.add_column(
        "crm_document",
        sa.Column("preview_status", sa.String(length=16), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "crm_document",
        sa.Column("preview_storage_key", sa.String(length=500), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_crm_document_preview_status",
        "crm_document",
        "preview_status IS NULL OR preview_status IN ('READY', 'UNAVAILABLE')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_crm_document_preview_key_when_ready",
        "crm_document",
        "(preview_status = 'READY') = (preview_storage_key IS NOT NULL)",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_document_preview_key_when_ready", "crm_document", schema=SCHEMA
    )
    op.drop_constraint("ck_crm_document_preview_status", "crm_document", schema=SCHEMA)
    op.drop_column("crm_document", "preview_storage_key", schema=SCHEMA)
    op.drop_column("crm_document", "preview_status", schema=SCHEMA)
