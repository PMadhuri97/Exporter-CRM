"""Trade history routes — **owner: Developer 3** (allocation task 3.20, plan P5-3,
P5-4; decision IQ-19).

What two companies have traded, and how it went. A relationship hangs off neither
company in particular — it is the pair — so reading one company's relationships is a
company sub-resource while a relationship and an invoice have their own paths.

Who may do what (IQ-19)
-----------------------
* **Read** — OPERATIONS, COMPLIANCE, ADMIN and **DEVELOPER**. DEVELOPER is included
  deliberately: these responses carry no identifiers for anyone (see
  ``schemas/trade_history.py``), which is what makes "DEVELOPER reads masked" true
  here without a masking pass. It matches the history log, which already serves
  ``trade`` rows to DEVELOPER.
* **Write** — OPERATIONS, COMPLIANCE, ADMIN. A relationship manager records what a
  buyer did with an invoice; that is their job, not compliance's.
* **API_USER** — nothing, as everywhere else in the CRM.

There is no edit and no delete route. An invoice's identity is frozen by trigger and
an outcome is append-only: a correction is a **new** outcome naming the one it
replaces. That is the whole design, so the absence of those routes is the feature.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.deal import DealSide
from app.modules.onboarding.api.schemas.trade_history import (
    DealPaymentOutcomeResponse,
    RecordDealPaymentOutcomeRequest,
    RecordTradeInvoiceRequest,
    RecordTradeOutcomeRequest,
    TradeCounterparty,
    TradeInvoiceDetailResponse,
    TradeInvoiceResponse,
    TradeOutcomeResponse,
    TradeRelationshipDetailResponse,
    TradeRelationshipListResponse,
    TradeRelationshipResponse,
)
from app.modules.onboarding.application.trade_history_service import TradeHistoryService
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.trade_invoice import (
    DealInvoiceDraft,
    TradeInvoice,
)
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.modules.onboarding.exceptions import (
    TradeInvoiceNotFoundError,
    TradeRelationshipNotFoundError,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

#: Every CRM reader, DEVELOPER included — these responses carry no identifiers
#: (module docstring, decision IQ-19).
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
#: RM, Compliance, Admin record invoices and outcomes (IQ-19).
_WRITER = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


async def _counterparties(
    db: AsyncSession, relationships: list[TradeRelationship]
) -> dict[uuid.UUID, TradeCounterparty]:
    """Both companies of every relationship, in one query rather than one per row."""
    wanted = {r.seller_company_id for r in relationships} | {
        r.buyer_company_id for r in relationships
    }
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            ExporterProfile.customer_id,
            ExporterProfile.name,
            ExporterProfile.country,
            ExporterProfile.pipeline_status,
        ).where(ExporterProfile.customer_id.in_(wanted))
    )
    return {
        row.customer_id: TradeCounterparty(
            company_id=row.customer_id,
            name=row.name,
            country=row.country,
            pipeline_status=row.pipeline_status or CompanyPipelineStatus.IN_PIPELINE,
        )
        for row in rows
    }


async def _invoice_counts(
    db: AsyncSession, relationships: list[TradeRelationship]
) -> dict[uuid.UUID, int]:
    """How many invoices each relationship has — one grouped query, so a list of
    twenty relationships costs one extra round trip rather than twenty."""
    ids = [r.id for r in relationships]
    if not ids:
        return {}
    rows = await db.execute(
        select(TradeInvoice.relationship_id, func.count())
        .where(TradeInvoice.relationship_id.in_(ids))
        .group_by(TradeInvoice.relationship_id)
    )
    return {relationship_id: count for relationship_id, count in rows}


def _relationship_response(
    relationship: TradeRelationship,
    counterparties: dict[uuid.UUID, TradeCounterparty],
    invoice_count: int,
) -> TradeRelationshipResponse:
    return TradeRelationshipResponse(
        id=relationship.id,
        seller=counterparties[relationship.seller_company_id],
        buyer=counterparties[relationship.buyer_company_id],
        source=relationship.source,
        created_at=relationship.created_at,
        invoice_count=invoice_count,
    )


async def _invoice_responses(
    service: TradeHistoryService, invoices: list[TradeInvoice]
) -> list[TradeInvoiceResponse]:
    """Each invoice with the outcome we currently believe.

    One head query per invoice. Acceptable because a relationship's invoice list is
    the page a person is looking at, not a report over every relationship; if that
    changes, the head is derivable in one pass with a NOT IN over the same table.
    """
    responses: list[TradeInvoiceResponse] = []
    for invoice in invoices:
        head = await service.current_outcome(invoice.id)
        response = TradeInvoiceResponse.model_validate(invoice)
        if head is not None:
            response.current_outcome = TradeOutcomeResponse.model_validate(head)
            response.current_outcome.is_current = True
        responses.append(response)
    return responses


@router.get(
    "/exporters/{customer_id}/trade-relationships",
    response_model=TradeRelationshipListResponse,
    summary="A company's trade relationships, as seller or as buyer",
    description=(
        "`as` chooses the side: `seller` (the default) is who this company sells to, "
        "`buyer` who it buys from. Two lists, never one — a company can be on either "
        "side with different counterparties, and one list mixing them would read "
        "differently row by row.\n\n"
        "A relationship is created automatically when a deal records its buyer "
        "company, so every such deal has one. `invoice_count` says whether anything "
        "has been recorded against it yet.\n\n"
        "No identifiers are served to any role: a counterparty is an id, a name, a "
        "country and whether it is in the pipeline. Open the company for the rest."
    ),
    responses={
        200: {"model": TradeRelationshipListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
    },
)
async def list_trade_relationships(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    as_: Annotated[DealSide, Query(alias="as")] = DealSide.SELLER,
    db: AsyncSession = Depends(get_db),
) -> TradeRelationshipListResponse:
    service = TradeHistoryService(db)
    relationships = await service.list_relationships(
        customer_id, as_buyer=as_ is DealSide.BUYER
    )
    counterparties = await _counterparties(db, relationships)
    counts = await _invoice_counts(db, relationships)
    return TradeRelationshipListResponse(
        relationships=[
            _relationship_response(r, counterparties, counts.get(r.id, 0))
            for r in relationships
        ],
        total=len(relationships),
    )


@router.get(
    "/trade-relationships/{relationship_id}",
    response_model=TradeRelationshipDetailResponse,
    summary="One trade relationship, with its invoices",
    description=(
        "Invoices newest first, each carrying the outcome we currently believe. "
        "`current_outcome` is `null` when nobody has recorded one — which is not the "
        "same as `UNKNOWN`, where somebody looked and could not say.\n\n"
        "An invoice's whole outcome chain is `GET /trade-invoices/{id}`."
    ),
    responses={
        200: {"model": TradeRelationshipDetailResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
        404: {"description": "Trade relationship not found"},
    },
)
async def get_trade_relationship(
    relationship_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> TradeRelationshipDetailResponse:
    relationship = await db.scalar(
        select(TradeRelationship).where(TradeRelationship.id == relationship_id)
    )
    if relationship is None:
        raise TradeRelationshipNotFoundError(relationship_id)

    service = TradeHistoryService(db)
    counterparties = await _counterparties(db, [relationship])
    invoices = await service.list_invoices(relationship_id)
    return TradeRelationshipDetailResponse(
        relationship=_relationship_response(relationship, counterparties, len(invoices)),
        invoices=await _invoice_responses(service, invoices),
    )


@router.get(
    "/trade-invoices/{invoice_id}",
    response_model=TradeInvoiceDetailResponse,
    summary="One invoice and its whole outcome chain",
    description=(
        "Outcomes oldest first — every belief and when it was replaced, not just the "
        "current one. `is_current` marks the live row, which is the outcome nothing "
        "supersedes rather than the newest by timestamp: two rows written in one "
        "transaction share a timestamp.\n\n"
        "Nothing here is editable. A correction is a new outcome naming the one it "
        "replaces, and an invoice's identity is frozen by trigger."
    ),
    responses={
        200: {"model": TradeInvoiceDetailResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
        404: {"description": "Trade invoice not found"},
    },
)
async def get_trade_invoice(
    invoice_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> TradeInvoiceDetailResponse:
    invoice = await db.scalar(select(TradeInvoice).where(TradeInvoice.id == invoice_id))
    if invoice is None:
        raise TradeInvoiceNotFoundError(invoice_id)

    service = TradeHistoryService(db)
    head = await service.current_outcome(invoice_id)
    outcomes = await service.list_outcomes(invoice_id)
    [response] = await _invoice_responses(service, [invoice])
    return TradeInvoiceDetailResponse(
        invoice=response,
        outcomes=[
            _outcome_response(outcome, is_current=head is not None and outcome.id == head.id)
            for outcome in outcomes
        ],
    )


def _outcome_response(outcome, *, is_current: bool) -> TradeOutcomeResponse:
    response = TradeOutcomeResponse.model_validate(outcome)
    response.is_current = is_current
    return response


def _evidence_refs(body: RecordTradeOutcomeRequest) -> list[dict] | None:
    """The request's references as the plain `{type, ref}` objects the service
    validates and stores."""
    if body.evidence_refs is None:
        return None
    return [ref.model_dump() for ref in body.evidence_refs]


@router.post(
    "/trade-relationships/{relationship_id}/invoices",
    response_model=TradeInvoiceResponse,
    status_code=201,
    summary="Record an invoice against a trade relationship",
    description=(
        "A fact about the past: its identity — the relationship, number, date, amount "
        "and currency — is frozen once written, so there is no edit route. A mistake "
        "is corrected by recording the right invoice; the wrong one stays visible.\n\n"
        "The currency is stored as issued and **never converted** (decision IQ-4). "
        "Amounts come back as strings, because money is not a float and JSON numbers "
        "would invite adding two currencies together.\n\n"
        "`deal_id` is omitted for past trade — what the two companies did before they "
        "came to us. One invoice number per relationship; the same number on another "
        "relationship is a different invoice."
    ),
    responses={
        201: {"model": TradeInvoiceResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Trade relationship not found"},
        422: {
            "description": (
                "A blank number, a non-positive amount, a currency that is not an ISO "
                "4217 code, or a number this relationship already has"
            )
        },
    },
)
async def record_trade_invoice(
    relationship_id: uuid.UUID,
    body: RecordTradeInvoiceRequest,
    current_user: Annotated[User, Depends(_WRITER)],
    db: AsyncSession = Depends(get_db),
) -> TradeInvoiceResponse:
    service = TradeHistoryService(db)
    invoice = await service.record_invoice(
        relationship_id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        amount=body.amount,
        currency=body.currency,
        deal_id=body.deal_id,
        actor_id=str(current_user.id),
    )
    [response] = await _invoice_responses(service, [invoice])
    return response


@router.post(
    "/trade-invoices/{invoice_id}/outcomes",
    response_model=TradeOutcomeResponse,
    status_code=201,
    summary="Append what we now know about an invoice",
    description=(
        "Nothing is edited. A correction is a **new** outcome naming the one it "
        "replaces, so the record says what we believed and when we stopped believing "
        "it.\n\n"
        "`supersedes_outcome_id` must be the invoice's current outcome — omit it for "
        "the first. Anything else is a 409 rather than an overwrite, because two "
        "people each correcting the same outcome without seeing the other's is what "
        "the chain exists to prevent. A correction also needs an `evidence_note`.\n\n"
        "`PARTIAL` requires `amount_paid`, in the invoice's own currency. "
        "`proof_status` is kept apart from `payment_status` on purpose: \"they paid\" "
        "and \"we can prove they paid\" are different claims, and a history that "
        "could not tell them apart would be worthless as evidence."
    ),
    responses={
        201: {"model": TradeOutcomeResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Trade invoice not found"},
        409: {"description": "supersedes_outcome_id is not the invoice's current outcome"},
        422: {
            "description": (
                "A PARTIAL outcome with no amount, a correction with no note, or "
                "malformed evidence"
            )
        },
    },
)
async def record_trade_outcome(
    invoice_id: uuid.UUID,
    body: RecordTradeOutcomeRequest,
    current_user: Annotated[User, Depends(_WRITER)],
    db: AsyncSession = Depends(get_db),
) -> TradeOutcomeResponse:
    outcome = await TradeHistoryService(db).record_outcome(
        invoice_id,
        payment_status=body.payment_status,
        proof_status=body.proof_status,
        amount_paid=body.amount_paid,
        evidence_note=body.evidence_note,
        evidence_refs=_evidence_refs(body),
        supersedes_outcome_id=body.supersedes_outcome_id,
        actor_id=str(current_user.id),
    )
    # Just written, so it is the head by construction.
    return _outcome_response(outcome, is_current=True)


@router.post(
    "/deals/{deal_id}/payment-outcome",
    response_model=DealPaymentOutcomeResponse,
    status_code=201,
    summary="Record how a handed-over deal was paid",
    description=(
        "The last question the CRM answers about a deal: it went to the lending team, "
        "and then what happened. Recorded at the deal, because the person who knows "
        "has the deal in front of them rather than a relationship id and an invoice "
        "id.\n\n"
        "**Creates the invoice if this deal has none**, from the number, date, amount "
        "and currency in the body — all four together or none. If the deal already "
        "has an invoice they must be omitted: an invoice's identity is frozen, and "
        "ignoring new details would tell you they had been recorded.\n\n"
        "The deal must be `HANDED_OVER`: before that there is nothing to have been "
        "paid. It must also name a **buyer company** — a trade relationship is a pair "
        "of company records, and a deal whose buyer is still a legacy `deal_buyer` row "
        "has nothing to pair with until the buyer migration links it.\n\n"
        "Further outcomes supersede, exactly as on `POST /trade-invoices/{id}/"
        "outcomes`: a correction is a new row naming the one it replaces."
    ),
    responses={
        201: {"model": DealPaymentOutcomeResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Deal not found"},
        409: {
            "description": (
                "The deal is not handed over, its buyer is not a company, or "
                "supersedes_outcome_id is not the invoice's current outcome"
            )
        },
        422: {
            "description": (
                "A partial invoice identity, invoice details for a deal that already "
                "has one, a PARTIAL outcome with no amount, or a correction with no note"
            )
        },
    },
)
async def record_deal_payment_outcome(
    deal_id: uuid.UUID,
    body: RecordDealPaymentOutcomeRequest,
    current_user: Annotated[User, Depends(_WRITER)],
    db: AsyncSession = Depends(get_db),
) -> DealPaymentOutcomeResponse:
    service = TradeHistoryService(db)
    draft = (
        DealInvoiceDraft(
            invoice_number=body.invoice_number,
            invoice_date=body.invoice_date,
            amount=body.amount,
            currency=body.currency,
        )
        if body.invoice_fields_given
        else None
    )
    invoice, outcome = await service.record_outcome_for_deal(
        deal_id,
        payment_status=body.payment_status,
        proof_status=body.proof_status,
        amount_paid=body.amount_paid,
        evidence_note=body.evidence_note,
        evidence_refs=_evidence_refs(body),
        supersedes_outcome_id=body.supersedes_outcome_id,
        invoice=draft,
        actor_id=str(current_user.id),
    )
    [invoice_response] = await _invoice_responses(service, [invoice])
    return DealPaymentOutcomeResponse(
        invoice=invoice_response,
        outcome=_outcome_response(outcome, is_current=True),
        invoice_created=draft is not None,
    )
