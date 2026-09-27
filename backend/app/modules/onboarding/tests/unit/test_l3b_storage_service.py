"""Storing and scanning, and the pass-through placeholder — L3-07, L3-08.

Contract: ``storage-and-documents.md`` §1, §4. Assumption A9.

The rule these tests exist to pin down: **an upload is stored, then scanned, and
nothing that is not `AVAILABLE` can be served — to anyone, by state rather than by
role.** A future caller must not be able to hand out a quarantined document by
forgetting to check, so the check lives in the service and is asserted here.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.modules.onboarding.application.storage_service import (
    DocumentNotServableError,
    StorageService,
    UnsupportedContentTypeError,
)
from app.modules.onboarding.domain.storage import (
    DocumentScanStatus,
    ScanOutcome,
    StorageOwnerType,
)
from app.modules.onboarding.infrastructure.storage.local_disk import LocalDiskStorage
from app.modules.onboarding.infrastructure.storage.passthrough_scanner import (
    PASS_THROUGH_SCANNER_NAME,
    PassThroughScanner,
)

COMPANY_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


class _VerdictScanner:
    """A fake scanner, to test what the service does with a verdict it cannot
    get from the pass-through one. Satisfies ``ScannerPort`` structurally — no
    subclassing, which is the point of the protocol."""

    def __init__(self, status: DocumentScanStatus, name: str = "fake") -> None:
        self.name = name
        self._status = status
        self.calls: list[str] = []

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        self.calls.append(key)
        return ScanOutcome(status=self._status, scanner_name=self.name, detail="fake")


@pytest.fixture
def service(tmp_path: Path) -> StorageService:
    return StorageService(LocalDiskStorage(root=tmp_path), PassThroughScanner())


async def _store(service: StorageService, **overrides):
    kwargs = {
        "owner_type": StorageOwnerType.COMPANY,
        "owner_id": COMPANY_ID,
        "source": "exporter_upload",
        "document_id": DOCUMENT_ID,
        "content_type": "application/pdf",
    }
    kwargs.update(overrides)
    return await service.store(b"invoice bytes", **kwargs)


# ── Storing ─────────────────────────────────────────────────────────────────


async def test_store_puts_the_bytes_at_the_contracted_key(service: StorageService):
    stored = await _store(service)

    assert stored.storage_key.endswith(f"/{DOCUMENT_ID}.pdf")
    assert f"/company/{COMPANY_ID}/exporter_upload/" in stored.storage_key
    assert stored.size_bytes == len(b"invoice bytes")


async def test_the_caller_supplies_the_document_id_so_row_and_key_agree(
    service: StorageService,
):
    """Phase 3 needs the id for its row and the key contains it; generating it in
    two places would let them disagree."""
    other = uuid.uuid4()
    stored = await _store(service, document_id=other)
    assert str(other) in stored.storage_key


async def test_the_extension_comes_from_the_content_type_not_a_file_name(
    service: StorageService,
):
    stored = await _store(service, content_type="image/png")
    assert stored.storage_key.endswith(".png")


@pytest.mark.parametrize(
    "content_type", ["application/x-msdownload", "", "application/octet-stream", "text/html"]
)
async def test_an_unaccepted_content_type_is_refused(
    service: StorageService, content_type: str
):
    """An allow-list, not a guess: the extension goes into the key, so a type with
    no known extension is refused rather than stored with a made-up one."""
    with pytest.raises(UnsupportedContentTypeError):
        await _store(service, content_type=content_type)


async def test_a_refused_content_type_writes_nothing(
    service: StorageService, tmp_path: Path
):
    with pytest.raises(UnsupportedContentTypeError):
        await _store(service, content_type="application/octet-stream")
    assert list(tmp_path.rglob("*.*")) == []


async def test_a_content_type_with_parameters_is_accepted(service: StorageService):
    """Browsers send `text/plain; charset=utf-8`; refusing that would refuse a
    perfectly ordinary upload."""
    stored = await _store(service, content_type="text/plain; charset=utf-8")
    assert stored.storage_key.endswith(".txt")


# ── The scan step ───────────────────────────────────────────────────────────


async def test_the_prototype_scanner_reports_itself_as_a_pass_through(
    service: StorageService,
):
    """Assumption A9: the placeholder is labelled in the data, not only on screen.
    A reader can always tell that nothing was actually scanned."""
    stored = await _store(service)

    assert stored.scan.scanner_name == PASS_THROUGH_SCANNER_NAME == "pass-through"
    assert stored.scan_status is DocumentScanStatus.AVAILABLE
    assert "no malware check" in (stored.scan.detail or "")
    assert service.scanner_name == "pass-through"


async def test_scanning_happens_on_the_key_that_was_written(tmp_path: Path):
    scanner = _VerdictScanner(DocumentScanStatus.AVAILABLE)
    service = StorageService(LocalDiskStorage(root=tmp_path), scanner)

    stored = await _store(service)
    assert scanner.calls == [stored.storage_key]


@pytest.mark.parametrize(
    "verdict",
    [DocumentScanStatus.QUARANTINED, DocumentScanStatus.SCAN_FAILED],
)
async def test_a_bad_verdict_is_carried_back_rather_than_raised(
    tmp_path: Path, verdict: DocumentScanStatus
):
    """The object exists and the row must record the verdict, so this is not an
    exception — Phase 3 stores the status. What it must never become is
    ``AVAILABLE``."""
    service = StorageService(LocalDiskStorage(root=tmp_path), _VerdictScanner(verdict))

    stored = await _store(service)
    assert stored.scan_status is verdict
    assert stored.scan_status.is_servable is False


# ── Serving ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    [
        DocumentScanStatus.PENDING_SCAN,
        DocumentScanStatus.QUARANTINED,
        DocumentScanStatus.SCAN_FAILED,
    ],
)
async def test_content_is_refused_for_anything_not_available(
    service: StorageService, status: DocumentScanStatus
):
    """By state, not by role: there is no role, and no flag, that opens one of
    these (contract §4)."""
    stored = await _store(service)

    for call in (service.open_link, service.read):
        with pytest.raises(DocumentNotServableError) as caught:
            await call(stored.storage_key, scan_status=status)
        assert caught.value.scan_status is status


async def test_an_available_document_can_be_linked_and_read(service: StorageService):
    stored = await _store(service)

    link = await service.open_link(
        stored.storage_key, scan_status=DocumentScanStatus.AVAILABLE
    )
    assert stored.storage_key in link.url
    assert (
        await service.read(stored.storage_key, scan_status=DocumentScanStatus.AVAILABLE)
        == b"invoice bytes"
    )


def test_only_available_is_servable():
    """One place to ask, so a new status cannot default to downloadable by being
    missed at a call site."""
    servable = [s for s in DocumentScanStatus if s.is_servable]
    assert servable == [DocumentScanStatus.AVAILABLE]


async def test_delete_removes_the_stored_object(service: StorageService):
    stored = await _store(service)
    await service.delete(stored.storage_key)

    with pytest.raises(FileNotFoundError):
        await service.read(stored.storage_key, scan_status=DocumentScanStatus.AVAILABLE)
