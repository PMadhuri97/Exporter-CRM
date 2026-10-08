"""Screening-review checklist and bank-activity routes (architecture §8.1, §9.4).

Split out of `exporter_router.py` so the company routes and the
background-check routes stop sharing one file. Mounted by `router.py` beside
`exporter_router`, with the same `/exporters` prefix and `Exporter CRM` tag, so
every path stays `/onboarding/exporters/...`.

The list serves the one screening catalogue and the caller's
capabilities, so the frontend keeps neither a key list nor a role list; unknown
companies are 404; each item's history is readable. Roles are unchanged — read
OPERATIONS/COMPLIANCE/ADMIN, write COMPLIANCE/ADMIN; DEVELOPER stays refused
(decided 28 Sep 2026: no widening). Each decision is also recorded in the
company history under the `screening` dimension.

The screening checklist is a compliance list inside the background check. It is
not qualification (architecture §5.5).

Since 1 October 2026 the list is about one check cycle — the current one, or
an earlier one named by ``cycle_id`` (read-only: ``can_record_decision`` is false
there) — and lists the seven catalogue items. An answer may carry evidence
references. A retired item's history stays readable; a new answer to it is 422.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.background_check import CheckCycleResponse
from app.modules.onboarding.api.schemas.screening import (
    BankActivityFindingResponse,
    BankActivityResponse,
    ScreeningCapabilities,
    ScreeningCatalogueItemResponse,
    ScreeningItemHistoryResponse,
    ScreeningReviewItemResponse,
    ScreeningReviewListResponse,
    UpdateScreeningReviewItemRequest,
)
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE_ITEMS,
    ScreeningCycleScope,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
    resolved_cycle_id,
)
from app.platform.authentication.models import User
from app.platform.authorization.services import has_permission, require_permission
from app.platform.database.services import get_db

router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

_SCREENING_DECIDE = require_permission("screening", "decide")
_SCREENING_VIEW = require_permission("screening", "view")

#: Recording a screening decision is compliance's (`screening:decide`); a plain API_USER
#: must never be able to mark a sanctions check PASSED. The same permission gates the
#: route and answers `can_record_decision`, so the two cannot drift. Reads need
#: `screening:view`.

_CATALOGUE = [ScreeningCatalogueItemResponse.model_validate(i) for i in SCREENING_CATALOGUE_ITEMS]


def _item(
    row: ScreeningReviewItem, names: dict[str, str], initial: CheckCycle | None
) -> ScreeningReviewItemResponse:
    """One answer as served: named, with the legacy cycle rule applied."""
    return (
        ScreeningReviewItemResponse.model_validate(row)
        .named(names)
        .model_copy(update={"cycle_id": resolved_cycle_id(row.cycle_id, initial)})
    )


def _cycle(scope: ScreeningCycleScope, names: dict[str, str]) -> CheckCycleResponse | None:
    cycle = scope.selected
    if cycle is None:
        return None
    return CheckCycleResponse(
        id=cycle.id,
        company_id=cycle.company_id,
        number=cycle.number,
        kind=cycle.kind,
        reason=cycle.reason,
        started_at=cycle.started_at,
        started_by=cycle.created_by,
        started_by_name=names.get(cycle.created_by),
        source=cycle.source,
        rules_version=cycle.rules_version,
        is_current=scope.is_current,
    )


# ── Screening review workspace ────────────────────────────────────────────

@router.get(
    "/{customer_id}/screening-review",
    response_model=ScreeningReviewListResponse,
    summary="List persisted screening-review checklist decisions",
    description=(
        "The decision on each checklist item that has one in a check cycle — the "
        "current cycle, or the one named by `cycle_id` — the full checklist catalogue "
        "in display order, and whether the caller may record a decision (only ever in "
        "the current cycle)."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
        404: {"description": "Company not found, or a `cycle_id` that is not this company's"},
    },
)
async def list_screening_review(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_SCREENING_VIEW)],
    db: AsyncSession = Depends(get_db),
    cycle_id: uuid.UUID | None = Query(
        default=None, description="A check cycle of this company. Default: the current one."
    ),
) -> ScreeningReviewListResponse:
    service = ScreeningReviewService(db)
    scope = await service.cycle_scope(customer_id, cycle_id)
    items = await service.list_review_items(customer_id, scope=scope)
    names = await actor_names(
        db,
        current_user,
        [*(item.reviewed_by for item in items), scope.selected.created_by if scope.selected else None],
    )
    return ScreeningReviewListResponse(
        customer_id=customer_id,
        items=[_item(item, names, scope.initial) for item in items],
        catalogue=_CATALOGUE,
        capabilities=ScreeningCapabilities(
            can_record_decision=has_permission(current_user, "screening", "decide")
            and scope.is_current
        ),
        cycle=_cycle(scope, names),
    )


@router.get(
    "/{customer_id}/screening-review/{item_key}/history",
    response_model=ScreeningItemHistoryResponse,
    summary="Every decision recorded on one screening-review checklist item",
    description=(
        "Newest first, paged. The checklist table is append-only, so this is the "
        "item's complete history; the first row of the first page is its current state."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
        404: {"description": "Company not found"},
        422: {"description": "Unknown checklist item"},
    },
)
async def list_screening_review_item_history(
    customer_id: uuid.UUID,
    item_key: str,
    current_user: Annotated[User, Depends(_SCREENING_VIEW)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ScreeningItemHistoryResponse:
    rows, total = await ScreeningReviewService(db).list_item_history(
        customer_id, item_key, limit=limit, offset=offset
    )
    names = await actor_names(db, current_user, (row.reviewed_by for row in rows))
    cycles = await CheckCycleRepository(db).list_for_company(customer_id)
    initial = cycles[0] if cycles else None
    return ScreeningItemHistoryResponse(
        customer_id=customer_id,
        item_key=item_key,
        items=[_item(row, names, initial) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/{customer_id}/screening-review/{item_key}",
    response_model=ScreeningReviewItemResponse,
    summary="Record or update one screening-review checklist decision",
    description=(
        "Appends a new answer to the item in the company's current check cycle; every "
        "earlier answer stays in the item's history. `evidence_refs` is optional: a "
        "`document` must be one of the company's own `AVAILABLE` documents, a `url` an "
        "http(s) link. A retired item (`website-reviewed`) takes no new answer."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:decide` permission required"},
        404: {"description": "Company not found"},
        422: {
            "description": (
                "Unknown or retired checklist item, unknown status, or evidence that is "
                "malformed, foreign or not AVAILABLE"
            )
        },
    },
)
async def update_screening_review(
    customer_id: uuid.UUID,
    item_key: str,
    body: UpdateScreeningReviewItemRequest,
    current_user: Annotated[User, Depends(_SCREENING_DECIDE)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewItemResponse:
    item = await ScreeningReviewService(db).upsert_review_item(
        customer_id,
        item_key=item_key,
        status=body.status,
        comment=body.comment,
        actor_id=str(current_user.id),
        evidence=body.to_evidence(),
    )
    names = await actor_names(db, current_user, [item.reviewed_by])
    # A new answer always carries its cycle, so no legacy rule applies.
    return _item(item, names, None)


@router.get(
    "/{customer_id}/bank-activity",
    response_model=BankActivityResponse,
    summary="List bank-linked suspicious-activity findings",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`screening:view` permission required"},
    },
    description=(
        "No bank-monitoring provider feed is connected: the response says so "
        "(`provider_feed_connected: false`, `provider_feed_status: NOT_CONNECTED`) "
        "and never carries fabricated findings."
    ),
)
async def get_bank_activity(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_SCREENING_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> BankActivityResponse:
    findings = await ScreeningReviewService(db).list_bank_findings(customer_id)
    open_findings = sum(1 for finding in findings if finding.status == "OPEN")
    last_synced_at = max((finding.detected_at for finding in findings), default=None)
    return BankActivityResponse(
        customer_id=customer_id,
        provider_feed_connected=False,
        connected_accounts=0,
        last_synced_at=last_synced_at,
        open_findings=open_findings,
        findings=[BankActivityFindingResponse.model_validate(finding) for finding in findings],
    )


__all__ = ["router"]
