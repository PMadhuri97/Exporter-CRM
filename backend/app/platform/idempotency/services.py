"""Validation services for idempotency key formats and deterministic key generation."""

import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.platform.database.services import AsyncSessionLocal
from app.platform.idempotency.config import compute_expires_at
from app.platform.idempotency.detection_models import DuplicateDetection
from app.platform.idempotency.exceptions import (
    DuplicateOperationConflictError,
    DuplicateOperationFailedError,
    IdempotencyKeyNotFoundError,
    InvalidKeyFormatError,
    InvalidStateTransitionError,
    RegistrationRaceError,
    ResponseCacheExceededError,
)
from app.platform.idempotency.models import (
    LIVE_RECORD_PREDICATE_SQL,
    DuplicateContractResult,
    DuplicateHandlingAction,
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
    KeyValidationResult,
    RegistrationResult,
    RegistrationResultType,
    ValidationReason,
)
from app.platform.idempotency.ports import IdempotencyRegistrationPort
from app.platform.idempotency.utilities import (
    KNOWN_RAIL_CODES,
    MAX_CUSTOMER_KEY_LENGTH,
    MAX_INTERNAL_KEY_LENGTH,
    MAX_RAIL_REF_LENGTH,
    RAIL_REF_PREFIX,
)
from app.platform.observability.metrics import (
    IDEMPOTENCY_REGISTRY_SIZE,
    observe_idempotency_registration_latency,
    record_idempotency_duplicate,
    record_idempotency_registration,
)

logger = structlog.get_logger(__name__)

MAX_RESPONSE_CACHE_BYTES = 65536


def validate_response_cache_payload(payload: dict | None) -> None:
    """Validate that response cache payload does not exceed 64 KB limit."""
    if payload is None:
        return
    try:
        serialized = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Response cache payload is not JSON serializable: {exc}") from exc

    size_bytes = len(serialized.encode("utf-8"))
    if size_bytes > MAX_RESPONSE_CACHE_BYTES:
        raise ResponseCacheExceededError(size_bytes, MAX_RESPONSE_CACHE_BYTES)


def evaluate_duplicate_contract(
    registration_result: RegistrationResult,
    raise_on_conflict: bool = False,
) -> DuplicateContractResult:
    """Evaluate a duplicate registration result against duplicate handling contract rules.

    Determines whether the caller must return 409 Conflict (active), return cached success
    payload (completed), return cached failure (failed), or re-execute as new (expired).

    If raise_on_conflict is True:
    - Raises DuplicateOperationConflictError for ACTIVE keys.
    - Raises DuplicateOperationFailedError for FAILED keys.
    """
    if registration_result.result != RegistrationResultType.DUPLICATE or registration_result.record is None:
        raise ValueError("evaluate_duplicate_contract requires a DUPLICATE registration result with a record")

    record = registration_result.record
    now = datetime.now(UTC)

    # Check if record is expired
    if (record.expires_at is not None and record.expires_at <= now) or record.status == IdempotencyStatus.EXPIRED:
        return DuplicateContractResult(
            action=DuplicateHandlingAction.EXECUTE_NEW,
            status=IdempotencyStatus.EXPIRED,
            message="Key has expired and should be treated as a new operation.",
        )

    if record.status == IdempotencyStatus.ACTIVE:
        if raise_on_conflict:
            raise DuplicateOperationConflictError(record.key_value, record.scope_id)
        return DuplicateContractResult(
            action=DuplicateHandlingAction.CONFLICT_ACTIVE,
            status=IdempotencyStatus.ACTIVE,
            message="Operation with this key is currently active and in progress.",
        )

    if record.status == IdempotencyStatus.COMPLETED:
        return DuplicateContractResult(
            action=DuplicateHandlingAction.RETURN_CACHED_SUCCESS,
            status=IdempotencyStatus.COMPLETED,
            response_cache=record.response_cache,
            message="Operation previously completed; returning cached response.",
        )

    if record.status == IdempotencyStatus.FAILED:
        if raise_on_conflict:
            raise DuplicateOperationFailedError(record.key_value, record.scope_id, record.response_cache)
        return DuplicateContractResult(
            action=DuplicateHandlingAction.RETURN_CACHED_FAILURE,
            status=IdempotencyStatus.FAILED,
            response_cache=record.response_cache,
            message="Operation previously failed; caller must generate a new key to retry.",
        )

    raise ValueError(f"Unknown idempotency status '{record.status}'")


def handle_duplicate_contract(registration_result: RegistrationResult) -> DuplicateContractResult:
    """Evaluate duplicate contract and enforce raising DuplicateOperationConflictError/FailedError."""
    return evaluate_duplicate_contract(registration_result, raise_on_conflict=True)


# UUID v4 canonical regex pattern (case-insensitive)
UUID_V4_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

# Step identifier regex pattern (only lowercase letters and underscores)
STEP_IDENTIFIER_PATTERN = re.compile(r"^[a-z_]+$")

# Rail reference structure: ANER-{settlement_id_short}-{leg_sequence}-{rail_code}
RAIL_REF_PATTERN = re.compile(r"^ANER-([a-zA-Z0-9]+)-([a-zA-Z0-9_]+)-([a-zA-Z0-9_]+)$")

# Insert attempts before registration gives up. Two, because the only condition that makes
# a re-attempt sensible — the conflicting record expiring between the INSERT and the
# follow-up SELECT — frees the key, so the retry conflicts with nothing. A third attempt
# would only mask a different problem.
_REGISTRATION_ATTEMPTS = 2


def _is_valid_uuid_v4(key: str) -> bool:
    """Check if a key is a valid UUID v4 canonical string."""
    if not UUID_V4_PATTERN.match(key):
        return False
    return uuid.UUID(key).version == 4


def validate_customer_key(key: str) -> KeyValidationResult:
    """Validate that the customer key is a valid UUID v4 string within 64 characters."""
    if not key or not key.strip():
        return KeyValidationResult.invalid(
            ValidationReason.EMPTY_KEY, "Customer key must not be empty"
        )

    if len(key) > MAX_CUSTOMER_KEY_LENGTH:
        return KeyValidationResult.invalid(
            ValidationReason.EXCEEDS_MAX_LENGTH,
            f"Customer key length {len(key)} exceeds maximum allowed {MAX_CUSTOMER_KEY_LENGTH}",
        )

    if not _is_valid_uuid_v4(key):
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_UUID_V4,
            "Customer key must be a valid UUID v4 string format",
        )

    return KeyValidationResult.valid()


def validate_internal_derived_key(key: str) -> KeyValidationResult:
    """Validate an internal derived key ({parent_key}:{step_identifier}).

    Parent key must be a valid UUID v4, step identifier must be lowercase letters & underscores,
    and total length must be <= 256 chars.
    """
    if not key or not key.strip():
        return KeyValidationResult.invalid(
            ValidationReason.EMPTY_KEY, "Internal derived key must not be empty"
        )

    if len(key) > MAX_INTERNAL_KEY_LENGTH:
        return KeyValidationResult.invalid(
            ValidationReason.EXCEEDS_MAX_LENGTH,
            f"Internal derived key length {len(key)} exceeds maximum allowed {MAX_INTERNAL_KEY_LENGTH}",
        )

    parts = key.split(":")
    if len(parts) != 2 or not parts[0]:
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_FORMAT,
            "Internal derived key must strictly follow the format '{parent_key}:{step_identifier}'",
        )

    parent_key, step_identifier = parts[0], parts[1]

    if not _is_valid_uuid_v4(parent_key):
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_UUID_V4,
            "Parent key portion of internal derived key must be a valid UUID v4 string",
        )

    if not STEP_IDENTIFIER_PATTERN.match(step_identifier):
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_STEP_IDENTIFIER,
            "Step identifier must contain only lowercase letters and underscores",
        )

    return KeyValidationResult.valid()


def validate_rail_reference(key: str) -> KeyValidationResult:
    """Validate a rail reference key (ANER-{settlement_id_short}-{leg_sequence}-{rail_code}).

    Rail code must be a known identifier and total length must be <= 64 chars.
    """
    if not key or not key.strip():
        return KeyValidationResult.invalid(
            ValidationReason.EMPTY_KEY, "Rail reference must not be empty"
        )

    if len(key) > MAX_RAIL_REF_LENGTH:
        return KeyValidationResult.invalid(
            ValidationReason.EXCEEDS_MAX_LENGTH,
            f"Rail reference length {len(key)} exceeds maximum allowed {MAX_RAIL_REF_LENGTH}",
        )

    match = RAIL_REF_PATTERN.match(key)
    if not match:
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_FORMAT,
            f"Rail reference must follow format '{RAIL_REF_PREFIX}-{{settlement_id_short}}-{{leg_sequence}}-{{rail_code}}'",
        )

    _, _, rail_code = match.groups()
    if rail_code.upper() not in KNOWN_RAIL_CODES:
        return KeyValidationResult.invalid(
            ValidationReason.UNKNOWN_RAIL_CODE,
            f"Rail code '{rail_code}' is not a recognized payment rail identifier",
        )

    return KeyValidationResult.valid()


def derive_internal_key(parent_key: str, step_identifier: str) -> str:
    """Generate a valid internal derived key from parent key and step identifier deterministically.

    Raises ValueError if parent_key or step_identifier are invalid.
    """
    candidate = f"{parent_key}:{step_identifier}"
    result = validate_internal_derived_key(candidate)
    if not result.is_valid:
        raise ValueError(f"Cannot derive internal key: {result.message}")
    return candidate


def generate_rail_reference(settlement_id: str, leg_sequence: Any, rail_code: str) -> str:
    """Generate a valid rail reference key deterministically.

    Format: ANER-{settlement_id_short}-{leg_sequence}-{rail_code}
    Raises ValueError if inputs yield an invalid rail reference.
    """
    clean_settlement = str(settlement_id).replace("-", "")
    if not clean_settlement:
        raise ValueError("Settlement ID cannot be empty")

    settlement_id_short = clean_settlement[:8]
    rail_code_clean = str(rail_code).strip().upper()
    leg_seq_clean = str(leg_sequence).strip()

    candidate = f"{RAIL_REF_PREFIX}-{settlement_id_short}-{leg_seq_clean}-{rail_code_clean}"
    result = validate_rail_reference(candidate)
    if not result.is_valid:
        raise ValueError(f"Cannot generate rail reference: {result.message}")

    return candidate


def validate_key_by_type(key_value: str, key_type: str | IdempotencyKeyType) -> KeyValidationResult:
    """Validate an idempotency key string according to its specified type."""
    raw_type = key_type.value if isinstance(key_type, IdempotencyKeyType) else str(key_type)

    if raw_type == IdempotencyKeyType.CUSTOMER_KEY.value:
        return validate_customer_key(key_value)
    elif raw_type == IdempotencyKeyType.INTERNAL_DERIVED_KEY.value:
        return validate_internal_derived_key(key_value)
    elif raw_type == IdempotencyKeyType.RAIL_REFERENCE.value:
        return validate_rail_reference(key_value)
    else:
        return KeyValidationResult.invalid(
            ValidationReason.INVALID_FORMAT,
            f"Unrecognized key_type '{key_type}'",
        )


def _build_register_insert_stmt(
    key_value: str,
    key_type_enum: IdempotencyKeyType,
    scope_id: str,
    operation_type: str,
    now: datetime,
    correlation_id: str | None = None,
    created_by: str | None = None,
    metadata: dict | None = None,
    expires_at: datetime | None = None,
):
    """Build atomic INSERT ... ON CONFLICT DO NOTHING RETURNING statement."""
    return (
        pg_insert(IdempotencyRecord)
        .values(
            id=uuid.uuid4(),
            key_value=key_value,
            scope_id=scope_id,
            key_type=key_type_enum,
            operation_type=operation_type,
            status=IdempotencyStatus.ACTIVE,
            first_seen_at=now,
            correlation_id=correlation_id,
            created_by=created_by,
            record_metadata=metadata,
            expires_at=expires_at,
        )
        # Index inference, not `constraint=`: uq_idempotency_record_key_scope is a PARTIAL
        # unique index now, and Postgres will not accept a partial index by name. The
        # index_where must match the index predicate textually — see the note on
        # LIVE_RECORD_PREDICATE_SQL — or inference fails at runtime rather than at import.
        .on_conflict_do_nothing(
            index_elements=["key_value", "scope_id"],
            index_where=text(LIVE_RECORD_PREDICATE_SQL),
        )
        .returning(IdempotencyRecord)
    )


def _build_duplicate_detection(
    existing_record: IdempotencyRecord,
    *,
    detected_at: datetime,
    caller_identity: str | None,
    correlation_id: str | None,
) -> DuplicateDetection:
    """The immutable record of a duplicate that was recognised and short-circuited.

    Not a violation. The operation did not run twice — this row is evidence that
    the idempotency control operated, which is why it is append-only and why the
    Prometheus counter beside it is not a substitute: a counter cannot name the
    key, the caller, or the moment.

    ``caller_identity`` and ``correlation_id`` describe the *duplicate* request,
    not the original. The original's are already on the record this points at.

    Written into the caller's transaction, so a caller that rolls back after a
    duplicate records nothing. That is deliberate — a detection describes a
    request that was actually served, and a rolled-back request was not.
    """
    # completed_at is when the original finished; a duplicate can also arrive
    # against a record that is still active, where the registration itself is the
    # only execution timestamp there is.
    original_executed_at = existing_record.completed_at or existing_record.first_seen_at

    # Clamped at zero. A negative elapsed time means the two timestamps came from
    # clocks that disagree, not that a duplicate preceded its original, and a
    # negative in this column would corrupt every latency aggregate built on it.
    elapsed_ms = int((detected_at - original_executed_at).total_seconds() * 1000)

    return DuplicateDetection(
        id=uuid.uuid4(),
        idempotency_key=existing_record.key_value,
        scope_id=existing_record.scope_id,
        operation_type=existing_record.operation_type,
        original_request_ref=existing_record.id,
        original_executed_at=original_executed_at,
        detected_at=detected_at,
        caller_identity=caller_identity,
        correlation_id=correlation_id,
        time_since_original_ms=max(0, elapsed_ms),
        # The registry keeps request and cached response on one row, so the result
        # handed back is this same record. Kept as its own column because the two
        # answer different questions and will diverge if a result ever becomes an
        # entity of its own.
        returned_result_ref=existing_record.id,
    )


def _build_select_for_update_stmt(key_value: str, scope_id: str):
    """Build SELECT ... FOR UPDATE for the LIVE record of a key, if one exists.

    Expired rows are history and are deliberately invisible here: a key whose only
    records are expired must read as unregistered so registration creates a new one.

    The partial unique index already guarantees at most one live row per pair, so the
    LIMIT is defensive rather than load-bearing — but without the status filter this
    query matches every expired generation too, and scalar_one() would raise
    MultipleResultsFound the first time a key is reused after expiry.
    """
    return (
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.key_value == key_value,
            IdempotencyRecord.scope_id == scope_id,
            IdempotencyRecord.status != IdempotencyStatus.EXPIRED,
        )
        .order_by(IdempotencyRecord.first_seen_at.desc())
        .limit(1)
        .with_for_update()
    )


def _build_latest_select_for_update_stmt(key_value: str, scope_id: str):
    """Build SELECT ... FOR UPDATE preferring the live record, falling back to history.

    Used only by the completion path, which needs to tell "no such key was ever
    registered" apart from "that key expired" — the former is IdempotencyKeyNotFoundError,
    the latter InvalidStateTransitionError. Filtering expired rows out here would collapse
    the second case into the first and lose the diagnosis.

    Ordering puts live before expired (false sorts before true), then newest first, so the
    single row returned is the live record when there is one and the most recent expired
    generation otherwise.
    """
    return (
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.key_value == key_value,
            IdempotencyRecord.scope_id == scope_id,
        )
        .order_by(
            (IdempotencyRecord.status == IdempotencyStatus.EXPIRED),
            IdempotencyRecord.first_seen_at.desc(),
        )
        .limit(1)
        .with_for_update()
    )


def _build_select_stmt(key_value: str, scope_id: str):
    """Build a plain (unlocked) SELECT for the LIVE record of a key, if one exists.

    The read-only mirror of _build_select_for_update_stmt, and it filters expired rows
    for the same reason: since S3T1 the uniqueness of (key_value, scope_id) holds only
    over live rows, so a key reused after expiry matches every past generation here and
    scalar_one_or_none() in get_record would raise MultipleResultsFound.

    Inspection therefore reports what registration would see — the live record, or None
    when the key holds no live registration in this scope.
    """
    return (
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.key_value == key_value,
            IdempotencyRecord.scope_id == scope_id,
            IdempotencyRecord.status != IdempotencyStatus.EXPIRED,
        )
        .order_by(IdempotencyRecord.first_seen_at.desc())
        .limit(1)
    )


def _build_reclaim_update_stmt(
    key_value: str,
    scope_id: str,
    now: datetime,
    new_expires_at: datetime,
):
    """Build the atomic lease-reclaim UPDATE.

    One statement, guarded on every condition that makes reclaiming safe:
    the record must still be ACTIVE, must carry a lease, and that lease must
    already have elapsed. A caller cannot reclaim by reading first and deciding
    itself — the read would be stale by the time it wrote.

    Terminal records are excluded by the status predicate, so a COMPLETED or
    FAILED reference can never be dragged back into flight.

    The metadata expression bumps a lease generation counter in the same
    statement. Unqualified `metadata` in a SET clause reads the pre-update
    value, so the increment is evaluated against the row as locked.
    """
    return (
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.key_value == key_value,
            IdempotencyRecord.scope_id == scope_id,
            IdempotencyRecord.status == IdempotencyStatus.ACTIVE,
            IdempotencyRecord.expires_at.isnot(None),
            IdempotencyRecord.expires_at <= now,
        )
        .values(
            expires_at=new_expires_at,
            record_metadata=text(
                "coalesce(metadata, '{}'::jsonb) || jsonb_build_object("
                "'lease_generation', "
                "coalesce((metadata->>'lease_generation')::int, 0) + 1, "
                "'lease_reclaimed_at', :lease_reclaimed_at)"
            ).bindparams(lease_reclaimed_at=now.isoformat()),
        )
        .returning(IdempotencyRecord)
    )


def _build_complete_update_stmt(
    key_value: str,
    scope_id: str,
    term_status_enum: IdempotencyStatus,
    response_payload: dict | None,
    now: datetime,
):
    """Build UPDATE ... WHERE status = 'active' RETURNING statement."""
    return (
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.key_value == key_value,
            IdempotencyRecord.scope_id == scope_id,
            IdempotencyRecord.status == IdempotencyStatus.ACTIVE,
        )
        .values(
            status=term_status_enum,
            response_cache=response_payload,
            completed_at=now,
        )
        .returning(IdempotencyRecord)
    )


def _resolve_expires_at(
    key_type: IdempotencyKeyType,
    first_seen_at: datetime,
    explicit: datetime | None,
) -> datetime | None:
    """Decide the window this registration carries.

    An explicit value from the caller wins — the parameter is an escape hatch for callers
    that own a deadline of their own. AL-103's rail reference service is one: it passes a
    short lease deadline it later reclaims, which is a different mechanism from the
    configured window and must not be overwritten by it.

    Otherwise this returns the configured window anchored on first_seen_at, or None for key
    types that do not expire on a clock.
    """
    if explicit is not None:
        return explicit
    return compute_expires_at(key_type, first_seen_at)


def _validate_and_parse_registration_inputs(
    key_value: str,
    key_type: str | IdempotencyKeyType,
) -> IdempotencyKeyType:
    validation_res = validate_key_by_type(key_value, key_type)
    if not validation_res.is_valid:
        raise InvalidKeyFormatError(validation_res)

    key_type_str = key_type.value if isinstance(key_type, IdempotencyKeyType) else str(key_type)
    return IdempotencyKeyType(key_type_str)


def _validate_and_parse_terminal_status(
    terminal_status: str | IdempotencyStatus,
) -> IdempotencyStatus:
    term_status_str = (
        terminal_status.value if isinstance(terminal_status, IdempotencyStatus) else str(terminal_status)
    )
    try:
        term_status_enum = IdempotencyStatus(term_status_str)
    except ValueError:
        raise ValueError(
            f"Invalid terminal status '{terminal_status}'. Must be 'completed' or 'failed'"
        ) from None

    if term_status_enum not in (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED):
        raise ValueError(
            f"Invalid terminal status '{terminal_status}'. Must be 'completed' or 'failed'"
        )

    return term_status_enum


async def register_key(
    session: AsyncSession | Session,
    key_value: str,
    key_type: str | IdempotencyKeyType,
    scope_id: str,
    operation_type: str,
    correlation_id: str | None = None,
    created_by: str | None = None,
    metadata: dict | None = None,
    expires_at: datetime | None = None,
) -> RegistrationResult:
    """Register an idempotency key prior to executing an operation (async/sync session)."""
    key_type_enum = _validate_and_parse_registration_inputs(key_value, key_type)

    _reg_start = time.perf_counter()
    for _ in range(_REGISTRATION_ATTEMPTS):
        now = datetime.now(UTC)
        # `now` is what the INSERT writes to first_seen_at, so anchoring here makes
        # expires_at exactly first_seen_at + the configured window.
        effective_expires_at = _resolve_expires_at(key_type_enum, now, expires_at)
        stmt = _build_register_insert_stmt(
            key_value, key_type_enum, scope_id, operation_type, now, correlation_id, created_by, metadata, effective_expires_at
        )

        if isinstance(session, AsyncSession):
            res = await session.execute(stmt)
        else:
            res = session.execute(stmt)
        inserted_record = res.scalar_one_or_none()

        if inserted_record is not None:
            observe_idempotency_registration_latency(time.perf_counter() - _reg_start)
            record_idempotency_registration(key_type_enum.value, operation_type)
            return RegistrationResult.new(inserted_record)

        select_stmt = _build_select_for_update_stmt(key_value, scope_id)
        if isinstance(session, AsyncSession):
            existing_res = await session.execute(select_stmt)
        else:
            existing_res = session.execute(select_stmt)
        existing_record = existing_res.scalar_one_or_none()

        if existing_record is not None:
            observe_idempotency_registration_latency(time.perf_counter() - _reg_start)
            record_idempotency_duplicate(key_type_enum.value, operation_type, existing_record.status.value)
            session.add(
                _build_duplicate_detection(
                    existing_record,
                    detected_at=now,
                    caller_identity=created_by,
                    correlation_id=correlation_id,
                )
            )
            # Returning the existing record is what short-circuits the caller: the
            # operation this key guards is not executed a second time.
            return RegistrationResult.duplicate(existing_record)

        # No live record, yet the insert conflicted: the blocking row was expired between
        # the two statements, which frees the key. Re-attempt the insert.

    raise RegistrationRaceError(key_value, scope_id, _REGISTRATION_ATTEMPTS)


def register_key_sync(
    session: Session,
    key_value: str,
    key_type: str | IdempotencyKeyType,
    scope_id: str,
    operation_type: str,
    correlation_id: str | None = None,
    created_by: str | None = None,
    metadata: dict | None = None,
    expires_at: datetime | None = None,
) -> RegistrationResult:
    """Synchronous version of register_key for sync database sessions / connections."""
    key_type_enum = _validate_and_parse_registration_inputs(key_value, key_type)

    _reg_start = time.perf_counter()
    for _ in range(_REGISTRATION_ATTEMPTS):
        now = datetime.now(UTC)
        # `now` is what the INSERT writes to first_seen_at, so anchoring here makes
        # expires_at exactly first_seen_at + the configured window.
        effective_expires_at = _resolve_expires_at(key_type_enum, now, expires_at)
        stmt = _build_register_insert_stmt(
            key_value, key_type_enum, scope_id, operation_type, now, correlation_id, created_by, metadata, effective_expires_at
        )

        res = session.execute(stmt)
        inserted_record = res.scalar_one_or_none()
        if inserted_record is not None:
            observe_idempotency_registration_latency(time.perf_counter() - _reg_start)
            record_idempotency_registration(key_type_enum.value, operation_type)
            return RegistrationResult.new(inserted_record)

        select_stmt = _build_select_for_update_stmt(key_value, scope_id)
        existing_res = session.execute(select_stmt)
        existing_record = existing_res.scalar_one_or_none()

        if existing_record is not None:
            observe_idempotency_registration_latency(time.perf_counter() - _reg_start)
            record_idempotency_duplicate(key_type_enum.value, operation_type, existing_record.status.value)
            session.add(
                _build_duplicate_detection(
                    existing_record,
                    detected_at=now,
                    caller_identity=created_by,
                    correlation_id=correlation_id,
                )
            )
            return RegistrationResult.duplicate(existing_record)

        # See register_key: the blocking row expired between the two statements.

    raise RegistrationRaceError(key_value, scope_id, _REGISTRATION_ATTEMPTS)


async def get_record(
    session: AsyncSession | Session,
    key_value: str,
    scope_id: str,
) -> IdempotencyRecord | None:
    """Read the live idempotency record for a key without registering or locking it.

    Returns None when the key holds no live registration in this scope — either it was
    never registered, or every generation of it has expired. Expired history is not
    reported: inspection answers "is this key claimed right now", which is the same
    question register_key answers.

    Unlike register_key this takes no row lock and writes nothing, so it is safe to
    call for inspection without side effects on the registry.
    """
    stmt = _build_select_stmt(key_value, scope_id)
    if isinstance(session, AsyncSession):
        res = await session.execute(stmt)
    else:
        res = session.execute(stmt)
    return res.scalar_one_or_none()


def get_record_sync(
    session: Session,
    key_value: str,
    scope_id: str,
) -> IdempotencyRecord | None:
    """Synchronous version of get_record for sync database sessions."""
    res = session.execute(_build_select_stmt(key_value, scope_id))
    return res.scalar_one_or_none()


async def reclaim_expired_key(
    session: AsyncSession | Session,
    key_value: str,
    scope_id: str,
    new_expires_at: datetime,
    now: datetime | None = None,
) -> IdempotencyRecord | None:
    """Atomically take over an ACTIVE record whose lease has elapsed.

    Returns the reclaimed record, or None when the record does not exist, is
    not ACTIVE, carries no lease, or holds a lease that has not yet elapsed.
    None always means "not yours" and must never be read as permission to
    proceed.

    Concurrency-safe by construction: the predicate and the write are one
    statement, so of two callers racing on the same expired lease exactly one
    matches a row and the other matches none.
    """
    effective_now = now or datetime.now(UTC)
    stmt = _build_reclaim_update_stmt(key_value, scope_id, effective_now, new_expires_at)

    if isinstance(session, AsyncSession):
        res = await session.execute(stmt)
    else:
        res = session.execute(stmt)
    return res.scalar_one_or_none()


async def complete_key(
    session: AsyncSession | Session,
    key_value: str,
    scope_id: str,
    terminal_status: str | IdempotencyStatus,
    response_payload: dict | None = None,
) -> IdempotencyRecord:
    """Transition an active key to a terminal status (completed or failed) and cache response payload."""
    validate_response_cache_payload(response_payload)
    term_status_enum = _validate_and_parse_terminal_status(terminal_status)
    now = datetime.now(UTC)
    stmt = _build_complete_update_stmt(key_value, scope_id, term_status_enum, response_payload, now)

    if isinstance(session, AsyncSession):
        res = await session.execute(stmt)
        updated_record = res.scalar_one_or_none()
    else:
        res = session.execute(stmt)
        updated_record = res.scalar_one_or_none()

    if updated_record is not None:
        return updated_record

    select_stmt = _build_latest_select_for_update_stmt(key_value, scope_id)
    if isinstance(session, AsyncSession):
        existing_res = await session.execute(select_stmt)
        existing_record = existing_res.scalar_one_or_none()
    else:
        existing_res = session.execute(select_stmt)
        existing_record = existing_res.scalar_one_or_none()

    if existing_record is None:
        raise IdempotencyKeyNotFoundError(key_value, scope_id)

    if existing_record.status in (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED):
        return existing_record

    raise InvalidStateTransitionError(key_value, existing_record.status.value, term_status_enum.value)


def complete_key_sync(
    session: Session,
    key_value: str,
    scope_id: str,
    terminal_status: str | IdempotencyStatus,
    response_payload: dict | None = None,
) -> IdempotencyRecord:
    """Synchronous version of complete_key for sync database sessions / connections."""
    validate_response_cache_payload(response_payload)
    term_status_enum = _validate_and_parse_terminal_status(terminal_status)
    now = datetime.now(UTC)
    stmt = _build_complete_update_stmt(key_value, scope_id, term_status_enum, response_payload, now)

    res = session.execute(stmt)
    updated_record = res.scalar_one_or_none()
    if updated_record is not None:
        return updated_record

    select_stmt = _build_latest_select_for_update_stmt(key_value, scope_id)
    existing_res = session.execute(select_stmt)
    existing_record = existing_res.scalar_one_or_none()

    if existing_record is None:
        raise IdempotencyKeyNotFoundError(key_value, scope_id)

    if existing_record.status in (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED):
        return existing_record

    raise InvalidStateTransitionError(key_value, existing_record.status.value, term_status_enum.value)


async def list_records_by_scopes(
    session: AsyncSession | Session,
    scope_ids: list[str],
    key_types: list[IdempotencyKeyType] | None = None,
) -> list[IdempotencyRecord]:
    """Read every record, any status, across a set of scope_ids without mutating them.

    Lets a caller tell "nothing was ever registered for this scope" apart from
    "everything registered is already at a terminal status" before attempting a bulk
    transition — a distinction transition_records_by_scopes's UPDATE result alone
    cannot make, since an empty result means either.

    key_types, when given, restricts which key_type rows are visible. Settlement
    lifecycle events own internal_derived_key (IDK) and rail_reference (RR) records only
    — customer_key is CK's own time-based expiry sweep's exclusive territory (S1T3), and
    a settlement_id/leg_id colliding with an unrelated customer_key's scope_id must never
    surface it here.
    """
    if not scope_ids:
        return []

    conditions = [IdempotencyRecord.scope_id.in_(scope_ids)]
    if key_types:
        conditions.append(IdempotencyRecord.key_type.in_(key_types))

    stmt = select(IdempotencyRecord).where(*conditions)
    if isinstance(session, AsyncSession):
        res = await session.execute(stmt)
    else:
        res = session.execute(stmt)
    return list(res.scalars().all())


def _build_bulk_transition_stmt(
    scope_ids: list[str],
    term_status_enum: IdempotencyStatus,
    now: datetime,
    key_types: list[IdempotencyKeyType] | None,
):
    """Build UPDATE ... WHERE scope_id = ANY(...) AND status = 'active' RETURNING statement."""
    conditions = [
        IdempotencyRecord.scope_id.in_(scope_ids),
        IdempotencyRecord.status == IdempotencyStatus.ACTIVE,
    ]
    if key_types:
        conditions.append(IdempotencyRecord.key_type.in_(key_types))
    return (
        update(IdempotencyRecord)
        .where(*conditions)
        .values(
            status=term_status_enum,
            completed_at=now,
        )
        .returning(IdempotencyRecord)
    )


async def transition_records_by_scopes(
    session: AsyncSession | Session,
    scope_ids: list[str],
    terminal_status: str | IdempotencyStatus,
    key_types: list[IdempotencyKeyType] | None = None,
) -> list[IdempotencyRecord]:
    """Bulk-transition every ACTIVE record across a set of scope_ids to a terminal status.

    A settlement lifecycle event settles many records in one shot: the settlement's own
    IDK records (scope_id = settlement_id) and every leg's RR records (scope_id = leg id).
    The WHERE status='active' clause is what makes redelivery a no-op — a record already
    in a terminal status is excluded from the UPDATE and simply doesn't appear in the
    returned list, the same guarantee complete_key gives a single record.

    key_types restricts which key_type rows are eligible — see list_records_by_scopes for
    why this matters: a settlement's scope_id must never reach into CK's territory.
    """
    if not scope_ids:
        return []

    term_status_enum = _validate_and_parse_terminal_status(terminal_status)
    now = datetime.now(UTC)
    stmt = _build_bulk_transition_stmt(scope_ids, term_status_enum, now, key_types)

    if isinstance(session, AsyncSession):
        res = await session.execute(stmt)
    else:
        res = session.execute(stmt)
    return list(res.scalars().all())


class IdempotencyKeyRegistrationService(IdempotencyRegistrationPort):
    """Platform implementation of key registration service."""

    def __init__(self, session: AsyncSession | Session):
        self.session = session

    async def register_key(
        self,
        key_value: str,
        key_type: str,
        scope_id: str,
        operation_type: str,
        correlation_id: str | None = None,
        created_by: str | None = None,
        metadata: dict | None = None,
        expires_at: datetime | None = None,
    ) -> RegistrationResult:
        return await register_key(
            session=self.session,
            key_value=key_value,
            key_type=key_type,
            scope_id=scope_id,
            operation_type=operation_type,
            correlation_id=correlation_id,
            created_by=created_by,
            metadata=metadata,
            expires_at=expires_at,
        )

    async def complete_key(
        self,
        key_value: str,
        scope_id: str,
        terminal_status: str,
        response_payload: dict | None = None,
    ) -> IdempotencyRecord:
        return await complete_key(
            session=self.session,
            key_value=key_value,
            scope_id=scope_id,
            terminal_status=terminal_status,
            response_payload=response_payload,
        )


async def collect_registry_size_metrics() -> None:
    """Query idempotency_record row counts by status and update the Prometheus gauge (S4T1).

    Called periodically by the background scheduler.  Best-effort: a failed
    collection is logged but never breaks the application.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(IdempotencyRecord.status, func.count())
                .select_from(IdempotencyRecord)
                .group_by(IdempotencyRecord.status)
            )
            rows = result.all()

        # Reset every status to 0 first, then set actual counts.  Statuses
        # with no rows in the DB (e.g. 'expired' when nothing has expired)
        # are explicitly zeroed rather than holding a stale value.
        for status in IdempotencyStatus:
            IDEMPOTENCY_REGISTRY_SIZE.labels(status=status.value).set(0)
        for status_enum, count in rows:
            IDEMPOTENCY_REGISTRY_SIZE.labels(status=status_enum.value).set(count)
    except Exception as exc:  # noqa: BLE001 — metrics collection is best-effort
        logger.warning("registry_size_collection_failed", error=str(exc))

