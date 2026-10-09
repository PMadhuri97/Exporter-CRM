"""RXIL company intake and bulk company import routes (CSV or Excel).

Bulk import creates companies, so it needs ``exporters:create``, as company
creation does (OPERATIONS and COMPLIANCE; the administrator creates nothing).

**RXIL intake needs ``exporters:partner_intake``** (COMPLIANCE by default). It records a qualification outcome *as RXIL's*:
``source = RXIL``, RXIL's own ``decided_by_kind`` and confidence, no deciding
user. The manual qualification routes refuse every one of those fields on
purpose (``schemas/qualification.py``), because a person must not be able to
record a decision as someone else's. Until RXIL delivers through its own
authenticated integration, a package is pasted in by hand, so the route is
limited to the people trusted to vouch that a package really came from RXIL.
``API_USER`` is deliberately not admitted: public sign-up grants it, and it
reaches nothing in the CRM.

The actor is always the signed-in user — neither an RXIL package nor a CSV
file can name one.

Mounted by ``router.py`` under the module's ``/onboarding`` prefix.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.company_intake import (
    ImportPreviewResponse,
    ImportReportResponse,
    IntakeResponse,
)
from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_CSV,
    CompanyImportService,
    preview_file,
)
from app.modules.onboarding.application.company_import_template import (
    TEMPLATE_XLSX_NAME,
    XLSX_MEDIA_TYPE,
    build_template_xlsx,
)
from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.platform.authentication.models import User
from app.platform.authorization.services import require_permission
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

router = APIRouter(tags=["Company intake"])

_COMPANY_CREATE = require_permission("exporters", "create")
_PARTNER_INTAKE = require_permission("exporters", "partner_intake")

_401 = {"description": "Unauthorized"}
_403 = {"description": "exporters:create permission required"}
_403_ADMIN = {"description": "exporters:partner_intake permission required"}

#: The largest file accepted, in bytes (a 1,000-row file is well under 1 MB).
MAX_IMPORT_BYTES = 5 * 1024 * 1024
_FILE_DESCRIPTION = "A CSV (UTF-8) or Excel (.xlsx) file in the template's shape"


async def _read_upload(file: UploadFile) -> bytes:
    """The uploaded file's bytes, refused when larger than ``MAX_IMPORT_BYTES``."""
    too_large = ValidationError(
        f"The file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB"
    )
    if file.size is not None and file.size > MAX_IMPORT_BYTES:
        raise too_large
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise too_large
    return content


@router.post(
    "/rxil/company-intake",
    response_model=IntakeResponse,
    status_code=201,
    summary="Take in an exporter RXIL has qualified (provisional format)",
    description=(
        "Creates or matches the company by the CRM's own identity rules and records "
        "RXIL's qualification exactly as supplied (source RXIL, never recomputed), "
        "which makes the company a PROSPECT. A company RXIL delivers that resembles "
        "existing companies without a PAN to settle it is refused (409) for a person "
        "to decide, never merged. A repeated delivery with the same package_id "
        "changes nothing. The package format is provisional until RXIL's "
        "specification is published. Needs exporters:partner_intake: the outcome is "
        "recorded as RXIL's "
        "decision, which the manual qualification routes never allow a person to do."
    ),
    responses={
        401: _401,
        403: _403_ADMIN,
        409: {"description": "Matches existing companies ambiguously, or already being handled"},
        422: {"description": "The package cannot be read, or breaks the company rules"},
    },
)
async def take_in_rxil_company(
    current_user: Annotated[User, Depends(_PARTNER_INTAKE)],
    package: Annotated[dict[str, Any], Body()],
    db: AsyncSession = Depends(get_db),
) -> IntakeResponse:
    intake = parse_rxil_company_package(package)
    result = await PartnerIntakeService(db).ingest(intake, actor_id=str(current_user.id))
    return IntakeResponse.of(result)


@router.get(
    "/imports/companies/template",
    response_class=Response,
    summary="The template for bulk company import, as CSV or Excel",
    description=(
        "`format=csv` (the default) is the template's header row. `format=xlsx` is a "
        "workbook with an Instructions sheet (every column: whether a value is needed, "
        "what to enter, an example and the allowed values) and a Companies sheet with "
        "dropdowns for country and source."
    ),
    responses={
        200: {
            "content": {"text/csv": {}, XLSX_MEDIA_TYPE: {}},
            "description": "The template file",
        },
        401: _401,
        403: _403,
    },
)
async def get_company_import_template(
    current_user: Annotated[User, Depends(_COMPANY_CREATE)],
    format: Annotated[Literal["csv", "xlsx"], Query()] = "csv",
) -> Response:
    if format == "xlsx":
        return Response(
            build_template_xlsx(),
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_XLSX_NAME}"'},
        )
    return PlainTextResponse(
        TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="company-import-template.csv"'},
    )


@router.post(
    "/imports/companies/preview",
    response_model=ImportPreviewResponse,
    summary="Read an import file without importing it",
    description=(
        "Reads the file exactly as the import would — CSV or Excel, the same header "
        "rules — and returns its columns, its first rows, its row count and what is "
        "wrong with its header. Nothing is checked row by row and nothing is saved."
    ),
    responses={
        401: _401,
        403: _403,
        422: {"description": "The file cannot be read at all, or is too large"},
    },
)
async def preview_company_import(
    current_user: Annotated[User, Depends(_COMPANY_CREATE)],
    file: Annotated[UploadFile, File(description=_FILE_DESCRIPTION)],
) -> ImportPreviewResponse:
    content = await _read_upload(file)
    return ImportPreviewResponse.of(preview_file(file.filename, content))


@router.post(
    "/imports/companies",
    response_model=ImportReportResponse,
    summary="Import companies from a CSV or Excel file",
    description=(
        "Every row is checked and matched by the same rules as creating a company by "
        "hand, and reported as accepted (created as a LEAD, or matched to the company "
        "its PAN belongs to), rejected, or possible_duplicate — each with codes and "
        "messages. Each created row is saved on its own: a row that fails cannot undo "
        "or damage another."
    ),
    responses={
        401: _401,
        403: _403,
        422: {"description": "Not a CSV or Excel file in the template's shape, or too large"},
    },
)
async def import_companies(
    current_user: Annotated[User, Depends(_COMPANY_CREATE)],
    file: Annotated[UploadFile, File(description=_FILE_DESCRIPTION)],
    db: AsyncSession = Depends(get_db),
) -> ImportReportResponse:
    content = await _read_upload(file)
    # The service reads and checks the whole file — encoding included — before
    # it saves any row, and refuses a bad file with a 422.
    report = await CompanyImportService(db).import_file(
        file.filename, content, actor_id=str(current_user.id)
    )
    return ImportReportResponse.of(report)


__all__ = ["router"]
