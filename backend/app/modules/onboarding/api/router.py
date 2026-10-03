import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.company_directory_router import (
    router as company_directory_router,
)
from app.modules.onboarding.api.company_intake_router import router as company_intake_router
from app.modules.onboarding.api.deal_router import router as deal_router
from app.modules.onboarding.api.document_router import router as document_router
from app.modules.onboarding.api.engagement_router import router as engagement_router
from app.modules.onboarding.api.exporter_router import router as exporter_router
from app.modules.onboarding.api.follow_up_router import router as follow_up_router
from app.modules.onboarding.api.gst_registration_router import (
    router as gst_registration_router,
)
from app.modules.onboarding.api.history_router import router as history_router
from app.modules.onboarding.api.qualification_router import router as qualification_router
from app.modules.onboarding.api.schemas.case import (
    CaseResponse,
    CaseTransitionListResponse,
    CaseTransitionRequest,
    CreateCaseRequest,
    UpdateCaseRequest,
)
from app.modules.onboarding.api.schemas.onboarding import (
    OnboardingStatusResponse,
    RegisterRequest,
    RegisterResponse,
    SdkTokenResponse,
    WebhookAck,
)
from app.modules.onboarding.api.schemas.verification import (
    RecordReviewRequest,
    TriggerVerificationRequest,
    VerificationCapabilities,
    VerificationResultListResponse,
    VerificationResultResponse,
    reviewer_ids,
)
from app.modules.onboarding.api.screening_router import router as screening_router
from app.modules.onboarding.application import (
    CaseService,
    OnboardingService,
    VerificationService,
    WebhookService,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
)
from app.modules.onboarding.exceptions import VerificationResultNotFoundError
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared.exceptions import AnerBaseException, NotFoundError

logger = structlog.get_logger(__name__)
router = APIRouter()

# Decisions that change what compliance relies on (case state, verification
# outcomes and their review) are compliance-owned.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)
# Routine internal-staff writes, and every read. API_USER (external callers)
# and DEVELOPER (internal technical staff) are excluded.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)

# Exporter CRM (EXP-1) — kept in its own file; see exporter_router.py's module
# docstring for why. Included here (rather than registered separately in
# app/api/rest/router.py) so it inherits this router's own "/onboarding"
# mount prefix, giving the ticket's documented paths
# (/onboarding/exporters...) with no prefix duplicated in two places.
router.include_router(exporter_router)
# The same `/exporters` routes, split by owner in L2-01: contacts and activities
# (Developer 3) and the screening checklist and bank activity (Developer 4).
# Included straight after the company routes, in the order they were declared
# when all three lived in exporter_router.py, so route matching is unchanged.
router.include_router(engagement_router)
router.include_router(screening_router)
# Qualification (L2-09, L2-10) — Developer 2's, in its own file. Its paths are
# absolute (/qualification/..., /exporters/{id}/qualification...), because the
# criteria are not under /exporters.
router.include_router(qualification_router)
# RXIL company intake and bulk CSV import (L2-12, L2-13) — Developer 2's.
router.include_router(company_intake_router)
# "Which company is this?" (P4-3, task 3.10) — Developer 3's. Its own `/companies`
# prefix, because the question is asked before any company id is known; see the
# router's module docstring.
router.include_router(company_directory_router)
# GST registrations — a company's branches (P6-2, P6-5; tasks 3.13, 3.14, 3.17) —
# Developer 3's. Absolute paths, because reading and adding one hangs off a company
# while flagging one takes only the registration's own id.
router.include_router(gst_registration_router)

# Shared CRM history log (L1-11) — Developer 1's, in its own file for the same
# reason the Exporter CRM routes are in theirs, and included here so it
# inherits the "/onboarding" mount prefix. It carries its own full paths
# (/exporters/{id}/history, /deals/{id}/history) rather than a router prefix,
# because the deal route is not under /exporters.
router.include_router(history_router)

# ── The §9.3 routers, mounted once in the seam commit and never re-mounted ──
#
# All three are empty when this lands, and mounting an empty router adds nothing
# to the OpenAPI document — which is the point. Developer 3A (phases 1 and 2)
# and Developer 3B all append to shared files; the router index is one of them,
# so it is edited here, once, and by neither of them again.
#
# Follow-up completion and the due/overdue list (L3-04) — Developer 3A, Phase 2.
# Same `/exporters` prefix as `engagement_router`, because a completion is about
# one company's activity.
router.include_router(follow_up_router)
# Deals and buyers (L3-05, L3-06) — Developer 3B. Absolute paths (`/deals/...`),
# like the deal history route above: a deal is not a company sub-resource.
router.include_router(deal_router)
# Documents and storage (L3-07 … L3-10) — Developer 3B. Absolute paths too,
# because documents hang off deals as well as companies.
router.include_router(document_router)

# ── Dev4 seam — anchor blocks for Developers 4A and 4B (4B-0) ──
#
# Developer 4A mounts exactly one router, and does it here: its import and its
# `router.include_router(background_check_router)` both go in the 4A block below,
# the import with `# noqa: E402`, so neither Dev4 branch edits the import list at the
# top of this file for it. Developer 4B mounts nothing new — its routes live in the
# `EXP-2: generalized verification results` block and `screening_router.py` — and
# edits only that block and its imports. Nothing is mounted here yet, so the OpenAPI
# document is unchanged.
#
# ── Background check — owner: Developer 4A ──
# (4A adds its router import and its one include_router here; 4B does not.)
from app.modules.onboarding.api.background_check_router import (  # noqa: E402
    router as background_check_router,
)

router.include_router(background_check_router)


# ── Case management and its state machine ───────────────
# These endpoints are the case model's surface. They resolve no provider route and
# call no provider: a case is created in DRAFT, and only the state machine below
# moves it, until the route resolver exists.


@router.post(
    "/cases",
    response_model=CaseResponse,
    status_code=201,
    summary="Create an onboarding/KYC case",
    description=(
        "Creates a case in `DRAFT`, together with its person profile and KYC detail, "
        "and records an audit event. Requires an `Idempotency-Key` header: a replay "
        "of the same key — or of the same `external_case_id` — returns `200` with the "
        "originally created case rather than creating a second one."
    ),
    responses={
        201: {"model": CaseResponse, "description": "Case created"},
        200: {"model": CaseResponse, "description": "Idempotent replay — the existing case"},
        400: {"description": "Missing Idempotency-Key header"},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def create_case(
    body: CreateCaseRequest,
    response: Response,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CaseResponse:
    if not idempotency_key:
        raise AnerBaseException(
            detail="Idempotency-Key header is required for case creation",
            error_code="MISSING_IDEMPOTENCY_KEY",
            status_code=400,
        )
    case, created = await CaseService(db).create_case(
        body, idempotency_key=idempotency_key, actor_id=current_user.id
    )
    if not created:
        response.status_code = 200
    return case


@router.get(
    "/cases/{case_id}",
    response_model=CaseResponse,
    summary="Read a case",
    responses={
        200: {"model": CaseResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Case not found"},
    },
)
async def get_case(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> CaseResponse:
    return await CaseService(db).get_case(case_id)


@router.patch(
    "/cases/{case_id}",
    response_model=CaseResponse,
    summary="Update a case's routing attributes",
    description=(
        "Updates the opaque routing attributes (`cell_id`, `product_context`, "
        "`policy_id`) and records an audit event. Case **state** is not updatable "
        "here — it is owned by the case state machine."
    ),
    responses={
        200: {"model": CaseResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Case not found"},
        422: {"description": "Invalid request body"},
    },
)
async def update_case(
    case_id: uuid.UUID,
    body: UpdateCaseRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> CaseResponse:
    return await CaseService(db).update_case(case_id, body, actor_id=current_user.id)


@router.post(
    "/cases/{case_id}/transitions",
    response_model=CaseResponse,
    summary="Transition a case to a new state",
    description=(
        "The only way case state ever changes. Validates the move against "
        "the legal-transition table, then records a `case_state_transition` row and an "
        "audit event carrying the actor, reason, timestamp, previous state, next state, "
        "source and correlation id. An illegal transition returns `409` and leaves the "
        "case untouched."
    ),
    responses={
        200: {"model": CaseResponse, "description": "Case transitioned"},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Case not found"},
        409: {"description": "Illegal state transition — the case is not mutated"},
        422: {
            "description": (
                "Unknown state, or a transition source only the platform may claim "
                "(SYSTEM / PROVIDER_CALLBACK)"
            )
        },
    },
)
async def transition_case(
    case_id: uuid.UUID,
    body: CaseTransitionRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> CaseResponse:
    return await CaseService(db).transition(case_id, body, actor_id=current_user.id)


@router.get(
    "/cases/{case_id}/transitions",
    response_model=CaseTransitionListResponse,
    summary="Read a case's state history",
    description=(
        "The append-only history of every state change this case has undergone, "
        "oldest first. Rows are immutable: a transition that turned out to be wrong "
        "is corrected by appending its reverse."
    ),
    responses={
        200: {"model": CaseTransitionListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Case not found"},
    },
)
async def list_case_transitions(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> CaseTransitionListResponse:
    return await CaseService(db).list_transitions(case_id)


# ── Onboarding foundation (pre-backlog; retired later) ───────────────────────


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a customer for onboarding",
    description=(
        "Creates an onboarding customer, provisions a provider applicant "
        "(Sumsub sandbox, or the in-process mock when SUMSUB_ENABLED is false), "
        "records an audit event, and publishes a `customer.registered` event. "
        "Returns the customer id, provider applicant id, and onboarding status."
    ),
    responses={
        201: {"model": RegisterResponse, "description": "Customer registered"},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        409: {"description": "A customer with this email is already onboarding"},
        502: {"description": "Identity provider error"},
    },
)
async def register_customer(
    body: RegisterRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    return await OnboardingService(db).register(body, actor_id=current_user.id)


@router.get(
    "/{customer_id}/sdk-token",
    response_model=SdkTokenResponse,
    summary="Issue a provider SDK access token",
    description=(
        "Mints a short-lived provider access token the client SDK uses to launch "
        "the verification flow for this customer's applicant."
    ),
    responses={
        200: {"model": SdkTokenResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Onboarding customer not found"},
        502: {"description": "Identity provider error"},
    },
)
async def get_sdk_token(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> SdkTokenResponse:
    return await OnboardingService(db).generate_sdk_token(customer_id)


@router.get(
    "/{customer_id}/status",
    response_model=OnboardingStatusResponse,
    summary="Read a customer's current onboarding/verification status",
    description=(
        "Lightweight, read-only status projection used for polling after a "
        "verification is submitted (e.g. by the developer test harness). Returns "
        "the customer's onboarding status plus the latest verification record's "
        "review status/answer. Never mutates state and makes no provider calls."
    ),
    responses={
        200: {"model": OnboardingStatusResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Onboarding customer not found"},
    },
)
async def get_onboarding_status(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatusResponse:
    return await OnboardingService(db).get_status(customer_id)


@router.post(
    "/webhooks/sumsub",
    response_model=WebhookAck,
    summary="Inbound Sumsub verification webhook",
    description=(
        "Public endpoint (no bearer auth) authenticated by the HMAC signature in "
        "the `X-Payload-Digest` header. Verifies the signature, persists the event, "
        "deduplicates redeliveries, writes an immutable verification record, "
        "transitions the customer's onboarding status, records an audit event, and "
        "publishes `customer.verification.updated`."
    ),
    responses={
        200: {"model": WebhookAck, "description": "Processed (or duplicate no-op)"},
        400: {"description": "Malformed webhook body"},
        401: {"description": "Invalid webhook signature"},
    },
)
async def sumsub_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_payload_digest: Annotated[str | None, Header(alias="X-Payload-Digest")] = None,
    x_payload_digest_alg: Annotated[str | None, Header(alias="X-Payload-Digest-Alg")] = None,
) -> WebhookAck:
    raw_body = await request.body()
    return await WebhookService(db).process_sumsub_webhook(
        raw_body=raw_body,
        signature=x_payload_digest,
        alg=x_payload_digest_alg,
    )


# ── EXP-2: generalized verification results ──────────────────────────────────
# One extensible mechanism to trigger and record any verification check (KYC
# for a director, a bank-account check for an exporter, ...) — see
# `domain.workflow_dependencies.VerificationAdapter` and
# `application.verification_service.VerificationService`.
#
# Owner: Developer 4B (verification-and-screening.md §7). Roles unchanged: writes COMPLIANCE/ADMIN,
# reads OPERATIONS/COMPLIANCE/ADMIN; DEVELOPER is refused (D8, lead: no widening). The
# actor and reviewer always come from the session, never the body.

#: Who may record a result or review one. The same tuple gates the two write routes
#: (`_VERIFICATION_DECIDER`) and answers the served capabilities, so the two cannot
#: drift.
_VERIFICATION_DECISION_ROLES = (UserRole.COMPLIANCE, UserRole.ADMIN)
_VERIFICATION_DECIDER = require_role(*_VERIFICATION_DECISION_ROLES)


async def _initial_cycle_ids(db: AsyncSession, views) -> dict[uuid.UUID, uuid.UUID]:
    """Each company's cycle-1 id, for the companies these results are about — so a
    legacy result (no cycle) is served as cycle 1 (Developer 1, P2-3a; company-keyed
    since P4-5, so a mapped deal-buyer result reads in its company's cycle 1)."""
    companies = {
        view.result.subject_company
        for view in views
        if view.result.subject_company is not None and view.result.cycle_id is None
    }
    initial: dict[uuid.UUID, uuid.UUID] = {}
    cycles = CheckCycleRepository(db)
    for company_id in companies:
        first = next(iter(await cycles.list_for_company(company_id)), None)
        if first is not None:
            initial[company_id] = first.id
    return initial


def _result_response(view, viewer: User, names, initial: dict[uuid.UUID, uuid.UUID]):
    cycle_id = view.result.cycle_id
    if cycle_id is None and view.result.subject_company is not None:
        cycle_id = initial.get(view.result.subject_company)
    return VerificationResultResponse.from_view(view, viewer, names, cycle_id=cycle_id)


@router.post(
    "/verifications",
    response_model=VerificationResultResponse,
    status_code=201,
    summary="Trigger a verification check",
    description=(
        "Resolves `provider` (default `manual`) to a `VerificationAdapter` via the "
        "EXP-2 registry, runs the check, and persists the outcome as a new "
        "`VerificationResult`. The exact same call handles every `verification_type`/"
        "`entity_type` combination — there is no per-type branching. Only "
        "`provider=manual` is accepted here. An `EXPORTER` subject must be an existing "
        "company and a `BUYER` subject an existing deal buyer (`deal_buyer.id`) whose "
        "deal is not `HANDED_OVER` or `WITHDRAWN`. A manual `PASSED` needs evidence (a "
        "note or at least one reference); a manual `PENDING` is refused. `document` "
        "evidence must belong to the subject and be `AVAILABLE` (scanned clean); `url` "
        "evidence must be an `http://` or `https://` link."
    ),
    responses={
        201: {"model": VerificationResultResponse, "description": "Verification result recorded"},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Subject (company or deal buyer) not found"},
        409: {"description": "The buyer's deal is HANDED_OVER or WITHDRAWN"},
        422: {
            "description": (
                "Unknown/disabled provider, an invalid payload for it, missing or "
                "foreign evidence, a `document` that is not `AVAILABLE`, a `url` that "
                "is not http(s), or an uninterpretable check/subject pair"
            )
        },
    },
)
async def trigger_verification(
    body: TriggerVerificationRequest,
    current_user: Annotated[User, Depends(_VERIFICATION_DECIDER)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    service = VerificationService(db)
    result = await service.trigger_verification(
        body.verification_type,
        body.entity_type,
        body.entity_reference,
        provider=body.provider,
        payload=body.payload,
        actor_id=current_user.id,
        evidence=body.to_evidence(),
    )
    view = await service.get_result_view(result.id)
    names = await actor_names(db, current_user, reviewer_ids([view]))
    return _result_response(view, current_user, names, await _initial_cycle_ids(db, [view]))


@router.get(
    "/verifications/{verification_result_id}",
    response_model=VerificationResultResponse,
    summary="Read one verification result",
    responses={
        200: {"model": VerificationResultResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Verification result not found"},
    },
)
async def get_verification_result(
    verification_result_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    try:
        view = await VerificationService(db).get_result_view(verification_result_id)
    except NotFoundError:
        raise VerificationResultNotFoundError(
            f"Verification result '{verification_result_id}' not found"
        ) from None
    names = await actor_names(db, current_user, reviewer_ids([view]))
    return _result_response(view, current_user, names, await _initial_cycle_ids(db, [view]))


@router.get(
    "/verifications",
    response_model=VerificationResultListResponse,
    summary="List verification results for an entity",
    description=(
        "Every check ever run against one exporter/buyer/director/invoice/vessel/shipment, "
        "newest first, each with its review chain; for a buyer, pass the `deal_buyer.id`. "
        "`capabilities` says whether the caller may record or review a result; no new "
        "result may be recorded on a buyer whose deal is `HANDED_OVER` or `WITHDRAWN`."
    ),
    responses={
        200: {"model": VerificationResultListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_verification_results(
    entity_type: VerificationEntityType,
    entity_reference: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultListResponse:
    service = VerificationService(db)
    results = await service.list_verification_results(entity_type, entity_reference)
    views = await service.views_for(results)
    names = await actor_names(db, current_user, reviewer_ids(views))
    may_decide = current_user.role in _VERIFICATION_DECISION_ROLES
    # D17: no new check on a buyer of a closed deal — served as a capability too, so
    # the screen never offers a form the server would refuse. Reviews stay open.
    may_record = may_decide and await service.accepts_new_check(entity_type, entity_reference)
    initial = await _initial_cycle_ids(db, views)
    return VerificationResultListResponse(
        entity_type=entity_type,
        entity_reference=entity_reference,
        results=[_result_response(v, current_user, names, initial) for v in views],
        total=len(views),
        capabilities=VerificationCapabilities(
            can_record_result=may_record, can_review=may_decide
        ),
    )


@router.post(
    "/verifications/{verification_result_id}/review",
    response_model=VerificationResultResponse,
    summary="Record a compliance reviewer's decision",
    description=(
        "Adds a review; nothing is ever edited. A result's first review omits "
        "`supersedes_review_id`. A later review must name the result's current review "
        "there and give a `note` — otherwise `409`, so a reviewer never overrules a "
        "review they have not seen. A `PENDING` result cannot be reviewed (`422`). The "
        "reviewer is the signed-in user. The response carries the whole review chain."
    ),
    responses={
        200: {"model": VerificationResultResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Verification result not found"},
        409: {
            "description": (
                "`supersedes_review_id` is not the current review, or the result has a "
                "legacy review with no review record to supersede"
            )
        },
        422: {"description": "Result still PENDING, or a superseding review without a note"},
    },
)
async def record_verification_review(
    verification_result_id: uuid.UUID,
    body: RecordReviewRequest,
    current_user: Annotated[User, Depends(_VERIFICATION_DECIDER)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    service = VerificationService(db)
    await service.record_review(
        verification_result_id,
        # The reviewer is the authenticated caller, never a client-supplied
        # value — same identifier the screening review stores as `actor_id`.
        reviewed_by=str(current_user.id),
        review_status=body.review_status,
        note=body.note,
        supersedes_review_id=body.supersedes_review_id,
    )
    view = await service.get_result_view(verification_result_id)
    names = await actor_names(db, current_user, reviewer_ids([view]))
    return _result_response(view, current_user, names, await _initial_cycle_ids(db, [view]))
