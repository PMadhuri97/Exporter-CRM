"""``POST /companies/match`` — "do we already have this company?" — **owner:
Developer 3** (allocation task 3.10, plan P4-3).

Its own file, and its own ``/companies`` prefix, for a reason worth stating: this
route is not about one company. Every other route in ``exporter_router.py`` names
a company in its path and answers questions about it; this one is handed a name and
some identifiers and asks the CRM which company — if any — they belong to. Hanging
it off ``/exporters/{id}`` would need an id the caller does not have yet.

Decision BQ-2, as this route implements it
-----------------------------------------
A relationship manager who may not see raw identifiers **may** submit a full PAN,
GSTIN or registration number here, and the server will name the company that holds
it. That is the whole point: the alternative is an RM creating a duplicate of a
company we already have because they could not check.

Three things keep that from becoming a way to read identifiers:

#. **The response never carries an identifier.** Not even a masked one — a
   candidate is a company id, a name and a country. What the caller already sent,
   they already know; what they did not send, they do not learn.
#. **Only exact values are accepted.** A partial or prefix search stays refused
   (it is not offered here at all, and ``GET /exporters`` refuses it with
   ``IdentifierSearchNotPermittedError``), so this cannot be walked to enumerate
   identifiers.
#. **Every identifier lookup is audited** — who, when, which kind, which company
   it named — by ``CompanyDirectoryService``, which is the layer that knows a
   lookup actually happened.

``open-items.md`` §1 records the lead's still-open question about naming holders to
masked roles at all. This route follows the precedent already set by the duplicate
PAN refusal and the GSTIN warnings: name the company, never the identifier.

Why POST for a read
-------------------
It writes nothing about the company, so GET would be the usual choice. It is a POST
because the request body carries full tax identifiers, and a GET would put them in
the query string — which lands in access logs, browser history and any proxy in
between, for exactly the values the rest of this CRM masks.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.company_directory import (
    CompanyMatchCandidate,
    CompanyMatchRequest,
    CompanyMatchResponse,
)
from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/companies", tags=["Exporter CRM"])

#: Who may ask. Recording a deal's buyer is a relationship manager's job, so
#: OPERATIONS is included — that is the case BQ-2 was decided for. DEVELOPER is
#: excluded: it is read-only internal technical staff, it may never reveal an
#: identifier (``can_reveal_identifiers``), and it has no reason to be resolving a
#: buyer. API_USER is excluded for the same reason as everywhere else in the CRM.
_MATCHER = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


@router.post(
    "/match",
    response_model=CompanyMatchResponse,
    summary="Find the company a name and identifiers belong to",
    description=(
        "Answers MATCHED, POSSIBLE_DUPLICATE, CONFLICT or NEW. A full PAN, GSTIN or "
        "(country, registration_number) names the company that holds it — including "
        "for a role that sees identifiers masked (decision BQ-2) — and every such "
        "lookup is audited. Partial or prefix identifier search is not offered. "
        "Without an identifier, companies in the same country whose name differs only "
        "in punctuation, spacing, case or legal form come back as POSSIBLE_DUPLICATE "
        "candidates for a person to choose between; a GSTIN held by two companies does "
        "the same (decision IQ-9). The response names candidates by id, name and "
        "country, and never carries an identifier. Nothing is created or changed."
    ),
    responses={
        200: {"model": CompanyMatchResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def match_company(
    body: CompanyMatchRequest,
    current_user: Annotated[User, Depends(_MATCHER)],
    db: AsyncSession = Depends(get_db),
) -> CompanyMatchResponse:
    result = await CompanyDirectoryService(db).match(
        name=body.name,
        country=body.country,
        pan=body.pan,
        gstin=body.gstin,
        registration_number=body.registration_number,
        actor_role=current_user.role.value,
        actor_id=str(current_user.id),
    )
    return CompanyMatchResponse(
        kind=result.kind,
        company_id=result.company_id,
        reason=result.reason,
        needs_a_person=result.needs_a_person,
        candidates=await _candidates(db, result.candidates),
    )


async def _candidates(
    db: AsyncSession, company_ids: tuple[uuid.UUID, ...]
) -> list[CompanyMatchCandidate]:
    """Each candidate as a name, a country and whether it is in the pipeline.

    Deliberately not the company response shape: that one carries PAN, GSTIN, IEC,
    CIN and the registration number, masked, and this route must not hand back
    identifiers at all (module docstring). Three columns, chosen because they are
    what a person needs to tell two companies apart — and `pipeline_status`, because
    "this one exists only as somebody's buyer" is exactly what tells an RM they have
    found the right record rather than a different company.

    Ordered as the matcher ordered them, so two identical calls agree.
    """
    if not company_ids:
        return []
    rows = await db.execute(
        select(
            ExporterProfile.customer_id,
            ExporterProfile.name,
            ExporterProfile.country,
            ExporterProfile.pipeline_status,
        ).where(ExporterProfile.customer_id.in_(company_ids))
    )
    by_id = {row.customer_id: row for row in rows}
    return [
        CompanyMatchCandidate(
            company_id=company_id,
            name=by_id[company_id].name,
            country=by_id[company_id].country,
            pipeline_status=by_id[company_id].pipeline_status
            or CompanyPipelineStatus.IN_PIPELINE,
        )
        for company_id in company_ids
        if company_id in by_id
    ]
