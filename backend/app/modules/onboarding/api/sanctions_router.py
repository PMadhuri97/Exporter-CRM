"""Structured sanctions screening.

* **Lists** (Settings → Sanctions lists): read with `screening:view`, changed with
  `settings:manage`. Every change is a new version.
* **A company's screening**: its subjects, their latest runs, what needs re-screening,
  the standing and the flag — `screening:view` (staff; never DEVELOPER).
* **Record a run, decide a hit** — `screening:decide` (compliance).
* **Confirm or reject a proposed true match** — admitted for `screening:decide` or
  `compliance:approve_true_match`; who may is then `CRM_SANCTIONS_TRUE_MATCH_APPROVAL`'s
  rule (403 `SANCTIONS_TRUE_MATCH_REFUSED`, saying why).
* **Worklists**: proposed true matches awaiting confirmation, and companies due a
  re-screen.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.compliance_settings import true_match_approval
from app.modules.onboarding.application.sanctions_list_service import SanctionsListService
from app.modules.onboarding.application.sanctions_screening_service import (
    HitInput,
    RunView,
    SanctionsScreeningService,
    actor_from,
)
from app.modules.onboarding.domain import sanctions as rules
from app.platform.authentication import display_names
from app.platform.authentication.models import User
from app.platform.authorization.services import (
    get_current_permissions,
    has_permission,
    require_any_permission,
    require_permission,
)
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_VIEW = require_permission("screening", "view")
_DECIDE = require_permission("screening", "decide")
_SETTINGS = require_permission("settings", "manage")
_CONFIRM = require_any_permission(("screening", "decide"), ("compliance", "approve_true_match"))
_PERMISSIONS = Annotated[frozenset[tuple[str, str]], Depends(get_current_permissions)]

Subject = Literal["COMPANY", "DIRECTOR", "UBO"]
Disposition = Literal["OPEN", "FALSE_POSITIVE", "TRUE_MATCH", "ESCALATED"]
StoredDisposition = Literal["OPEN", "FALSE_POSITIVE", "TRUE_MATCH_PROPOSED", "TRUE_MATCH", "ESCALATED"]
Outcome = Literal["PASSED", "FAILED", "REVIEW"]


# ── Shapes ───────────────────────────────────────────────────────────────────


class SanctionsListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    version: int
    name: str
    authority: str | None
    active: bool
    mandatory: bool
    list_version_date: date
    is_current: bool


class SanctionsListsResponse(BaseModel):
    lists: list[SanctionsListResponse]
    history: list[SanctionsListResponse]
    can_edit: bool


class AddSanctionsListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(min_length=1, max_length=200)
    authority: str | None = Field(default=None, max_length=200)
    mandatory: bool = False
    list_version_date: date


class ReviseSanctionsListRequest(BaseModel):
    """Writes the next version. A newer `list_version_date` puts every company screened
    against an older one on the re-screen worklist."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    authority: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    mandatory: bool | None = None
    list_version_date: date | None = None


class HitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_code: str = Field(min_length=1, max_length=40)
    matched_name: str = Field(min_length=1, max_length=255)
    list_entry_id: str | None = Field(default=None, max_length=100)
    score: Decimal | None = Field(default=None, ge=0, le=100)
    #: The first decision; anything but OPEN needs a reason. TRUE_MATCH is recorded as
    #: proposed unless confirmation is switched off.
    disposition: Disposition = "OPEN"
    reason: str | None = Field(default=None, max_length=2000)


class RecordRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: Subject = "COMPANY"
    #: The person or company screened; the company's own name when left out.
    subject_name: str | None = Field(default=None, max_length=255)
    #: The beneficial-owner record, for a UBO subject.
    subject_reference: uuid.UUID | None = None
    #: The lists screened; must include every active mandatory list.
    list_codes: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, max_length=2)
    provider: str = Field(default="MANUAL", max_length=100)
    provider_reference: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=4000)
    hits: list[HitRequest] = Field(default_factory=list)


class DecideHitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: Disposition
    reason: str | None = Field(default=None, max_length=2000)


class RejectTrueMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class DispositionResponse(BaseModel):
    id: uuid.UUID
    disposition: StoredDisposition
    reason: str | None
    decided_by: str
    decided_by_name: str | None = None
    decided_at: datetime
    approved_by: str | None
    approved_by_name: str | None = None


class HitResponse(BaseModel):
    id: uuid.UUID
    list_code: str
    matched_name: str
    list_entry_id: str | None
    score: Decimal | None
    current: DispositionResponse
    decisions: list[DispositionResponse]


class RunListResponse(BaseModel):
    code: str
    list_version_date: date


class RunResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    subject_type: Subject
    subject_name: str
    subject_reference: uuid.UUID | None
    cycle_id: uuid.UUID | None
    performed_by: str
    performed_by_name: str | None = None
    performed_at: datetime
    provider: str
    provider_reference: str | None
    search_terms: dict
    note: str | None
    lists: list[RunListResponse]
    hits: list[HitResponse]
    outcome: Outcome


class RunListOfCompanyResponse(BaseModel):
    runs: list[RunResponse]


class SubjectCoverageResponse(BaseModel):
    subject_type: Subject
    subject_name: str
    subject_reference: uuid.UUID | None
    latest: RunResponse | None
    #: Why the subject needs screening again; empty when it does not.
    rescreen_reasons: list[str]


class CompanySanctionsResponse(BaseModel):
    company_id: uuid.UUID
    #: PASSED, FAILED or REVIEW — the worst of the subjects' latest runs; `null` before
    #: the company itself is screened.
    standing: Outcome | None
    #: A true match is proposed or confirmed: the company's deals cannot be handed over.
    flagged: bool
    subjects: list[SubjectCoverageResponse]
    #: What this reader may do here.
    can_record: bool
    true_match_approval: Literal["SINGLE", "SECOND_OFFICER", "HEAD"]


class PendingTrueMatchResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str | None
    run_id: uuid.UUID
    subject_name: str
    hit: HitResponse
    can_confirm: bool


class PendingTrueMatchListResponse(BaseModel):
    matches: list[PendingTrueMatchResponse]


class RescreenDueResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str | None
    reasons: list[str]


class RescreenDueListResponse(BaseModel):
    companies: list[RescreenDueResponse]
    total: int


# ── Mapping ──────────────────────────────────────────────────────────────────


async def _runs(db: AsyncSession, views: list[RunView]) -> list[RunResponse]:
    names = await display_names(
        db,
        [view.run.performed_by for view in views]
        + [
            who
            for view in views
            for hit in view.hits
            for row in hit.decisions
            for who in (row.decided_by, row.approved_by)
        ],
        email_fallback=True,
    )

    def disposition(row) -> DispositionResponse:
        return DispositionResponse(
            id=row.id,
            disposition=row.disposition,
            reason=row.reason,
            decided_by=row.decided_by,
            decided_by_name=names.get(row.decided_by),
            decided_at=row.decided_at,
            approved_by=row.approved_by,
            approved_by_name=names.get(row.approved_by or ""),
        )

    def hit(view_hit) -> HitResponse:
        return HitResponse(
            id=view_hit.hit.id,
            list_code=view_hit.hit.list_code,
            matched_name=view_hit.hit.matched_name,
            list_entry_id=view_hit.hit.list_entry_id,
            score=view_hit.hit.score,
            current=disposition(view_hit.current),
            decisions=[disposition(row) for row in view_hit.decisions],
        )

    return [
        RunResponse(
            id=view.run.id,
            company_id=view.run.company_id,
            subject_type=view.run.subject_type,  # type: ignore[arg-type]
            subject_name=view.run.subject_name,
            subject_reference=view.run.subject_reference,
            cycle_id=view.run.cycle_id,
            performed_by=view.run.performed_by,
            performed_by_name=names.get(view.run.performed_by),
            performed_at=view.run.performed_at,
            provider=view.run.provider,
            provider_reference=view.run.provider_reference,
            search_terms=view.run.search_terms,
            note=view.run.note,
            lists=[RunListResponse(code=r.code, list_version_date=r.list_version_date) for r in view.lists],
            hits=[hit(h) for h in view.hits],
            outcome=view.outcome,  # type: ignore[arg-type]
        )
        for view in views
    ]


async def _run(db: AsyncSession, view: RunView) -> RunResponse:
    return (await _runs(db, [view]))[0]


# ── Lists ────────────────────────────────────────────────────────────────────


@router.get(
    "/settings/sanctions-lists",
    response_model=SanctionsListsResponse,
    summary="The sanctions lists screenings cover",
    description=(
        "`lists` is the current version of each list, inactive ones included; `history` "
        "every version. A screening must cover every active, mandatory list."
    ),
    responses={401: {"description": "Unauthorized"}, 403: {"description": "`screening:view` required"}},
)
async def list_sanctions_lists(
    current_user: Annotated[User, Depends(_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> SanctionsListsResponse:
    service = SanctionsListService(db)
    return SanctionsListsResponse(
        lists=[SanctionsListResponse.model_validate(r) for r in await service.current()],
        history=[SanctionsListResponse.model_validate(r) for r in await service.history()],
        can_edit=has_permission(current_user, "settings", "manage"),
    )


@router.post(
    "/settings/sanctions-lists",
    response_model=SanctionsListResponse,
    status_code=201,
    summary="Add a sanctions list",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`settings:manage` permission required"},
        422: {"description": "A code already used"},
    },
)
async def add_sanctions_list(
    body: AddSanctionsListRequest,
    current_user: Annotated[User, Depends(_SETTINGS)],
    db: AsyncSession = Depends(get_db),
) -> SanctionsListResponse:
    row = await SanctionsListService(db).add(
        code=body.code,
        name=body.name,
        authority=body.authority,
        mandatory=body.mandatory,
        list_version_date=body.list_version_date,
        actor_id=str(current_user.id),
    )
    return SanctionsListResponse.model_validate(row)


@router.patch(
    "/settings/sanctions-lists/{code}",
    response_model=SanctionsListResponse,
    summary="Change a sanctions list, or record a new version of it",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`settings:manage` permission required"},
        404: {"description": "No such list"},
        422: {"description": "Nothing changes, or a version date earlier than the current one"},
    },
)
async def revise_sanctions_list(
    code: str,
    body: ReviseSanctionsListRequest,
    current_user: Annotated[User, Depends(_SETTINGS)],
    db: AsyncSession = Depends(get_db),
) -> SanctionsListResponse:
    row = await SanctionsListService(db).revise(
        code.upper(),
        name=body.name,
        authority=body.authority,
        authority_sent="authority" in body.model_fields_set,
        active=body.active,
        mandatory=body.mandatory,
        list_version_date=body.list_version_date,
        actor_id=str(current_user.id),
    )
    return SanctionsListResponse.model_validate(row)


# ── A company's screening ────────────────────────────────────────────────────


@router.get(
    "/exporters/{company_id}/sanctions",
    response_model=CompanySanctionsResponse,
    summary="A company's sanctions coverage",
    description=(
        "Every subject — the company, each beneficial owner on record, and anyone "
        "else screened — with its latest run in the current check cycle and why it is "
        "due a re-screen; the company's standing; and whether a true match flags it."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
        404: {"description": "Company not found"},
    },
)
async def get_company_sanctions(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> CompanySanctionsResponse:
    standing = await SanctionsScreeningService(db).company(company_id)
    latest = [s.latest for s in standing.subjects if s.latest is not None]
    responses = {r.id: r for r in await _runs(db, latest)}
    return CompanySanctionsResponse(
        company_id=company_id,
        standing=standing.standing,  # type: ignore[arg-type]
        flagged=standing.flagged,
        subjects=[
            SubjectCoverageResponse(
                subject_type=s.subject_type,  # type: ignore[arg-type]
                subject_name=s.subject_name,
                subject_reference=s.subject_reference,
                latest=responses.get(s.latest.run.id) if s.latest else None,
                rescreen_reasons=s.rescreen_reasons,
            )
            for s in standing.subjects
        ],
        can_record=has_permission(current_user, "screening", "decide"),
        true_match_approval=true_match_approval().value,  # type: ignore[arg-type]
    )


@router.get(
    "/exporters/{company_id}/sanctions/runs",
    response_model=RunListOfCompanyResponse,
    summary="Every sanctions screening of a company, newest first",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
    },
)
async def list_company_sanctions_runs(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> RunListOfCompanyResponse:
    return RunListOfCompanyResponse(
        runs=await _runs(db, await SanctionsScreeningService(db).runs_for(company_id))
    )


@router.post(
    "/exporters/{company_id}/sanctions/runs",
    response_model=RunResponse,
    status_code=201,
    summary="Record a sanctions screening",
    description=(
        "One subject against the lists named — every active mandatory list included — "
        "with each possible match and a first decision on it. The company's SANCTIONS "
        "check is updated from the result."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:decide` permission required"},
        404: {"description": "Company not found"},
        422: {"description": "A mandatory list missing, an unknown list, or a decision with no reason"},
    },
)
async def record_sanctions_run(
    company_id: uuid.UUID,
    body: RecordRunRequest,
    current_user: Annotated[User, Depends(_DECIDE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    search = {"name": body.subject_name, "aliases": body.aliases, "country": body.country}
    view = await SanctionsScreeningService(db).record_run(
        company_id,
        subject_type=body.subject_type,
        subject_name=body.subject_name,
        subject_reference=body.subject_reference,
        list_codes=body.list_codes,
        hits=[
            HitInput(
                list_code=h.list_code,
                matched_name=h.matched_name,
                list_entry_id=h.list_entry_id,
                score=h.score,
                disposition=h.disposition,
                reason=h.reason,
            )
            for h in body.hits
        ],
        search_terms={key: value for key, value in search.items() if value} or None,
        provider=body.provider,
        provider_reference=body.provider_reference,
        note=body.note,
        actor=actor_from(current_user, permissions),
    )
    return await _run(db, view)


@router.get(
    "/sanctions/runs/{run_id}",
    response_model=RunResponse,
    summary="One sanctions screening, with its hits and every decision on them",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
        404: {"description": "No such screening"},
    },
)
async def get_sanctions_run(
    run_id: uuid.UUID,
    current_user: Annotated[User, Depends(_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    return await _run(db, await SanctionsScreeningService(db).run_view(run_id))


# ── Decisions ────────────────────────────────────────────────────────────────


@router.post(
    "/sanctions/hits/{hit_id}/decision",
    response_model=RunResponse,
    summary="Decide a possible match",
    description=(
        "A new decision that supersedes the previous one. Anything but OPEN needs a "
        "reason. TRUE_MATCH is recorded as proposed and waits for confirmation, unless "
        "confirmation is switched off."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:decide` permission required"},
        404: {"description": "No such possible match"},
        422: {"description": "No reason, a final true match, or one awaiting confirmation"},
    },
)
async def decide_sanctions_hit(
    hit_id: uuid.UUID,
    body: DecideHitRequest,
    current_user: Annotated[User, Depends(_DECIDE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    view = await SanctionsScreeningService(db).decide(
        hit_id,
        disposition=body.disposition,
        reason=body.reason,
        actor=actor_from(current_user, permissions),
    )
    return await _run(db, view)


@router.post(
    "/sanctions/hits/{hit_id}/confirm",
    response_model=RunResponse,
    summary="Confirm a proposed true match",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`SANCTIONS_TRUE_MATCH_REFUSED`, with why"},
        404: {"description": "No such possible match"},
        422: {"description": "No proposed true match on this hit"},
    },
)
async def confirm_true_match(
    hit_id: uuid.UUID,
    current_user: Annotated[User, Depends(_CONFIRM)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    view = await SanctionsScreeningService(db).confirm_true_match(
        hit_id, actor=actor_from(current_user, permissions)
    )
    return await _run(db, view)


@router.post(
    "/sanctions/hits/{hit_id}/reject",
    response_model=RunResponse,
    summary="Reject a proposed true match; the match goes back to open",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`SANCTIONS_TRUE_MATCH_REFUSED`, with why"},
        404: {"description": "No such possible match"},
        422: {"description": "No proposed true match, or no reason"},
    },
)
async def reject_true_match(
    hit_id: uuid.UUID,
    body: RejectTrueMatchRequest,
    current_user: Annotated[User, Depends(_CONFIRM)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    view = await SanctionsScreeningService(db).reject_true_match(
        hit_id, reason=body.reason, actor=actor_from(current_user, permissions)
    )
    return await _run(db, view)


# ── Worklists ────────────────────────────────────────────────────────────────


@router.get(
    "/sanctions/true-matches",
    response_model=PendingTrueMatchListResponse,
    summary="Proposed true matches awaiting confirmation",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:decide` or `compliance:approve_true_match` required"},
    },
)
async def list_pending_true_matches(
    current_user: Annotated[User, Depends(_CONFIRM)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> PendingTrueMatchListResponse:
    service = SanctionsScreeningService(db)
    actor = actor_from(current_user, permissions)
    mode = true_match_approval()
    out = []
    for pending in await service.pending_true_matches():
        view = await service.run_view(pending.run.id)
        run = await _run(db, view)
        hit = next(h for h in run.hits if h.id == pending.hit.id)
        out.append(
            PendingTrueMatchResponse(
                company_id=pending.company_id,
                company_name=pending.company_name,
                run_id=pending.run.id,
                subject_name=pending.run.subject_name,
                hit=hit,
                can_confirm=rules.true_match_refusal(
                    mode,
                    proposer_id=pending.proposal.decided_by,
                    approver_id=actor.id,
                    approver_permissions=actor.permissions,
                )
                is None,
            )
        )
    return PendingTrueMatchListResponse(matches=out)


@router.get(
    "/sanctions/rescreen-due",
    response_model=RescreenDueListResponse,
    summary="Companies due a sanctions re-screen",
    description=(
        "Companies screened before whose latest screening is out of date: a list has a "
        "newer version or became mandatory, the company's name changed, or a beneficial "
        "owner was never screened."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
    },
)
async def list_rescreen_due(
    current_user: Annotated[User, Depends(_VIEW)],
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> RescreenDueListResponse:
    rows = await SanctionsScreeningService(db).rescreen_due(limit=limit)
    return RescreenDueListResponse(
        companies=[
            RescreenDueResponse(company_id=r.company_id, company_name=r.company_name, reasons=r.reasons)
            for r in rows
        ],
        total=len(rows),
    )


__all__ = ["router"]
