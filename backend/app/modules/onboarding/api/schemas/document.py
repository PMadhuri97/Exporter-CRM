"""Request/response schemas for documents.

Contract: ``docs/contracts/storage-and-documents.md`` §5, §6.

**No response carries a storage key.** It is an internal address and
publishing it would invite a client to build its own URLs — exactly the coupling the
port exists to prevent. Content comes from an explicit link request instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.document_views import (
    DocumentCategoryView,
    DocumentView,
    DownloadLinkView,
)
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)
from app.modules.onboarding.domain.storage import DocumentScanStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    category: DocumentCategory
    document_type: str
    source: DocumentSource
    file_name: str
    content_type: str
    size_bytes: int
    uploaded_by: str | None
    uploaded_at: datetime
    scan_status: DocumentScanStatus
    #: Which scanner reached the verdict. ``"pass-through"`` in the prototype —
    #: a placeholder, not a scan. Screens display it so nobody
    #: mistakes a pass-through for a clean result.
    scanner_name: str | None
    #: Whether content may be fetched at all. ``False`` for `PENDING_SCAN`,
    #: `QUARANTINED` and `SCAN_FAILED`, for every role.
    is_downloadable: bool
    #: Whether it can be read on screen (`GET /documents/{id}/preview`): servable, and a
    #: PDF, image or text file, or a Word/Excel/PowerPoint/CSV file whose conversion to
    #: PDF has not failed.
    has_preview: bool = False

    @classmethod
    def from_view(cls, view: DocumentView) -> DocumentResponse:
        return cls(
            id=view.id,
            company_id=view.company_id,
            deal_id=view.deal_id,
            category=view.category,
            document_type=view.document_type,
            source=view.source,
            file_name=view.file_name,
            content_type=view.content_type,
            size_bytes=view.size_bytes,
            uploaded_by=view.uploaded_by,
            uploaded_at=view.uploaded_at,
            scan_status=view.scan_status,
            scanner_name=view.scanner_name,
            is_downloadable=view.is_downloadable,
            has_preview=view.has_preview,
        )


class DocumentListResponse(BaseModel):
    """``total`` is the count matching the filter, not the length of this page."""

    documents: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentTypeResponse(BaseModel):
    key: str
    label: str


class DocumentCategoryResponse(BaseModel):
    """One category valid where the caller is standing, and the types it accepts."""

    category: DocumentCategory
    owner_kind: DocumentOwnerKind
    types: list[DocumentTypeResponse]

    @classmethod
    def from_view(cls, view: DocumentCategoryView) -> DocumentCategoryResponse:
        return cls(
            category=view.category,
            owner_kind=view.owner_kind,
            types=[
                DocumentTypeResponse(key=entry.key, label=entry.label)
                for entry in view.types
            ],
        )


class DocumentCategoryListResponse(BaseModel):
    """The filing catalogue for one owner kind.

    ``scanner_name`` rides along so a screen can label the upload control with the
    scanner that will actually judge the file — ``"pass-through"`` today, which the
    screen must say out loud (gate §7.6).
    """

    categories: list[DocumentCategoryResponse]
    scanner_name: str


class DownloadLinkResponse(BaseModel):
    """A short-lived link. ``url`` is opaque: local disk returns an API path with a
    signature, S3 will return a presigned URL, and a client that parses either is
    coupled to the implementation the port hides."""

    document_id: uuid.UUID
    url: str
    expires_at: datetime

    @classmethod
    def from_view(cls, view: DownloadLinkView) -> DownloadLinkResponse:
        return cls(
            document_id=view.document_id, url=view.url, expires_at=view.expires_at
        )


class UploadDocumentMetadata(BaseModel):
    """The fields that accompany an uploaded file.

    Sent as form fields beside the file, not as a JSON body — a multipart request
    cannot carry both. ``model_config`` still forbids extras so a typo in a field
    name is a 422 rather than a silently ignored value.
    """

    model_config = ConfigDict(extra="forbid")

    category: DocumentCategory
    document_type: str = Field(min_length=1, max_length=100)
    #: Defaults to ``EXPORTER_UPLOAD``: a person uploading a file in the CRM is
    #: almost always filing something the exporter sent. ``RXIL`` and ``SYSTEM``
    #: are set by the code paths that genuinely produce them, never guessed here.
    source: DocumentSource = DocumentSource.EXPORTER_UPLOAD


__all__ = [
    "DocumentCategoryListResponse",
    "DocumentCategoryResponse",
    "DocumentListResponse",
    "DocumentResponse",
    "DocumentTypeResponse",
    "DownloadLinkResponse",
    "UploadDocumentMetadata",
]
