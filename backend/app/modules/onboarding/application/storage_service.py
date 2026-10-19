"""Storing a file and having it scanned.

Contract: ``docs/contracts/storage-and-documents.md`` §1-§4.

This service is the one place that knows the **order** of the two steps: bytes are
stored, then scanned, and the object is not servable until a clean result comes
back. It holds no database session and writes no row —
``DocumentService`` persists ``crm_document`` and calls this. Splitting it that
way is what lets the storage rules be tested without a database, and what keeps
the port free of document concepts.

**Nothing here decides who may upload.** Roles are the route's, via
``require_role``, matching the §3.7 matrix — the same split
``ConversationService`` uses.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import dataclass

import structlog

from app.modules.onboarding.domain.storage import (
    DocumentScanStatus,
    DownloadLink,
    ScannerPort,
    ScanOutcome,
    StorageOwnerType,
    StoragePort,
    build_storage_key,
)
from app.modules.onboarding.infrastructure.storage.config import (
    DOWNLOAD_LINK_TTL,
    environment_segment,
)

logger = structlog.get_logger(__name__)

#: Extension per content type we accept. An allow-list, not a guess: the
#: extension goes into the storage key, and deriving it from the uploaded file
#: name would put user-controlled text in a path (§9.3's "Watch out for").
#: A type absent from here is refused rather than stored with a made-up
#: extension — the upload route turns that into a 422.
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/msword": ".doc",
    "application/zip": ".zip",
}


class UnsupportedContentTypeError(ValueError):
    """A content type with no extension in the allow-list above.

    A domain-level ``ValueError``; the boundary maps it to a 422
    (``DocumentContentTypeNotSupportedError`` in ``exceptions.py``).
    """


class ContentDoesNotMatchTypeError(ValueError):
    """The bytes are not what the declared content type says they are.

    The type comes from the client and decides how the file is stored, previewed and
    converted, so it is checked against the content itself — an HTML page declared
    ``application/pdf`` is refused, not stored as a PDF. The boundary maps it to a 422
    (``DocumentContentMismatchError``).
    """


_PDF = b"%PDF-"
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_TIFF = (b"II*\x00", b"MM\x00*")
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc / .xls
_ZIP = b"PK\x03\x04"
#: How far into a file a PDF header may sit: readers tolerate leading junk up to 1 KiB.
_PDF_HEADER_WINDOW = 1024
#: The opening of a text upload that makes it markup rather than text. A .txt or .csv
#: has no business starting like a web page or an SVG.
_MARKUP_OPENINGS = (b"<!doctype", b"<html", b"<head", b"<body", b"<script", b"<svg", b"<?xml", b"<iframe")


def _zip_members(content: bytes) -> list[str] | None:
    """The names in a ZIP's central directory, or ``None`` if it is not a readable ZIP.
    Reads only the directory, never decompresses a member, so a ZIP bomb costs nothing."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return archive.namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return None


def _is_ooxml(content: bytes, main_part: str) -> bool:
    if not content.startswith(_ZIP):
        return False
    members = _zip_members(content)
    return members is not None and "[Content_Types].xml" in members and main_part in members


def _is_text(content: bytes) -> bool:
    head = content[:8192]
    if b"\x00" in head:
        return False
    opening = head.lstrip(b"\xef\xbb\xbf").lstrip()[:16].lower()
    return not opening.startswith(_MARKUP_OPENINGS)


def content_matches_type(content: bytes, content_type: str) -> bool:
    """Whether ``content`` really is ``content_type`` (one of the allow-list's keys).

    Judged by the file's own signature (its "magic bytes"); for Word and Excel files,
    by the parts the format requires inside the archive, so an arbitrary ZIP cannot
    pass as a .docx and reach the document converter.
    """
    normalised = content_type.strip().lower().split(";")[0]
    if normalised == "application/pdf":
        return _PDF in content[:_PDF_HEADER_WINDOW]
    if normalised == "image/jpeg":
        return content.startswith(_JPEG)
    if normalised == "image/png":
        return content.startswith(_PNG)
    if normalised == "image/tiff":
        return content.startswith(_TIFF)
    if normalised in ("text/csv", "text/plain"):
        return _is_text(content)
    if normalised == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _is_ooxml(content, "word/document.xml")
    if normalised == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return _is_ooxml(content, "xl/workbook.xml")
    if normalised in ("application/msword", "application/vnd.ms-excel"):
        return content.startswith(_OLE2)
    if normalised == "application/zip":
        return content.startswith(_ZIP) and _zip_members(content) is not None
    # A type in the allow-list with no rule here is refused: a new type must say how
    # it is recognised before it is accepted.
    return False


@dataclass(frozen=True)
class StoredDocument:
    """Everything ``DocumentService`` needs to write a ``crm_document`` row.

    Deliberately not an entity: this service has no session, so it returns facts
    rather than a row. ``scan`` carries the scanner's name as well as its verdict,
    because "who said this was clean" is part of the answer — especially while the
    answer comes from a pass-through placeholder.
    """

    storage_key: str
    size_bytes: int
    content_type: str
    scan: ScanOutcome

    @property
    def scan_status(self) -> DocumentScanStatus:
        return self.scan.status


class StorageService:
    """Store, scan, link and remove. No database, no roles, no HTTP."""

    def __init__(self, storage: StoragePort, scanner: ScannerPort) -> None:
        self._storage = storage
        self._scanner = scanner

    @property
    def scanner_name(self) -> str:
        """Which scanner this service will attribute verdicts to.

        Exposed so a screen can say *which* scanner — and so it can say
        "pass-through" honestly instead of implying a real one ran.
        """
        return self._scanner.name

    def extension_for(self, content_type: str) -> str:
        normalised = content_type.strip().lower().split(";")[0]
        try:
            return CONTENT_TYPE_EXTENSIONS[normalised]
        except KeyError as exc:
            raise UnsupportedContentTypeError(
                f"content type {content_type!r} is not accepted"
            ) from exc

    async def store(
        self,
        content: bytes,
        *,
        owner_type: StorageOwnerType,
        owner_id: uuid.UUID,
        source: str,
        document_id: uuid.UUID,
        content_type: str,
    ) -> StoredDocument:
        """Put the bytes at a key built from the contract's shape, then scan.

        The order is deliberate and is the rule the whole scan step rests on:
        an object exists before it is judged, and it is judged before it can be
        served. A caller cannot skip the scan, because the only way to get a
        ``StoredDocument`` is through here.

        ``document_id`` is supplied by the caller rather than generated here:
        ``DocumentService`` needs the id for its row, the key contains it, and generating it
        in two places would let the row and the key disagree.

        The content is checked against its declared type before anything is stored
        (``content_matches_type``): the type is the client's claim, not a fact.
        """
        extension = self.extension_for(content_type)
        if not content_matches_type(content, content_type):
            raise ContentDoesNotMatchTypeError(
                f"the content is not a valid {content_type!r} file"
            )
        key = build_storage_key(
            env=environment_segment(),
            owner_type=owner_type,
            owner_id=owner_id,
            source=source,
            document_id=document_id,
            extension=extension,
        )
        stored = await self._storage.put(key, content, content_type=content_type)
        outcome = await self._scanner.scan(key, content)

        if outcome.status is not DocumentScanStatus.AVAILABLE:
            # Contract §4: a bad verdict raises an alert. There is no alerting
            # system to call yet, so this is a warning-level event carrying
            # everything an operator would need — inventing a pager integration
            # is out of scope, and swallowing it is not.
            logger.warning(
                "document_scan_not_clean",
                key=key,
                document_id=str(document_id),
                status=outcome.status.value,
                scanner=outcome.scanner_name,
                detail=outcome.detail,
            )

        return StoredDocument(
            storage_key=stored.key,
            size_bytes=stored.size_bytes,
            content_type=stored.content_type,
            scan=outcome,
        )

    async def open_link(
        self, storage_key: str, *, scan_status: DocumentScanStatus
    ) -> DownloadLink:
        """A link for an object that is servable, or refuse.

        The status is checked **here**, not only at the route, so that no future
        caller can hand out a link to a quarantined object by forgetting to look.
        It is refused for every role: this is a state rule, not a permission
        (contract §4).
        """
        if not scan_status.is_servable:
            raise DocumentNotServableError(storage_key, scan_status)
        return await self._storage.open_link(storage_key, expires_in=DOWNLOAD_LINK_TTL)

    async def read(
        self, storage_key: str, *, scan_status: DocumentScanStatus
    ) -> bytes:
        """The bytes of a servable object, or refuse — same rule as ``open_link``."""
        if not scan_status.is_servable:
            raise DocumentNotServableError(storage_key, scan_status)
        return await self._storage.read(storage_key)

    async def put_preview(self, storage_key: str, content: bytes) -> str:
        """Keep a document's PDF preview. Not scanned: it is made by the server from
        content that has already passed the scan step."""
        stored = await self._storage.put(storage_key, content, content_type="application/pdf")
        return stored.key

    async def delete(self, storage_key: str) -> None:
        await self._storage.delete(storage_key)


class DocumentNotServableError(RuntimeError):
    """Something asked for the content of a document that is not ``AVAILABLE``.

    Carries the status so the boundary can say which one it was; mapped to a 409
    by ``DocumentNotAvailableError`` in ``exceptions.py``.
    """

    def __init__(self, storage_key: str, scan_status: DocumentScanStatus) -> None:
        self.storage_key = storage_key
        self.scan_status = scan_status
        super().__init__(
            f"document at {storage_key!r} is {scan_status.value} and cannot be served"
        )
