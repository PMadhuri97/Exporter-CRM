"""Document and storage routes — **owner: Developer 3B** (L3-07 … L3-10).

Empty until now; see `follow_up_router.py`'s docstring for why it was mounted in
the seam commit rather than when it was filled.

No prefix, because documents hang off deals as well as companies: a single router
prefix would fit neither. The upload and list paths name their owner
(`/exporters/{company_id}/documents`, `/deals/{deal_id}/documents`), and everything
about one document is under `/documents/{document_id}`.

Roles come from architecture §3.7: OPERATIONS, COMPLIANCE and ADMIN upload; those
three plus DEVELOPER read. **The download path is not only a role check** — a
document that has not passed the scan step is refused to everyone, by state, and a
link that has expired or been tampered with is refused before the row is read.
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Annotated
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.document import (
    DocumentCategoryListResponse,
    DocumentCategoryResponse,
    DocumentListResponse,
    DocumentResponse,
    DownloadLinkResponse,
)
from app.modules.onboarding.application.document_service import (
    DocumentService,
    build_storage_service,
)
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)
from app.modules.onboarding.exceptions import DocumentLinkInvalidError
from app.modules.onboarding.infrastructure.storage import verify_signed_key
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["Exporter CRM"])

_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)

#: A ceiling on one upload, matched to what the CSV import already refuses, so the
#: two limits do not disagree. A document larger than this is refused before the
#: body is read into memory where possible, and always before it is stored.
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024

_401 = {"description": "Unauthorized"}
_403_WRITE = {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}
_403_READ = {"description": "CRM read role required"}


def _asciified(part: str) -> str:
    """One part of a file name, reduced to ASCII and stripped of header-hostile
    characters. Quotes and backslashes are dropped rather than escaped: they have no
    place in a saved file name, and escaping them correctly across clients is not
    worth the risk."""
    return (
        unicodedata.normalize("NFKD", part)
        .encode("ascii", "ignore")
        .decode("ascii")
        .replace('"', "")
        .replace("\\", "")
        .strip()
    )


def content_disposition(file_name: str) -> str:
    """An `attachment` disposition that survives a non-Latin-1 file name.

    HTTP headers are latin-1, so `filename="प्रमाणपत्र.pdf"` raises
    `UnicodeEncodeError` inside the server and becomes a 500 — which Indian
    exporters would hit constantly. RFC 6266 answers this with two parameters: a
    plain `filename` an old client can read, and `filename*` carrying the real
    name percent-encoded as UTF-8. Modern browsers prefer `filename*`.

    The ASCII fallback keeps the extension where there is one, so a client that
    only understands `filename` still saves something openable. Quotes and
    backslashes are dropped rather than escaped: they have no place in a saved
    file name and escaping them correctly across clients is not worth the risk.
    """
    # Split first: the fallback has to be judged on the stem, not the whole name.
    # "प्रमाण-₹.txt" reduces to "-.txt", whose extension letters would pass any
    # check applied to the string as a whole, leaving a useless name.
    stem, dot, extension = file_name.rpartition(".")
    if not dot:
        stem, extension = file_name, ""

    ascii_stem = _asciified(stem)
    ascii_extension = _asciified(extension)
    if not any(character.isalnum() for character in ascii_stem):
        ascii_stem = "document"
    ascii_name = f"{ascii_stem}.{ascii_extension}" if ascii_extension else ascii_stem

    quoted = quote(file_name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


async def _read_upload(file: UploadFile) -> bytes:
    if file.size is not None and file.size > MAX_DOCUMENT_BYTES:
        raise ValidationError(
            f"the file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB"
        )
    content = await file.read()
    if len(content) > MAX_DOCUMENT_BYTES:
        # `size` is advisory — a client may omit or understate it, so the real
        # length is checked after reading, before anything is stored.
        raise ValidationError(
            f"the file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB"
        )
    if not content:
        raise ValidationError("the file is empty")
    return content


#: The form fields that accompany an uploaded file. Declared as annotated
#: parameters rather than built into a model inside the handler: a model
#: constructed in the body raises a Pydantic error that FastAPI never sees, so an
#: over-long `document_type` came back as a 500 instead of a 422. These
#: constraints run before the handler, and match `crm_document.document_type`'s
#: `varchar(100)`.
_CategoryField = Annotated[DocumentCategory, Form()]
_DocumentTypeField = Annotated[str, Form(min_length=1, max_length=100)]
_SourceField = Annotated[DocumentSource, Form()]


# ── The filing catalogue ─────────────────────────────────────────────────────


@router.get(
    "/documents/categories",
    response_model=DocumentCategoryListResponse,
    summary="Which categories may be filed here, and the types each accepts",
    description=(
        "Architecture §3.4: the ten categories are fixed and each belongs to a "
        "company, a deal, or both, so a screen asks which are valid where the user "
        "is standing rather than keeping a copy. The **types** inside each category "
        "are settings — adding one is a GitOps change, not a release.\n\n"
        "`scanner_name` is the scanner that will judge an upload. It is "
        "`pass-through` in the prototype: a labelled placeholder that checks "
        "nothing, and a screen must say so (assumption A9)."
    ),
    responses={401: _401, 403: _403_READ},
)
async def list_document_categories(
    current_user: Annotated[User, Depends(_READER)],
    owner: DocumentOwnerKind = Query(
        default=DocumentOwnerKind.COMPANY,
        description="Whose page the user is on — COMPANY or DEAL.",
    ),
) -> DocumentCategoryListResponse:
    if owner is DocumentOwnerKind.BOTH:
        # `BOTH` describes a category, not a place a user can stand.
        raise ValidationError("owner must be COMPANY or DEAL")
    return DocumentCategoryListResponse(
        categories=[
            DocumentCategoryResponse.from_view(view)
            for view in DocumentService.categories_for(owner)
        ],
        scanner_name=build_storage_service().scanner_name,
    )


# ── Content, by signed link ──────────────────────────────────────────────────
#
# Declared **before** `/documents/{document_id}`: FastAPI matches in declaration
# order, so with the placeholder first, a GET of `/documents/content` would be read
# as a document id and refused as an invalid UUID. The same trap
# `/exporters/follow-ups` has, and `test_l3b_document_api.py` pins it.

@router.get(
    "/documents/content",
    response_class=Response,
    summary="Fetch a document's content with a signed link",
    description=(
        "The link `POST /documents/{id}/download-link` returns. The signature "
        "covers the key **and** the expiry, so neither can be changed without "
        "invalidating it, and an expired link is refused.\n\n"
        "Still role-gated: a signed link is not a way around authentication. The "
        "scan status is re-checked here too, so a link minted while a document was "
        "`AVAILABLE` stops working if a later verdict quarantines it."
    ),
    responses={
        401: _401,
        403: {"description": "CRM read role required, or the link is invalid or expired"},
        404: {"description": "No document for that key"},
        409: {"description": "The document has not passed the scan step"},
    },
)
async def get_document_content(
    current_user: Annotated[User, Depends(_READER)],
    key: str = Query(description="The relative storage key from the signed link"),
    expires: int = Query(description="Expiry, as a Unix timestamp, from the link"),
    signature: str = Query(description="The link's signature"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Verified before the database is touched: an unsigned or expired request
    # should not even cause a lookup.
    if not verify_signed_key(key, expires, signature):
        raise DocumentLinkInvalidError
    document, content = await DocumentService(db).read_content(key)
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            # `attachment` so a document is never rendered inline in the browser:
            # an HTML or SVG file served inline from this origin would run as this
            # application. The file name comes from the row, not the key.
            "Content-Disposition": content_disposition(document.file_name),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── Company documents ────────────────────────────────────────────────────────


@router.post(
    "/exporters/{company_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="Upload a document against a company",
    description=(
        "The file is stored, then scanned, then recorded — in that order, so a "
        "refused upload leaves neither a row nor an object.\n\n"
        "**Every upload lands `PENDING_SCAN` and cannot be opened** until a clean "
        "result arrives (architecture §3.4). In the prototype the scanner is a "
        "labelled pass-through, so a clean result is immediate and means nothing "
        "was checked.\n\n"
        "The category must be one that belongs on a company, and the type one the "
        "settings configure for that category."
    ),
    responses={
        401: _401,
        403: _403_WRITE,
        404: {"description": "Company not found"},
        422: {
            "description": (
                "Category not filed against a company, unknown document type, "
                "unaccepted content type, or an empty or oversized file"
            )
        },
    },
)
async def upload_company_document(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    file: Annotated[UploadFile, File(description="The document")],
    category: _CategoryField,
    document_type: _DocumentTypeField,
    source: _SourceField = DocumentSource.EXPORTER_UPLOAD,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    content = await _read_upload(file)
    view = await DocumentService(db).upload(
        content,
        company_id=company_id,
        category=category,
        document_type=document_type,
        source=source,
        file_name=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        actor_id=str(current_user.id),
    )
    return DocumentResponse.from_view(view)


@router.get(
    "/exporters/{company_id}/documents",
    response_model=DocumentListResponse,
    summary="List a company's documents",
    description=(
        "Newest upload first. `category` may be repeated to filter. Documents that "
        "have not passed the scan step are listed — hiding them would leave an "
        "operator wondering where a file went — but `is_downloadable` is false and "
        "their content is refused."
    ),
    responses={401: _401, 403: _403_READ},
)
async def list_company_documents(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    category: Annotated[list[DocumentCategory] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    views, total = await DocumentService(db).list_for_company(
        company_id,
        categories=tuple(category) if category else None,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        documents=[DocumentResponse.from_view(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Deal documents ───────────────────────────────────────────────────────────


@router.post(
    "/deals/{deal_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="Upload a document against a deal",
    description=(
        "As for a company, except the category must be one that belongs on a deal "
        "(architecture §3.4). These are the documents a handover's snapshot will "
        "list (Phase 4)."
    ),
    responses={
        401: _401,
        403: _403_WRITE,
        404: {"description": "Deal not found"},
        422: {
            "description": (
                "Category not filed against a deal, unknown document type, "
                "unaccepted content type, or an empty or oversized file"
            )
        },
    },
)
async def upload_deal_document(
    deal_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    file: Annotated[UploadFile, File(description="The document")],
    category: _CategoryField,
    document_type: _DocumentTypeField,
    source: _SourceField = DocumentSource.EXPORTER_UPLOAD,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    content = await _read_upload(file)
    view = await DocumentService(db).upload(
        content,
        deal_id=deal_id,
        category=category,
        document_type=document_type,
        source=source,
        file_name=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        actor_id=str(current_user.id),
    )
    return DocumentResponse.from_view(view)


@router.get(
    "/deals/{deal_id}/documents",
    response_model=DocumentListResponse,
    summary="List a deal's documents",
    responses={401: _401, 403: _403_READ},
)
async def list_deal_documents(
    deal_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    category: Annotated[list[DocumentCategory] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    views, total = await DocumentService(db).list_for_deal(
        deal_id,
        categories=tuple(category) if category else None,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        documents=[DocumentResponse.from_view(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── One document, and its content ────────────────────────────────────────────


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get one document's details",
    responses={401: _401, 403: _403_READ, 404: {"description": "Document not found"}},
)
async def get_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    return DocumentResponse.from_view(await DocumentService(db).get_document(document_id))


@router.post(
    "/documents/{document_id}/download-link",
    response_model=DownloadLinkResponse,
    summary="Mint a short-lived link to a document's content",
    description=(
        "`POST`, not `GET`: this mints a credential rather than reading a "
        "resource, and it should not be something a browser prefetches or a proxy "
        "caches.\n\n"
        "Refused for a document that is not `AVAILABLE` — to **every** role. An "
        "unscanned, quarantined or failed-scan file is a state, not a permission "
        "(architecture §3.4)."
    ),
    responses={
        401: _401,
        403: _403_READ,
        404: {"description": "Document not found"},
        409: {"description": "The document has not passed the scan step"},
    },
)
async def create_download_link(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> DownloadLinkResponse:
    link = await DocumentService(db).open_download_link(document_id)
    logger.info(
        "document.link.minted",
        document_id=str(document_id),
        actor_id=str(current_user.id),
    )
    return DownloadLinkResponse.from_view(link)


__all__ = ["router"]
