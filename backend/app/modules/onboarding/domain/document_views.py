"""Read-model view types for documents.

Pure data structures — no I/O, no session — the same pattern as ``deal_views.py``
and ``engagement_views.py``. ``DocumentService`` assembles them.

``DocumentCategoryView`` is the catalogue as data: a screen asks the server which
categories are valid where the user is standing, and which types each one accepts,
rather than holding a copy of architecture §3.4's table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)
from app.modules.onboarding.domain.storage import DocumentScanStatus


@dataclass(frozen=True)
class DocumentView:
    """One document row.

    Carries no storage key and no link. The key is an internal address
    and a link is a separate, deliberate request — handing one out with every
    list would mint credentials nobody asked for.
    """

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
    scanner_name: str | None

    @property
    def is_downloadable(self) -> bool:
        """Whether content may be served — by state, never by role (contract §4)."""
        return self.scan_status.is_servable


@dataclass(frozen=True)
class DocumentTypeView:
    key: str
    label: str


@dataclass(frozen=True)
class DocumentCategoryView:
    """One category a caller may file against here, and the types it accepts."""

    category: DocumentCategory
    owner_kind: DocumentOwnerKind
    types: tuple[DocumentTypeView, ...]


@dataclass(frozen=True)
class DownloadLinkView:
    """A time-limited way to fetch one document's content."""

    document_id: uuid.UUID
    url: str
    expires_at: datetime
