"""The storage and scanner ports, and the key shape — **owner: Developer 3B**
(L3-07, L3-08).

Contract: ``docs/contracts/storage-and-documents.md`` §1-§4. Architecture §3.4.

Two ``Protocol`` ports and one pure function. No I/O, no database, no FastAPI: an
implementation satisfies a port without importing it (the consumer-owned-port
convention used throughout this repository), and the key shape is testable
without touching a disk.

**The ports know nothing about documents.** ``StoragePort`` moves bytes at a key;
``ScannerPort`` judges bytes. Neither takes a category, an owner or a document
row — that is ``crm_document``'s job (Phase 3). Keeping them this narrow is what
makes swapping local disk for S3 (decision D8) a change in one file.
"""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

# ── Scan status ─────────────────────────────────────────────────────────────


class DocumentScanStatus(str, enum.Enum):
    """Where a stored object is in the scan step (architecture §3.4).

    Lives here rather than in ``document_enums.py`` because the scanner port
    returns it and the port must not import the document entity's module — the
    dependency runs the other way. Phase 3's ``crm_document`` imports it from
    here for its column.
    """

    #: Every upload lands here, and cannot be opened.
    PENDING_SCAN = "PENDING_SCAN"
    #: A clean result came back. The only status that may be served.
    AVAILABLE = "AVAILABLE"
    #: The scanner found something. Never served, and never re-scanned into
    #: availability — a quarantined object stays quarantined.
    QUARANTINED = "QUARANTINED"
    #: The scanner could not decide. Never served either: "we do not know"
    #: and "it is clean" must not collapse into the same outcome.
    SCAN_FAILED = "SCAN_FAILED"

    @property
    def is_servable(self) -> bool:
        """Whether a download may be served.

        A single place to ask, so a new status cannot accidentally default to
        downloadable by being missed at one call site.
        """
        return self is DocumentScanStatus.AVAILABLE


@dataclass(frozen=True)
class ScanOutcome:
    """What a scanner concluded, and which scanner concluded it."""

    status: DocumentScanStatus
    scanner_name: str
    detail: str | None = None


# ── Ports ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StoredObject:
    """The result of a successful write.

    ``size_bytes`` is what the implementation actually wrote, never what the
    client claimed: a declared size is a client assertion, and the row records
    the truth.
    """

    key: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class DownloadLink:
    """A time-limited way to fetch one object.

    ``url`` is **opaque to the caller.** Local disk returns an API path carrying
    a signed token; S3 will return a presigned URL. Code that parses it is
    coupled to the implementation the port exists to hide.
    """

    url: str
    expires_at: datetime


@runtime_checkable
class StoragePort(Protocol):
    """Somewhere bytes live, addressed by a relative key."""

    async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject: ...

    async def read(self, key: str) -> bytes: ...

    async def open_link(self, key: str, *, expires_in: timedelta) -> DownloadLink: ...

    async def delete(self, key: str) -> None: ...


@runtime_checkable
class ScannerPort(Protocol):
    """Something that decides whether stored bytes may be served.

    ``name`` is stored on the document row, lowercase, exactly as a verification
    provider is stored ``"manual"`` (§7.5, decision D4), so a reader can always
    tell which scanner reached a verdict — including when the answer is
    "pass-through", which is not a scanner at all.
    """

    name: str

    async def scan(self, key: str, content: bytes) -> ScanOutcome: ...


# ── The key shape ───────────────────────────────────────────────────────────


class StorageOwnerType(str, enum.Enum):
    """Who a stored object hangs off. Architecture §3.4: a document belongs
    either to a company or to a deal, never both, never neither."""

    COMPANY = "company"
    DEAL = "deal"


#: One path segment: lowercase letters, digits, hyphens and underscores. Every
#: segment of a key is checked against this, which is what makes traversal
#: (`..`), absolute paths (`/x`), drive letters (`C:`) and separators inside a
#: segment impossible to express rather than merely filtered.
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: The extension, including its dot. Sniffed from the content type, never taken
#: from the uploaded file name (§9.3's "Watch out for": a user-supplied name in
#: a key is a traversal surface and a rename hazard).
_EXTENSION = re.compile(r"^\.[a-z0-9]{1,16}$")


class StorageKeyError(ValueError):
    """A key could not be built, or was refused before any I/O.

    A plain ``ValueError`` rather than an ``AnerBaseException``: this is a domain
    rule, and the module's exception list maps it to an HTTP status at the
    boundary (``StorageKeyRefusedError`` in ``exceptions.py``). Keeping the
    domain free of FastAPI status codes is the same split every other policy in
    this module uses.
    """


def build_storage_key(
    *,
    env: str,
    owner_type: StorageOwnerType,
    owner_id: uuid.UUID,
    source: str,
    document_id: uuid.UUID,
    extension: str,
) -> str:
    """``{env}/{owner_type}/{owner_id}/{source}/{document_id}{ext}``.

    Architecture §3.4, fixed. Pure: no I/O, no clock, no settings lookup — the
    caller passes ``env`` in, so the shape is tested without an environment.

    Every variable segment is validated, so a key that would escape its root
    cannot be built in the first place. The implementation validates again
    against the real root before writing (§2.1) — two checks, because this one
    cannot know where the root is.
    """
    env_segment = env.strip().lower()
    source_segment = source.strip().lower()
    ext = extension.strip().lower()

    for label, segment in (("env", env_segment), ("source", source_segment)):
        if not _SEGMENT.match(segment):
            raise StorageKeyError(
                f"{label} segment {segment!r} is not a safe path segment"
            )
    if not _EXTENSION.match(ext):
        raise StorageKeyError(f"extension {extension!r} is not a safe extension")

    return (
        f"{env_segment}/{owner_type.value}/{owner_id}/{source_segment}/{document_id}{ext}"
    )


def is_safe_key(key: str) -> bool:
    """Whether every segment of an existing key is a safe path segment.

    Used by an implementation before it resolves a key against its root, and by
    Phase 3 before it trusts a key read back from a row. The final segment
    carries an extension, so it is checked as name plus extension.
    """
    if not key or key.startswith("/") or "\\" in key or "\0" in key:
        return False

    segments = key.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return False

    *leading, last = segments
    if not all(_SEGMENT.match(segment) for segment in leading):
        return False

    stem, dot, ext = last.rpartition(".")
    if not dot:
        return bool(_SEGMENT.match(last))
    return bool(_SEGMENT.match(stem) and _EXTENSION.match(f".{ext}"))
