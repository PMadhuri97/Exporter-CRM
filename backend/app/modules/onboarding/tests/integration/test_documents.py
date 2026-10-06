"""Migration 0019, the document record, and the scan gate.

The database-level cases go straight through ``psycopg2`` so they prove the
*database* refuses the bad row and not just the service — migration register §2:
every new constraint gets a direct-SQL violation test. The rest go through the
service and the API as a person would.

The tests that matter most are the scan-gate ones: **a document that has not passed
the scan step is refused to every role**, and a link cannot be stretched, forged or
outlived. Storage goes to a ``tmp_path`` root, so nothing here writes to the
configured one.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.storage_service import StorageService
from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.storage import (
    DocumentScanStatus,
    ScanOutcome,
)
from app.modules.onboarding.exceptions import (
    DealNotFoundError,
    DealTerminalError,
    DocumentCategoryNotAllowedError,
    DocumentContentTypeNotSupportedError,
    DocumentNotAvailableError,
    DocumentNotFoundError,
    DocumentTypeNotAllowedError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.storage import LocalDiskStorage, sign_key
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_prospect
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolated_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point local-disk storage at ``tmp_path`` for every test in this file.

    The service-level tests inject their own storage, but the API tests go through
    the route's ``build_storage_service()``, which reads ``STORAGE_LOCAL_ROOT`` — so
    without this they wrote real files into the developer's
    ``backend/.local-storage``. ``local_storage_root()`` reads the variable on every
    call, so setting it here is enough.
    """
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))

BASE = "/api/v1/onboarding"
PDF = b"%PDF-1.4 sample invoice"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


class _VerdictScanner:
    """A scanner with a fixed verdict, for the statuses the pass-through one never
    produces. Satisfies ``ScannerPort`` structurally."""

    def __init__(self, status: DocumentScanStatus) -> None:
        self.name = "fake"
        self._status = status

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        return ScanOutcome(status=self._status, scanner_name=self.name)


def _service(db, tmp_path: Path, scanner=None) -> DocumentService:
    """A ``DocumentService`` writing to ``tmp_path``.

    The storage is injected rather than taken from the environment so these tests
    never touch the configured root — and so a verdict other than clean can be
    exercised without a real scanner.
    """
    storage = StorageService(
        LocalDiskStorage(root=tmp_path),
        scanner or _VerdictScanner(DocumentScanStatus.AVAILABLE),
    )
    return DocumentService(db, storage=storage)


async def _company() -> uuid.UUID:
    # A prospect, so the same company can also have a deal opened on it.
    return await make_prospect()


async def _deal(company_id: uuid.UUID) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference="Documents deal", actor_id="tester"
        )
    return view.id


async def _upload(tmp_path: Path, **kwargs):
    defaults = {
        "category": DocumentCategory.ENTITY_KYC,
        "document_type": "certificate_of_incorporation",
        "source": DocumentSource.EXPORTER_UPLOAD,
        "file_name": "incorporation.pdf",
        "content_type": "application/pdf",
        "actor_id": "tester",
    }
    scanner = kwargs.pop("scanner", None)
    async with db_services.AsyncSessionLocal() as db:
        return await _service(db, tmp_path, scanner).upload(PDF, **{**defaults, **kwargs})


# ── The database refuses what the contract forbids ───────────────────────────


def test_a_document_with_no_owner_is_refused_by_the_database():
    """``ck_crm_document_one_owner``, first half. Paperwork belonging to nobody
    could never be found again."""
    with _connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO onboarding.crm_document"
                " (category, document_type, source, file_name, content_type,"
                "  size_bytes, uploaded_at, scan_status, storage_key)"
                " VALUES ('OTHER', 'other', 'INTERNAL', 'x.pdf', 'application/pdf',"
                "  1, now(), 'PENDING_SCAN', %s)",
                (f"test/company/x/internal/{uuid.uuid4()}.pdf",),
            )


def test_a_document_with_two_owners_is_refused_by_the_database():
    """``ck_crm_document_one_owner``, second half — architecture §3.4: a document
    belongs **either** to a company or to a deal."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.deal (company_id, reference, stage)"
            " VALUES (%s, 'both owners', 'OPEN') RETURNING id",
            (str(company_id),),
        )
        deal_id = cursor.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO onboarding.crm_document"
                " (company_id, deal_id, category, document_type, source, file_name,"
                "  content_type, size_bytes, uploaded_at, scan_status, storage_key)"
                " VALUES (%s, %s, 'OTHER', 'other', 'INTERNAL', 'x.pdf',"
                "  'application/pdf', 1, now(), 'PENDING_SCAN', %s)",
                (str(company_id), str(deal_id), f"test/company/x/internal/{uuid.uuid4()}.pdf"),
            )


def test_two_documents_cannot_share_a_storage_key():
    """``uq_crm_document_storage_key``: two rows pointing at one object would make a
    delete ambiguous and a download unattributable (contract §5.2)."""
    key = f"test/company/shared/internal/{uuid.uuid4()}.pdf"
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        for _ in range(1):
            cursor.execute(
                "INSERT INTO onboarding.crm_document"
                " (company_id, category, document_type, source, file_name,"
                "  content_type, size_bytes, uploaded_at, scan_status, storage_key)"
                " VALUES (%s, 'OTHER', 'other', 'INTERNAL', 'x.pdf',"
                "  'application/pdf', 1, now(), 'AVAILABLE', %s)",
                (str(company_id), key),
            )
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(
                "INSERT INTO onboarding.crm_document"
                " (company_id, category, document_type, source, file_name,"
                "  content_type, size_bytes, uploaded_at, scan_status, storage_key)"
                " VALUES (%s, 'OTHER', 'other', 'INTERNAL', 'y.pdf',"
                "  'application/pdf', 1, now(), 'AVAILABLE', %s)",
                (str(company_id), key),
            )


def test_a_document_for_a_ghost_company_is_refused_by_the_database():
    """``fk_crm_document_company_id``."""
    with _connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO onboarding.crm_document"
                " (company_id, category, document_type, source, file_name,"
                "  content_type, size_bytes, uploaded_at, scan_status, storage_key)"
                " VALUES (%s, 'OTHER', 'other', 'INTERNAL', 'x.pdf',"
                "  'application/pdf', 1, now(), 'AVAILABLE', %s)",
                (str(uuid.uuid4()), f"test/company/ghost/internal/{uuid.uuid4()}.pdf"),
            )


def test_a_company_with_documents_cannot_be_deleted():
    """``ON DELETE RESTRICT``: a company's paperwork is part of the record, and
    seven-year AML retention means it must not vanish with the row."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.crm_document"
            " (company_id, category, document_type, source, file_name,"
            "  content_type, size_bytes, uploaded_at, scan_status, storage_key)"
            " VALUES (%s, 'OTHER', 'other', 'INTERNAL', 'x.pdf',"
            "  'application/pdf', 1, now(), 'AVAILABLE', %s)",
            (str(company_id), f"test/company/keep/internal/{uuid.uuid4()}.pdf"),
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "DELETE FROM onboarding.exporter_profile WHERE customer_id = %s",
                (str(company_id),),
            )


# ── Uploading ────────────────────────────────────────────────────────────────


async def test_a_company_document_is_stored_and_recorded(tmp_path: Path):
    company_id = await _company()
    view = await _upload(tmp_path, company_id=company_id)

    assert view.company_id == company_id
    assert view.deal_id is None
    assert view.category is DocumentCategory.ENTITY_KYC
    assert view.document_type == "certificate_of_incorporation"
    assert view.file_name == "incorporation.pdf"
    # Measured, never taken from a claim.
    assert view.size_bytes == len(PDF)
    # The object is really there, under the contract's key shape.
    stored = list(tmp_path.rglob("*.pdf"))
    assert len(stored) == 1
    assert f"/company/{company_id}/exporter_upload/" in stored[0].as_posix()


async def test_a_deal_document_is_stored_against_the_deal(tmp_path: Path):
    company_id = await _company()
    deal_id = await _deal(company_id)

    view = await _upload(
        tmp_path,
        deal_id=deal_id,
        category=DocumentCategory.SHIPPING,
        document_type="bill_of_lading",
    )
    assert view.deal_id == deal_id
    assert view.company_id is None
    assert f"/deal/{deal_id}/" in list(tmp_path.rglob("*.pdf"))[0].as_posix()


async def test_the_file_name_never_reaches_the_storage_key(tmp_path: Path):
    """§9.3's "Watch out for": a user-supplied name inside a key is a traversal
    surface and a rename hazard. It is a column instead."""
    company_id = await _company()
    view = await _upload(
        tmp_path, company_id=company_id, file_name="../../etc/passwd invoice.pdf"
    )

    assert view.file_name == "../../etc/passwd invoice.pdf"
    key = list(tmp_path.rglob("*.pdf"))[0].as_posix()
    assert "passwd" not in key
    assert str(view.id) in key


async def test_a_category_filed_against_the_wrong_owner_is_refused(tmp_path: Path):
    """Architecture §3.4 gives each category an owner; `SHIPPING` on a company would
    put the document where nobody looks for it."""
    company_id = await _company()
    with pytest.raises(DocumentCategoryNotAllowedError):
        await _upload(
            tmp_path,
            company_id=company_id,
            category=DocumentCategory.SHIPPING,
            document_type="bill_of_lading",
        )


async def test_a_company_category_is_refused_on_a_deal(tmp_path: Path):
    company_id = await _company()
    deal_id = await _deal(company_id)
    with pytest.raises(DocumentCategoryNotAllowedError):
        await _upload(
            tmp_path,
            deal_id=deal_id,
            category=DocumentCategory.ENTITY_KYC,
            document_type="certificate_of_incorporation",
        )


@pytest.mark.parametrize(
    "category", [DocumentCategory.BANKING, DocumentCategory.INSURANCE, DocumentCategory.OTHER]
)
async def test_a_both_category_is_accepted_on_either_owner(
    tmp_path: Path, category: DocumentCategory
):
    company_id = await _company()
    deal_id = await _deal(company_id)
    document_type = {
        DocumentCategory.BANKING: "bank_statement",
        DocumentCategory.INSURANCE: "annual_policy",
        DocumentCategory.OTHER: "other",
    }[category]

    on_company = await _upload(
        tmp_path, company_id=company_id, category=category, document_type=document_type
    )
    on_deal = await _upload(
        tmp_path, deal_id=deal_id, category=category, document_type=document_type
    )
    assert on_company.category is category and on_deal.category is category


async def test_an_unconfigured_type_is_refused(tmp_path: Path):
    """Types are settings; an unknown one is a 422 naming the category, not a new
    enum member."""
    company_id = await _company()
    with pytest.raises(DocumentTypeNotAllowedError):
        await _upload(tmp_path, company_id=company_id, document_type="not_configured")


async def test_a_type_from_another_category_is_refused(tmp_path: Path):
    company_id = await _company()
    with pytest.raises(DocumentTypeNotAllowedError):
        await _upload(tmp_path, company_id=company_id, document_type="bill_of_lading")


async def test_an_unaccepted_content_type_is_refused_and_stores_nothing(tmp_path: Path):
    company_id = await _company()
    with pytest.raises(DocumentContentTypeNotSupportedError):
        await _upload(
            tmp_path, company_id=company_id, content_type="application/x-msdownload"
        )
    assert list(tmp_path.rglob("*.*")) == []


async def test_an_upload_for_a_missing_owner_is_refused_and_stores_nothing(tmp_path: Path):
    with pytest.raises(ExporterProfileNotFoundError):
        await _upload(tmp_path, company_id=uuid.uuid4())
    with pytest.raises(DealNotFoundError):
        await _upload(
            tmp_path,
            deal_id=uuid.uuid4(),
            category=DocumentCategory.SHIPPING,
            document_type="bill_of_lading",
        )
    # Validation happens before a byte is written, so no orphaned objects.
    assert list(tmp_path.rglob("*.*")) == []


async def test_neither_or_both_owners_is_refused(tmp_path: Path):
    company_id = await _company()
    deal_id = await _deal(company_id)

    with pytest.raises(DocumentCategoryNotAllowedError):
        await _upload(tmp_path)  # neither
    with pytest.raises(DocumentCategoryNotAllowedError):
        await _upload(tmp_path, company_id=company_id, deal_id=deal_id)  # both


# ── The scan gate ────────────────────────────────────────────────────────────


async def test_the_prototype_records_the_pass_through_scanner_by_name(tmp_path: Path):
    """The placeholder is labelled in the data, so a reader can tell
    nothing was actually scanned. This uses the real service wiring, not a fake."""
    async with db_services.AsyncSessionLocal() as db:
        service = DocumentService(db)
        assert service.scanner_name == "pass-through"


@pytest.mark.parametrize(
    "verdict",
    [
        DocumentScanStatus.PENDING_SCAN,
        DocumentScanStatus.QUARANTINED,
        DocumentScanStatus.SCAN_FAILED,
    ],
)
async def test_content_is_refused_for_anything_not_available(
    tmp_path: Path, verdict: DocumentScanStatus
):
    """By state, for every role: there is no role and no flag that opens one of
    these (architecture §3.4, contract §4)."""
    company_id = await _company()
    view = await _upload(tmp_path, company_id=company_id, scanner=_VerdictScanner(verdict))
    assert view.scan_status is verdict
    assert view.is_downloadable is False

    async with db_services.AsyncSessionLocal() as db:
        service = _service(db, tmp_path)
        with pytest.raises(DocumentNotAvailableError):
            await service.open_download_link(view.id)


async def test_an_available_document_yields_a_link_and_its_content(tmp_path: Path):
    company_id = await _company()
    view = await _upload(tmp_path, company_id=company_id)
    assert view.scan_status is DocumentScanStatus.AVAILABLE

    async with db_services.AsyncSessionLocal() as db:
        link = await _service(db, tmp_path).open_download_link(view.id)
    assert str(view.id) in link.url

    async with db_services.AsyncSessionLocal() as db:
        row = await db.scalar(select(CrmDocument).where(CrmDocument.id == view.id))
        document, content = await _service(db, tmp_path).read_content(row.storage_key)
    assert content == PDF
    assert document.id == view.id


async def test_reading_a_key_with_no_row_is_a_404(tmp_path: Path):
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DocumentNotFoundError):
            await _service(db, tmp_path).read_content(
                f"test/company/x/internal/{uuid.uuid4()}.pdf"
            )


# ── The API ──────────────────────────────────────────────────────────────────


async def test_the_catalogue_offers_only_the_categories_valid_here(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)

    company = await client.get(
        f"{BASE}/documents/categories?owner=COMPANY", headers=auth_header(token)
    )
    assert company.status_code == 200, company.text
    company_categories = {c["category"] for c in company.json()["categories"]}
    assert "ENTITY_KYC" in company_categories
    assert "SHIPPING" not in company_categories
    # The screen has to be able to say the scanner is a placeholder.
    assert company.json()["scanner_name"] == "pass-through"

    deal = await client.get(
        f"{BASE}/documents/categories?owner=DEAL", headers=auth_header(token)
    )
    deal_categories = {c["category"] for c in deal.json()["categories"]}
    assert "SHIPPING" in deal_categories
    assert "ENTITY_KYC" not in deal_categories
    # Both-owner categories appear on each side.
    assert {"BANKING", "INSURANCE", "OTHER"} <= company_categories & deal_categories


async def test_the_api_uploads_lists_and_downloads(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={
            "category": "ENTITY_KYC",
            "document_type": "certificate_of_incorporation",
            "source": "EXPORTER_UPLOAD",
        },
        files={"file": ("incorporation.pdf", PDF, "application/pdf")},
        headers=auth_header(token),
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    assert uploaded.json()["scanner_name"] == "pass-through"
    assert uploaded.json()["is_downloadable"] is True

    listing = await client.get(
        f"{BASE}/exporters/{company_id}/documents", headers=auth_header(token)
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    # No response ever carries the storage key.
    assert "storage_key" not in listing.json()["documents"][0]

    link = await client.post(
        f"{BASE}/documents/{document_id}/download-link", headers=auth_header(token)
    )
    assert link.status_code == 200, link.text

    # The link is served by this application, and the path resolves — which is what
    # proves `/documents/content` is declared before `/documents/{document_id}`.
    url = link.json()["url"].removeprefix("/api/v1")
    content = await client.get(f"/api/v1{url}", headers=auth_header(token))
    assert content.status_code == 200, content.text
    assert content.content == PDF
    assert content.headers["content-disposition"].startswith("attachment")
    assert content.headers["x-content-type-options"] == "nosniff"


async def test_a_tampered_or_expired_link_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    company_id = await _company()
    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    document_id = uploaded.json()["id"]
    link = await client.post(
        f"{BASE}/documents/{document_id}/download-link", headers=auth_header(token)
    )
    url = link.json()["url"]
    key = url.split("key=")[1].split("&")[0]

    # A forged signature.
    forged = await client.get(
        f"{BASE}/documents/content?key={key}&expires=99999999999&signature=deadbeef",
        headers=auth_header(token),
    )
    assert forged.status_code == 403, forged.text
    assert forged.json()["error_code"] == "DOCUMENT_LINK_INVALID"

    # An authentic signature over an expiry that has passed: signed correctly, and
    # still refused, which is what stops a link outliving its window.
    past = int(time.time()) - 1
    expired = await client.get(
        f"{BASE}/documents/content?key={key}&expires={past}&signature={sign_key(key, past)}",
        headers=auth_header(token),
    )
    assert expired.status_code == 403, expired.text


async def test_content_still_needs_a_role(client: AsyncClient):
    """A signed link is not a way around authentication."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    api_user = await token_with_role(client, UserRole.API_USER)
    company_id = await _company()
    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    link = await client.post(
        f"{BASE}/documents/{uploaded.json()['id']}/download-link",
        headers=auth_header(token),
    )
    url = link.json()["url"].removeprefix("/api/v1")

    refused = await client.get(f"/api/v1{url}", headers=auth_header(api_user))
    assert refused.status_code == 403, refused.text


async def test_an_empty_file_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    resp = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_developer_may_read_documents_but_not_upload(client: AsyncClient):
    staff = await token_with_role(client, UserRole.OPERATIONS)
    developer = await token_with_role(client, UserRole.DEVELOPER)
    company_id = await _company()
    await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(staff),
    )

    listing = await client.get(
        f"{BASE}/exporters/{company_id}/documents", headers=auth_header(developer)
    )
    assert listing.status_code == 200, listing.text

    refused = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(developer),
    )
    assert refused.status_code == 403, refused.text


# ── The review's findings ────────────────────────────────────────────────────


async def test_a_unicode_file_name_survives_the_download(client: AsyncClient):
    """HTTP headers are latin-1, so a Hindi or rupee file name used to raise
    ``UnicodeEncodeError`` inside ``Content-Disposition`` and return a 500 — which
    Indian exporters would hit constantly. RFC 6266's ``filename*`` carries the
    real name; the plain ``filename`` is an ASCII fallback."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("\u092a\u094d\u0930\u092e\u093e\u0923-\u20b9.txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    assert uploaded.status_code == 201, uploaded.text

    link = await client.post(
        f"{BASE}/documents/{uploaded.json()['id']}/download-link",
        headers=auth_header(token),
    )
    url = link.json()["url"].removeprefix("/api/v1")
    content = await client.get(f"/api/v1{url}", headers=auth_header(token))

    assert content.status_code == 200, content.text
    assert content.content == b"hello"
    disposition = content.headers["content-disposition"]
    # Both parameters: the percent-encoded real name, and an ASCII fallback that
    # keeps the extension so an old client still saves something openable.
    assert "filename*=UTF-8''" in disposition
    assert "%E0%A4%AA" in disposition  # the first Devanagari character
    assert 'filename="document.txt"' in disposition


async def test_a_file_name_longer_than_the_column_is_capped_not_a_500(
    client: AsyncClient,
):
    """``crm_document.file_name`` is varchar(500). A longer name used to fail the
    insert *after* the bytes were written: a 500, and a file on disk with no row
    pointing at it."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("n" * 600 + ".txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    assert uploaded.status_code == 201, uploaded.text
    stored_name = uploaded.json()["file_name"]
    assert len(stored_name) == 500
    assert stored_name.endswith(".txt")  # the extension survives the cap

    listing = await client.get(
        f"{BASE}/exporters/{company_id}/documents", headers=auth_header(token)
    )
    assert listing.json()["total"] == 1


async def test_a_document_type_longer_than_the_column_is_a_422(client: AsyncClient):
    """Validated on the form parameter, so FastAPI answers 422. Building the model
    inside the handler raised a Pydantic error FastAPI never saw — a raw 500."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    resp = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "x" * 200},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_content_is_refused_without_a_token(client: AsyncClient):
    """A signed link is not a way around authentication — which is why the browser
    cannot simply open it, and the frontend fetches it with the access token."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()
    uploaded = await client.post(
        f"{BASE}/exporters/{company_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_header(token),
    )
    link = await client.post(
        f"{BASE}/documents/{uploaded.json()['id']}/download-link",
        headers=auth_header(token),
    )
    url = link.json()["url"].removeprefix("/api/v1")

    anonymous = await client.get(f"/api/v1{url}")
    assert anonymous.status_code == 401, anonymous.text


async def test_no_orphan_file_is_left_when_the_row_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The bytes are stored before the row exists, so a failed insert would leave a
    file nothing points at. The upload path removes it and re-raises."""
    company_id = await _company()
    root = tmp_path / "orphan-check"

    async with db_services.AsyncSessionLocal() as db:
        service = _service(db, root)

        async def _explode():
            raise RuntimeError("insert failed")

        monkeypatch.setattr(db, "commit", _explode)
        with pytest.raises(RuntimeError):
            await service.upload(
                PDF,
                company_id=company_id,
                category=DocumentCategory.OTHER,
                document_type="other",
                source=DocumentSource.INTERNAL,
                file_name="doomed.pdf",
                content_type="application/pdf",
                actor_id="tester",
            )

    assert list(root.rglob("*.pdf")) == []


async def test_a_terminal_deal_takes_no_more_paperwork(tmp_path: Path):
    """A handed-over deal's documents are what the lending team was given, and a
    withdrawn deal's are history. Same rule as editing a terminal deal's buyer."""
    company_id = await _company()
    deal_id = await _deal(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="fell through", actor_id="tester"
        )

    with pytest.raises(DealTerminalError):
        await _upload(
            tmp_path,
            deal_id=deal_id,
            category=DocumentCategory.SHIPPING,
            document_type="bill_of_lading",
        )
