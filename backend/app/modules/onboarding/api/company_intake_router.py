"""RXIL company intake and bulk CSV import routes — **owner: Developer 2**
(L2-12, L2-13).

Both create companies, so both admit OPERATIONS, COMPLIANCE and ADMIN, as
company creation does; RXIL intake also records a qualification outcome, which
the same roles may do. The actor is always the signed-in user — neither an
RXIL package nor a CSV file can name one.

Mounted by ``router.py`` under the module's ``/onboarding`` prefix.
"""

from __future__ import annotations

import io
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.company_intake import (
    ImportReportResponse,
    IntakeResponse,
)
from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_CSV,
    CompanyImportService,
)
from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

router = APIRouter(tags=["Company intake"])

_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
_401 = {"description": "Unauthorized"}
_403 = {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}

#: The largest CSV accepted, in bytes (a 1,000-row file is well under 1 MB).
MAX_IMPORT_BYTES = 5 * 1024 * 1024


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
        "specification is published."
    ),
    responses={
        401: _401,
        403: _403,
        409: {"description": "Matches existing companies ambiguously, or already being handled"},
        422: {"description": "The package cannot be read, or breaks the company rules"},
    },
)
async def take_in_rxil_company(
    current_user: Annotated[User, Depends(_STAFF)],
    package: Annotated[dict[str, Any], Body()],
    db: AsyncSession = Depends(get_db),
) -> IntakeResponse:
    intake = parse_rxil_company_package(package)
    result = await PartnerIntakeService(db).ingest(intake, actor_id=str(current_user.id))
    return IntakeResponse.of(result)


@router.get(
    "/imports/companies/template",
    response_class=PlainTextResponse,
    summary="The CSV template for bulk company import",
    responses={
        200: {"content": {"text/csv": {}}, "description": "The template's header row"},
        401: _401,
        403: _403,
    },
)
async def get_company_import_template(
    current_user: Annotated[User, Depends(_STAFF)],
) -> PlainTextResponse:
    return PlainTextResponse(
        TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="company-import-template.csv"'},
    )


@router.post(
    "/imports/companies",
    response_model=ImportReportResponse,
    summary="Import companies from a CSV file",
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
        422: {"description": "Not a CSV in the template's shape, or too large"},
    },
)
async def import_companies(
    current_user: Annotated[User, Depends(_STAFF)],
    file: Annotated[UploadFile, File(description="A CSV file in the template's shape")],
    db: AsyncSession = Depends(get_db),
) -> ImportReportResponse:
    if file.size is not None and file.size > MAX_IMPORT_BYTES:
        raise ValidationError(f"the file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
    try:
        lines = io.TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
        report = await CompanyImportService(db).import_csv(lines, actor_id=str(current_user.id))
    except UnicodeDecodeError as exc:
        raise ValidationError("the file must be UTF-8 text") from exc
    return ImportReportResponse.of(report)


__all__ = ["router"]
