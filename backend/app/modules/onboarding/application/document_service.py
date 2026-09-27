"""Documents on a company or a deal — **owner: Developer 3B** (L3-09).

Contract: ``docs/contracts/storage-and-documents.md`` §4-§6. Architecture §3.4.

This is where Phase 1's storage meets the database. The order is the rule the whole
scan step rests on, and it is not negotiable:

1. the owner exists, the category belongs on that owner, and the type is one the
   settings configure — checked **before** a byte is written;
2. ``StorageService`` stores the bytes and has them scanned;
3. the row is written with the resulting status, which is ``PENDING_SCAN`` until a
   verdict says otherwise.

**Content is refused for anything that is not ``AVAILABLE``** — to every role, by
state rather than by permission. ``StorageService`` checks it too, so a future
caller that forgets cannot hand out a quarantined file.

**Nothing here decides who may upload.** Roles are the route's, via
``require_role``, matching the §3.7 matrix — the same split ``DealService`` and
``ConversationService`` use.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.storage_service import (
    DocumentNotServableError,
    StorageService,
    UnsupportedContentTypeError,
)
from app.modules.onboarding.domain.document_views import (
    DocumentCategoryView,
    DocumentTypeView,
    DocumentView,
    DownloadLinkView,
)
from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import (
    DocumentScanStatus,
    StorageKeyError,
    StorageOwnerType,
)
from app.modules.onboarding.exceptions import (
    DealNotFoundError,
    DocumentCategoryNotAllowedError,
    DocumentContentTypeNotSupportedError,
    DocumentNotAvailableError,
    DocumentNotFoundError,
    DocumentTypeNotAllowedError,
    ExporterProfileNotFoundError,
    StorageKeyRefusedError,
)
from app.modules.onboarding.infrastructure.document_type_loader import (
    is_valid_type,
    types_for,
)
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (
    CrmDocumentRepository,
)
from app.modules.onboarding.infrastructure.storage import (
    LocalDiskStorage,
    PassThroughScanner,
)

logger = structlog.get_logger(__name__)


def build_storage_service() -> StorageService:
    """The prototype's storage: local disk, behind a labelled pass-through scanner.

    One place to change when S3 and a real scanner arrive (decision D8, gate §7.6),
    rather than a constructor call in every route. Not a FastAPI dependency: it
    holds no session and nothing about it varies per request.
    """
    return StorageService(LocalDiskStorage(), PassThroughScanner())


class DocumentService:
    """Upload, list, and hand out content for documents."""

    def __init__(self, db: AsyncSession, storage: StorageService | None = None) -> None:
        self._db = db
        self._documents = CrmDocumentRepository(db)
        self._storage = storage or build_storage_service()

    @property
    def scanner_name(self) -> str:
        """Which scanner verdicts will be attributed to — ``"pass-through"`` in the
        prototype. Exposed so a screen can say so honestly (assumption A9)."""
        return self._storage.scanner_name

    # ── Read ─────────────────────────────────────────────────────────────────

    @staticmethod
    def categories_for(owner: DocumentOwnerKind) -> list[DocumentCategoryView]:
        """The categories that may be filed against ``owner``, with their types.

        A ``staticmethod`` over architecture §3.4's rules plus the settings file, so
        a screen asks the server which categories are valid where the user is
        standing instead of keeping a copy (§7.5).
        """
        return [
            DocumentCategoryView(
                category=category,
                owner_kind=category.owner_kind,
                types=tuple(
                    DocumentTypeView(key=key, label=label)
                    for key, label in types_for(category)
                ),
            )
            for category in DocumentCategory
            if category.allows(owner)
        ]

    async def get_document(self, document_id: uuid.UUID) -> DocumentView:
        return _to_view(await self._require_document(document_id))

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        categories: tuple[DocumentCategory, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DocumentView], int]:
        rows, total = await self._documents.list_for_owner(
            company_id=company_id, categories=categories, limit=limit, offset=offset
        )
        return [_to_view(row) for row in rows], total

    async def list_for_deal(
        self,
        deal_id: uuid.UUID,
        *,
        categories: tuple[DocumentCategory, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DocumentView], int]:
        rows, total = await self._documents.list_for_owner(
            deal_id=deal_id, categories=categories, limit=limit, offset=offset
        )
        return [_to_view(row) for row in rows], total

    # ── Write ────────────────────────────────────────────────────────────────

    async def upload(
        self,
        content: bytes,
        *,
        company_id: uuid.UUID | None = None,
        deal_id: uuid.UUID | None = None,
        category: DocumentCategory,
        document_type: str,
        source: DocumentSource,
        file_name: str,
        content_type: str,
        actor_id: str | None,
    ) -> DocumentView:
        """Store a file and record it against exactly one owner.

        Every rule is checked before anything is stored, so a refused upload leaves
        neither a row nor an object. The reverse order — store, then validate —
        would leave orphaned bytes on disk for every rejected request.

        The document's id is generated here because the storage key contains it
        (contract §2): one id, used for the row and the key, so the two can never
        disagree.
        """
        if (company_id is None) == (deal_id is None):
            # Mirrors `ck_crm_document_one_owner`. Checked here so the answer is a
            # 422 naming the rule rather than a Postgres check violation.
            raise DocumentCategoryNotAllowedError(
                str(category.value),
                "a document belongs to exactly one of a company or a deal",
            )

        owner_kind = (
            DocumentOwnerKind.COMPANY if company_id is not None else DocumentOwnerKind.DEAL
        )
        if not category.allows(owner_kind):
            raise DocumentCategoryNotAllowedError(
                category.value,
                f"{category.value} is filed against a {category.owner_kind.value.lower()}"
                f", not a {owner_kind.value.lower()}",
            )
        if not is_valid_type(category, document_type):
            raise DocumentTypeNotAllowedError(category.value, document_type)

        if company_id is not None:
            await self._require_company(company_id)
            owner_type, owner_id = StorageOwnerType.COMPANY, company_id
        else:
            await self._require_deal(deal_id)  # type: ignore[arg-type]
            owner_type, owner_id = StorageOwnerType.DEAL, deal_id  # type: ignore[assignment]

        document_id = uuid.uuid4()
        try:
            stored = await self._storage.store(
                content,
                owner_type=owner_type,
                owner_id=owner_id,
                source=source.value,
                document_id=document_id,
                content_type=content_type,
            )
        except UnsupportedContentTypeError as exc:
            raise DocumentContentTypeNotSupportedError(content_type) from exc
        except StorageKeyError as exc:
            raise StorageKeyRefusedError(str(exc)) from exc

        document = CrmDocument(
            id=document_id,
            company_id=company_id,
            deal_id=deal_id,
            category=category,
            document_type=document_type,
            source=source,
            # As uploaded, for display and download — never part of the key.
            file_name=file_name.strip() or "document",
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            uploaded_by=actor_id,
            uploaded_at=datetime.now(tz=UTC),
            scan_status=stored.scan_status,
            scanner_name=stored.scan.scanner_name,
            storage_key=stored.storage_key,
        )
        self._db.add(document)
        await self._db.commit()
        await self._db.refresh(document)

        logger.info(
            "document.upload.ok",
            document_id=str(document.id),
            company_id=str(company_id) if company_id else None,
            deal_id=str(deal_id) if deal_id else None,
            category=category.value,
            document_type=document_type,
            source=source.value,
            scan_status=document.scan_status.value,
            scanner=document.scanner_name,
            actor_id=actor_id,
        )
        return _to_view(document)

    # ── Content ──────────────────────────────────────────────────────────────

    async def open_download_link(self, document_id: uuid.UUID) -> DownloadLinkView:
        """A short-lived link for a document that may be served.

        Refused for **every** role when the document is not ``AVAILABLE``: an
        unscanned or quarantined file is not a permissions question (contract §4).
        """
        document = await self._require_document(document_id)
        try:
            link = await self._storage.open_link(
                document.storage_key, scan_status=document.scan_status
            )
        except DocumentNotServableError as exc:
            raise DocumentNotAvailableError(document_id, document.scan_status.value) from exc
        return DownloadLinkView(
            document_id=document.id, url=link.url, expires_at=link.expires_at
        )

    async def read_content(self, storage_key: str) -> tuple[CrmDocument, bytes]:
        """The bytes behind a signed key, with the row they belong to.

        Takes the key rather than an id because the download route is handed a
        signed key — the signature covers the key, so the key identifies the row
        (``uq_crm_document_storage_key`` makes that unambiguous). The scan status is
        re-checked here: a link minted while a document was ``AVAILABLE`` must not
        keep working if a later verdict quarantined it.
        """
        document = await self._documents.get_by_storage_key(storage_key)
        if document is None:
            raise DocumentNotFoundError(storage_key)
        try:
            content = await self._storage.read(
                document.storage_key, scan_status=document.scan_status
            )
        except DocumentNotServableError as exc:
            raise DocumentNotAvailableError(
                document.id, document.scan_status.value
            ) from exc
        return document, content

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require_document(self, document_id: uuid.UUID) -> CrmDocument:
        document = await self._documents.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document

    async def _require_company(self, company_id: uuid.UUID) -> None:
        exists = await self._db.scalar(
            select(ExporterProfile.customer_id).where(
                ExporterProfile.customer_id == company_id
            )
        )
        if exists is None:
            raise ExporterProfileNotFoundError(company_id)

    async def _require_deal(self, deal_id: uuid.UUID) -> None:
        exists = await self._db.scalar(select(Deal.id).where(Deal.id == deal_id))
        if exists is None:
            raise DealNotFoundError(deal_id)


def _to_view(document: CrmDocument) -> DocumentView:
    return DocumentView(
        id=document.id,
        company_id=document.company_id,
        deal_id=document.deal_id,
        category=document.category,
        document_type=document.document_type,
        source=document.source,
        file_name=document.file_name,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        uploaded_by=document.uploaded_by,
        uploaded_at=document.uploaded_at,
        scan_status=document.scan_status,
        scanner_name=document.scanner_name,
    )


__all__ = ["DocumentScanStatus", "DocumentService", "build_storage_service"]
