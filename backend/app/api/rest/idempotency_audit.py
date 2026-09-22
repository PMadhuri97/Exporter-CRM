"""Internal investigation endpoints over the idempotency registry.

Consumed by the operations and compliance teams and by the case management
console. Everything here is a query: no verb other than GET is defined on this
router, so an attempted write is a 405 from the framework before it ever reaches
a permission check or a session.

This is the composition point for the interface. Each half comes from the module
that owns it and reads under that module's own credentials — the registry and
the ledger under ``ledger_ro``, settlements under ``settlement_ro``, the audit log
under ``audit_ro`` — because
BUILD.md #15 gives a module one read-only role and forbids sharing it. Assembly
belongs here rather than in the platform service, which may not import a module
at all (ADR 0001 rule 1).

Duplicate detections and violations are served by separate endpoints from separate
tables and must never be conflated: a detection is the idempotency control working,
a violation is the control failing. Nothing here returns both.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import AuditViolationSource
from app.modules.ledger import LedgerTransactionKeyResolver
from app.modules.settlement import SettlementCrossReference
from app.platform.authentication.models import User, UserRole
from app.platform.authorization import require_role
from app.platform.database.services import (
    get_audit_ro_db,
    get_ro_db,
    get_settlement_ro_db,
)
from app.platform.idempotency.audit_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditRecord,
    AuditRecordPage,
    IdempotencyAuditRepository,
)
from app.platform.idempotency.audit_service import IdempotencyAuditQueryService
from app.platform.idempotency.detection_repository import (
    DetectionPage,
    DetectionRecord,
    DuplicateDetectionRepository,
)
from app.platform.idempotency.exceptions import IdempotencyKeyNotFoundError
from app.shared.contracts.idempotency import ViolationPage, ViolationRecord
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)
router = APIRouter()

# Investigation is an operations and compliance activity. API_USER is excluded:
# response_cache can hold a full cached response body belonging to another caller.
_INVESTIGATOR = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


class AuditRecordResponse(BaseModel):
    """One registry record, wherever it currently lives."""

    id: uuid.UUID
    key_value: str
    scope_id: str
    key_type: str
    operation_type: str
    status: str
    response_cache: dict[str, Any] | None
    response_reference: str | None
    first_seen_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    correlation_id: str | None
    created_by: str | None
    record_metadata: dict[str, Any] | None
    source: str = Field(
        description="Which storage tier answered: 'hot' or 'archive'. Informational — "
        "every query spans both, so a caller never has to choose."
    )
    archived_at: datetime | None


class AuditRecordPageResponse(BaseModel):
    """A page of records. ``total`` counts every match, independent of paging."""

    total: int
    limit: int
    offset: int
    records: list[AuditRecordResponse]


def _record(record: AuditRecord) -> AuditRecordResponse:
    return AuditRecordResponse(
        id=record.id,
        key_value=record.key_value,
        scope_id=record.scope_id,
        key_type=record.key_type.value,
        operation_type=record.operation_type,
        status=record.status.value,
        response_cache=record.response_cache,
        response_reference=record.response_reference,
        first_seen_at=record.first_seen_at,
        completed_at=record.completed_at,
        expires_at=record.expires_at,
        correlation_id=record.correlation_id,
        created_by=record.created_by,
        record_metadata=record.record_metadata,
        source=record.source.value,
        archived_at=record.archived_at,
    )


def _page(page: AuditRecordPage) -> AuditRecordPageResponse:
    return AuditRecordPageResponse(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        records=[_record(r) for r in page.records],
    )


class DuplicateDetectionResponse(BaseModel):
    """One duplicate that was recognised and short-circuited.

    A detection, not a violation. The guarded operation did not run a second
    time — this is the idempotency control working, recorded so the caller
    responsible for the retries can be identified.
    """

    id: uuid.UUID
    idempotency_key: str
    scope_id: str
    operation_type: str
    original_request_ref: uuid.UUID
    original_executed_at: datetime
    detected_at: datetime
    caller_identity: str | None
    correlation_id: str | None
    time_since_original_ms: int = Field(
        description="Gap between the original execution and this duplicate. A few "
        "hundred milliseconds is a network retry; hours is a caller replaying "
        "stale state. The distinction is the diagnostic value."
    )
    returned_result_ref: uuid.UUID | None


class DuplicateDetectionPageResponse(BaseModel):
    """A page of detections. ``total`` counts every match, independent of paging."""

    total: int
    limit: int
    offset: int
    detections: list[DuplicateDetectionResponse]


def _detection(record: DetectionRecord) -> DuplicateDetectionResponse:
    return DuplicateDetectionResponse(
        id=record.id,
        idempotency_key=record.idempotency_key,
        scope_id=record.scope_id,
        operation_type=record.operation_type,
        original_request_ref=record.original_request_ref,
        original_executed_at=record.original_executed_at,
        detected_at=record.detected_at,
        caller_identity=record.caller_identity,
        correlation_id=record.correlation_id,
        time_since_original_ms=record.time_since_original_ms,
        returned_result_ref=record.returned_result_ref,
    )


def _detection_page(page: DetectionPage) -> DuplicateDetectionPageResponse:
    return DuplicateDetectionPageResponse(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        detections=[_detection(d) for d in page.detections],
    )


class ViolationResponse(BaseModel):
    """One recorded idempotency failure: an operation that executed more than once.

    Not a duplicate detection. A detection is the control working; this is the
    control failing, with real duplicate execution behind it.
    """

    id: uuid.UUID
    detected_at: datetime
    key_value: str | None
    scope: str | None = Field(
        description="The detector's scope: a customer, entity or rail identifier. "
        "Not a registry scope_id, and does not join to idempotency_record."
    )
    operation_type: str | None = Field(
        description="The detector's category, e.g. settlement_creation, not the "
        "registry's route-template operation_type."
    )
    execution_count: int | None = Field(
        description="How many times the operation actually executed. Anything above "
        "one is the failure."
    )
    involved_object_ids: list[str] = Field(
        description="The ledger transaction, settlement or rail status IDs involved."
    )
    correlation_id: str | None = Field(
        description="The original correlation ID, for end-to-end tracing."
    )
    violation_hash: str | None = Field(
        description="Stable per incident. The detector re-records an unresolved "
        "violation on every scheduled run, so records sharing a hash are one incident."
    )
    already_alerted: bool | None = Field(
        description="True on the records that did not page the SRE on-call because "
        "the incident had already been alerted."
    )


class ViolationPageResponse(BaseModel):
    """A page of violations, newest first. ``total`` counts every match."""

    total: int
    limit: int
    offset: int
    violations: list[ViolationResponse]


def _violation(record: ViolationRecord) -> ViolationResponse:
    return ViolationResponse(
        id=record.id,
        detected_at=record.detected_at,
        key_value=record.key_value,
        scope=record.scope,
        operation_type=record.operation_type,
        execution_count=record.execution_count,
        involved_object_ids=record.involved_object_ids,
        correlation_id=record.correlation_id,
        violation_hash=record.violation_hash,
        already_alerted=record.already_alerted,
    )


def _violation_page(page: ViolationPage) -> ViolationPageResponse:
    return ViolationPageResponse(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        violations=[_violation(v) for v in page.violations],
    )


def audit_query_service(
    ledger_db: Annotated[AsyncSession, Depends(get_ro_db)],
    settlement_db: Annotated[AsyncSession, Depends(get_settlement_ro_db)],
    audit_db: Annotated[AsyncSession, Depends(get_audit_ro_db)],
) -> IdempotencyAuditQueryService:
    """Assemble the interface from one read-only session per schema it reads.

    The registry, its archive, ledger_transaction and duplicate_detection all
    live in the ledger schema and share one session. Settlements and the audit
    log each get their own, under the module's own read-only role: BUILD.md #15
    gives a module one such role and forbids sharing it.

    Sessions open no connection until first used, so a request that never reads
    the audit log never connects as audit_ro.
    """
    return IdempotencyAuditQueryService(
        IdempotencyAuditRepository(ledger_db),
        settlements=SettlementCrossReference(settlement_db),
        ledger_transactions=LedgerTransactionKeyResolver(ledger_db),
        detections=DuplicateDetectionRepository(ledger_db),
        violations=AuditViolationSource(audit_db),
    )


Service = Annotated[IdempotencyAuditQueryService, Depends(audit_query_service)]
Investigator = Annotated[User, Depends(_INVESTIGATOR)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/records",
    response_model=AuditRecordResponse,
    summary="Get one idempotency record by key and scope",
    description=(
        "Returns the full record, including the cached response body. Spans the "
        "hot registry and the archive, so an aged key still resolves.\n\n"
        "Both parameters are query parameters rather than path segments because "
        "scope_id is not URL-safe: for customer keys it is the HTTP route "
        "template, which contains slashes and spaces.\n\n"
        "Where a key has been registered more than once in the same scope — an "
        "expired generation followed by a reuse — the most recent registration "
        "is returned."
    ),
    responses={
        404: {"description": "No record for this key and scope"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def get_record(
    current_user: Investigator,
    service: Service,
    key_value: Annotated[str, Query(min_length=1, max_length=256)],
    scope_id: Annotated[str, Query(min_length=1, max_length=255)],
) -> AuditRecordResponse:
    try:
        record = await service.get_record(key_value, scope_id)
    except IdempotencyKeyNotFoundError as exc:
        # The domain exception is not an AnerBaseException, so it would other-
        # wise surface as a 500. Translating it here is the delivery layer's job.
        raise NotFoundError(str(exc)) from exc
    return _record(record)


@router.get(
    "/settlements/{settlement_id}/records",
    response_model=AuditRecordPageResponse,
    summary="List every idempotency record belonging to a settlement",
    description=(
        "Reconstructs what a settlement registered, oldest first, across the hot "
        "registry and the archive.\n\n"
        "A settlement's records are not all reachable the same way. Rail "
        "references and internal derived keys are found through scopes derived "
        "from the settlement and its legs; the customer key is scoped to an HTTP "
        "route template that names no settlement and is found through the key "
        "itself. Both are resolved and matched in one query.\n\n"
        "Also serves as the settlement side of the cross-reference lookup: "
        "omit the date range to get everything."
    ),
    responses={403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}},
)
async def list_settlement_records(
    settlement_id: uuid.UUID,
    current_user: Investigator,
    service: Service,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> AuditRecordPageResponse:
    return _page(
        await service.list_settlement_records(
            settlement_id, since=since, until=until, limit=limit, offset=offset
        )
    )


@router.get(
    "/duplicates",
    response_model=DuplicateDetectionPageResponse,
    summary="List duplicate detections for an operation type",
    description=(
        "Individual duplicate detections for one operation type over a detection "
        "time window, most recent first. Used for pattern analysis: an operation "
        "type generating many duplicates means something upstream is retrying too "
        "aggressively, and these rows name the caller.\n\n"
        "**These are not violations.** Each row is a request that reused an "
        "idempotency key and was correctly prevented from executing again — the "
        "control working as designed. Violations are actual idempotency failures "
        "where duplicate execution occurred despite the controls, and are served "
        "independently from a different source.\n\n"
        "Read from the persisted duplicate_detection log, not from the Prometheus "
        "counter. That counter carries no key value by design — an unbounded label "
        "would be a cardinality incident — so it can say how many duplicates an "
        "operation saw and never which.\n\n"
        "`since` and `until` bound detected_at, so each detection is filtered on "
        "when it was caught rather than on when its original ran."
    ),
    responses={403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}},
)
async def list_duplicate_detections(
    current_user: Investigator,
    service: Service,
    operation_type: Annotated[str, Query(min_length=1, max_length=100)],
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> DuplicateDetectionPageResponse:
    return _detection_page(
        await service.list_duplicate_detections(
            operation_type, since=since, until=until, limit=limit, offset=offset
        )
    )


@router.get(
    "/violations",
    response_model=ViolationPageResponse,
    summary="List recorded idempotency violations",
    description=(
        "Every violation the detection system has recorded, most recent first, "
        "paginated.\n\n"
        "**These are idempotency failures**: duplicate execution that occurred "
        "despite the idempotency controls, such as a ledger transaction posted twice, "
        "two live settlements for one customer key, or a rail reference confirmed "
        "twice by the partner. They are served independently of duplicate "
        "detections, which are the opposite event: a request that was correctly "
        "short-circuited.\n\n"
        "Every record is returned, not one per incident. The scheduled check "
        "re-records a violation on each run that still finds it, so an unresolved "
        "incident recurs with the same `violation_hash`. Group by that field for one "
        "row per incident; `already_alerted` marks the records that did not page.\n\n"
        "`scope` and `operation_type` use the detector's vocabulary (a customer, "
        "entity or rail identifier; a category such as `settlement_creation`), not "
        "the registry's, so they do not join to `/records` directly."
    ),
    responses={403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}},
)
async def list_violations(
    current_user: Investigator,
    service: Service,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> ViolationPageResponse:
    return _violation_page(await service.list_violations(limit=limit, offset=offset))


@router.get(
    "/ledger-transactions/{transaction_id}/records",
    response_model=AuditRecordPageResponse,
    summary="List the idempotency records that guarded a ledger transaction",
    description=(
        "The reverse lookup for a suspected duplicate: given a transaction, find "
        "its idempotency key history.\n\n"
        "Returns a page rather than a single record, and that is not a "
        "formality. The link is the key value, which carries no scope, so one "
        "transaction's key can legitimately match records in several scopes — "
        "which is precisely the shape a duplicate has. An empty page means the "
        "transaction registered no key, which is a normal state, not an error."
    ),
    responses={403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"}},
)
async def list_ledger_transaction_records(
    transaction_id: uuid.UUID,
    current_user: Investigator,
    service: Service,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> AuditRecordPageResponse:
    return _page(
        await service.list_ledger_transaction_records(
            transaction_id, limit=limit, offset=offset
        )
    )
