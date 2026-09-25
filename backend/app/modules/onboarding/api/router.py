import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.engagement_router import router as engagement_router
from app.modules.onboarding.api.exporter_router import router as exporter_router
from app.modules.onboarding.api.history_router import router as history_router
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
    VerificationResultListResponse,
    VerificationResultResponse,
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
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.exceptions import VerificationResultNotFoundError
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared.exceptions import AnerBaseException

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

# Shared CRM history log (L1-11) — Developer 1's, in its own file for the same
# reason the Exporter CRM routes are in theirs, and included here so it
# inherits the "/onboarding" mount prefix. It carries its own full paths
# (/exporters/{id}/history, /deals/{id}/history) rather than a router prefix,
# because the deal route is not under /exporters.
router.include_router(history_router)


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


@router.post(
    "/verifications",
    response_model=VerificationResultResponse,
    status_code=201,
    summary="Trigger a verification check",
    description=(
        "Resolves `provider` (default `manual`) to a `VerificationAdapter` via the "
        "EXP-2 registry, runs the check, and persists the outcome as a new "
        "`VerificationResult`. The exact same call handles every `verification_type`/"
        "`entity_type` combination — there is no per-type branching."
    ),
    responses={
        201: {"model": VerificationResultResponse, "description": "Verification result recorded"},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        422: {"description": "Unknown/disabled provider, or an invalid payload for it"},
    },
)
async def trigger_verification(
    body: TriggerVerificationRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    result = await VerificationService(db).trigger_verification(
        body.verification_type,
        body.entity_type,
        body.entity_reference,
        provider=body.provider,
        payload=body.payload,
        actor_id=current_user.id,
    )
    return VerificationResultResponse.model_validate(result)


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
    result = await db.get(VerificationResult, verification_result_id)
    if result is None:
        raise VerificationResultNotFoundError(
            f"Verification result '{verification_result_id}' not found"
        )
    return VerificationResultResponse.model_validate(result)


@router.get(
    "/verifications",
    response_model=VerificationResultListResponse,
    summary="List verification results for an entity",
    description="Every check ever run against one exporter/buyer/director/invoice/vessel/shipment.",
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
    results = await VerificationService(db).list_verification_results(entity_type, entity_reference)
    return VerificationResultListResponse(
        entity_type=entity_type,
        entity_reference=entity_reference,
        results=[VerificationResultResponse.model_validate(r) for r in results],
        total=len(results),
    )


@router.post(
    "/verifications/{verification_result_id}/review",
    response_model=VerificationResultResponse,
    summary="Record a compliance reviewer's decision",
    description=(
        "Sets `reviewed_by`/`review_status`, which are immutable once set — a second "
        "review attempt on the same result returns `409` rather than overwriting it."
    ),
    responses={
        200: {"model": VerificationResultResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Verification result not found"},
        409: {"description": "Already reviewed"},
    },
)
async def record_verification_review(
    verification_result_id: uuid.UUID,
    body: RecordReviewRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    result = await VerificationService(db).record_review(
        verification_result_id,
        # The reviewer is the authenticated caller, never a client-supplied
        # value — same identifier the screening review stores as `actor_id`.
        reviewed_by=str(current_user.id),
        review_status=body.review_status,
    )
    return VerificationResultResponse.model_validate(result)
