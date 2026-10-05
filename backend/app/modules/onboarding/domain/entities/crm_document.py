"""``CrmDocument`` — one piece of paperwork, on a company or on a deal.

Contract: ``docs/contracts/storage-and-documents.md`` §5. Architecture §3.4,
migration 0019.

**Exactly one owner.** ``company_id`` and ``deal_id`` are both nullable, and
``ck_crm_document_one_owner`` requires exactly one to be set: a document is
company-wide paperwork *or* paperwork for one deal (architecture §3.4), never
both and never neither. Both halves are tested by direct SQL.

**Only the relative storage key is stored** — no bucket, no host,
no ``s3://``. Changing provider must not require touching a row. The original
file name and content type are columns here and never appear in the key: a
user-supplied name inside a path is a traversal surface and a rename hazard
(§9.3's "Watch out for").

**Not the legacy ``onboarding_document``.** That table hangs off
``onboarding_request`` (audit note E34) and is not extended, reused or renamed by
this record.

Mutable in one respect only: the scan status, which moves ``PENDING_SCAN`` →
``AVAILABLE``/``QUARANTINED``/``SCAN_FAILED`` once a verdict arrives. Nothing else
about a stored document changes — there is no edit route, and replacing a document
means uploading a new one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class CrmDocument(AnerModel):
    __tablename__ = "crm_document"
    __table_args__ = (
        # Exactly one owner — architecture §3.4. `num_nonnulls` rather than a
        # hand-written pair of IS NULL clauses: one expression that stays correct
        # if a third owner kind is ever added.
        CheckConstraint(
            "num_nonnulls(company_id, deal_id) = 1",
            name="ck_crm_document_one_owner",
        ),
        # Two rows pointing at one object would make `delete` ambiguous and a
        # download unattributable (contract §5.2).
        UniqueConstraint("storage_key", name="uq_crm_document_storage_key"),
        Index("ix_crm_document_company_recent", "company_id", "uploaded_at"),
        Index("ix_crm_document_deal_recent", "deal_id", "uploaded_at"),
        # The one query that crosses owners: "what is still waiting on a scan".
        Index("ix_crm_document_scan_status", "scan_status"),
        {"schema": SCHEMA},
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_crm_document_company_id",
            # RESTRICT, like the deal's: a company's paperwork is part of the
            # record, and deleting the company must not silently destroy it.
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.deal.id",
            name="fk_crm_document_deal_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    category: Mapped[DocumentCategory] = mapped_column(
        Enum(
            DocumentCategory,
            name="crm_document_category_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
    )
    #: A seeded settings value, not an enum (architecture §3.4): a new type needs
    #: no code change. Validated against the catalogue at the service boundary, so
    #: a typo is a 422 rather than a row nobody can find.
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(
            DocumentSource,
            name="crm_document_source_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
    )
    #: As uploaded, for display and download. Never part of the storage key.
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Measured from what was written, never taken from the client's claim.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scan_status: Mapped[DocumentScanStatus] = mapped_column(
        Enum(
            DocumentScanStatus,
            name="crm_document_scan_status_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
        default=DocumentScanStatus.PENDING_SCAN,
    )
    #: Which scanner reached the verdict — ``"pass-through"`` in the prototype,
    #: stored lowercase exactly as a provider is stored ``"manual"``. A reader can
    #: always tell that nothing was actually scanned.
    scanner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: **Relative** only.
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
