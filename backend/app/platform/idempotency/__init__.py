"""Idempotency key format validation and generation shared platform package.

This package provides canonical format validation and deterministic key generation
for customer keys, internal derived keys, and payment rail references.
"""

__version__ = "1.0.0"

from app.platform.idempotency.alerting import (
    compute_violation_hash,
    dispatch_violation_alert,
)
from app.platform.idempotency.archive_models import IdempotencyArchive
from app.platform.idempotency.audit_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditRecord,
    AuditRecordPage,
    IdempotencyAuditRepository,
    RecordSource,
)
from app.platform.idempotency.audit_service import IdempotencyAuditQueryService
from app.platform.idempotency.config import (
    compute_expires_at,
    expiry_window_for,
    get_key_expiry_windows,
    get_sweep_interval,
    key_name_for,
    load_key_expiry_windows,
    load_sweep_interval,
    parse_seconds,
    reset_key_expiry_windows_cache,
)
from app.platform.idempotency.context import (
    IDEMPOTENCY_KEY_FIELD,
    bind_idempotency_key,
    current_idempotency_key,
)
from app.platform.idempotency.detection_models import DuplicateDetection
from app.platform.idempotency.exceptions import (
    DuplicateOperationConflictError,
    DuplicateOperationFailedError,
    IdempotencyError,
    IdempotencyKeyNotFoundError,
    InvalidKeyFormatError,
    InvalidStateTransitionError,
    KeyExpiryConfigurationError,
    RegistrationRaceError,
    ResponseCacheExceededError,
)
from app.platform.idempotency.expiry import (
    IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY,
    ExpirySweepResult,
    IdempotencyExpiryService,
)
from app.platform.idempotency.liveness import (
    check_detector_liveness,
)
from app.platform.idempotency.models import (
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
from app.platform.idempotency.ports import (
    IdempotencyRegistrationPort,
    ReferenceKeyResolver,
    ReferenceScopeResolver,
    ScopedReferenceResolver,
)
from app.platform.idempotency.proto import ViolationReport
from app.platform.idempotency.services import (
    IdempotencyKeyRegistrationService,
    complete_key,
    complete_key_sync,
    derive_internal_key,
    evaluate_duplicate_contract,
    generate_rail_reference,
    get_record,
    get_record_sync,
    handle_duplicate_contract,
    list_records_by_scopes,
    reclaim_expired_key,
    register_key,
    register_key_sync,
    transition_records_by_scopes,
    validate_customer_key,
    validate_internal_derived_key,
    validate_rail_reference,
    validate_response_cache_payload,
)
from app.platform.idempotency.stream_processor import (
    IdempotencyViolationStreamProcessor,
)
from app.platform.idempotency.utilities import (
    KNOWN_RAIL_CODES,
    MAX_CUSTOMER_KEY_LENGTH,
    MAX_INTERNAL_KEY_LENGTH,
    MAX_RAIL_REF_LENGTH,
    RAIL_REF_PREFIX,
)
from app.platform.idempotency.violation_detector import (
    IDEMPOTENCY_VIOLATION_CHECK_LOCK_KEY,
    ScheduledCheckResult,
    ScheduledViolationDetector,
)

__all__ = [
    "__version__",
    "KeyValidationResult",
    "ValidationReason",
    "RegistrationResult",
    "RegistrationResultType",
    "IdempotencyStatus",
    "IdempotencyKeyType",
    "IdempotencyRecord",
    "DuplicateHandlingAction",
    "DuplicateContractResult",
    "IdempotencyArchive",
    "DuplicateDetection",
    "IdempotencyAuditRepository",
    "IdempotencyAuditQueryService",
    "AuditRecord",
    "AuditRecordPage",
    "RecordSource",
    "MAX_PAGE_SIZE",
    "DEFAULT_PAGE_SIZE",
    "IDEMPOTENCY_KEY_FIELD",
    "bind_idempotency_key",
    "current_idempotency_key",
    "IdempotencyError",
    "InvalidKeyFormatError",
    "IdempotencyKeyNotFoundError",
    "InvalidStateTransitionError",
    "KeyExpiryConfigurationError",
    "RegistrationRaceError",
    "IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY",
    "ExpirySweepResult",
    "IdempotencyExpiryService",
    "compute_expires_at",
    "expiry_window_for",
    "get_key_expiry_windows",
    "get_sweep_interval",
    "load_key_expiry_windows",
    "load_sweep_interval",
    "key_name_for",
    "parse_seconds",
    "reset_key_expiry_windows_cache",
    "DuplicateOperationConflictError",
    "DuplicateOperationFailedError",
    "ResponseCacheExceededError",
    "IdempotencyRegistrationPort",
    "ReferenceKeyResolver",
    "ReferenceScopeResolver",
    "ScopedReferenceResolver",
    "IdempotencyKeyRegistrationService",
    "register_key",
    "register_key_sync",
    "complete_key",
    "complete_key_sync",
    "get_record",
    "get_record_sync",
    "reclaim_expired_key",
    "evaluate_duplicate_contract",
    "handle_duplicate_contract",
    "validate_response_cache_payload",
    "MAX_CUSTOMER_KEY_LENGTH",
    "MAX_INTERNAL_KEY_LENGTH",
    "MAX_RAIL_REF_LENGTH",
    "KNOWN_RAIL_CODES",
    "RAIL_REF_PREFIX",
    "validate_customer_key",
    "validate_internal_derived_key",
    "validate_rail_reference",
    "derive_internal_key",
    "generate_rail_reference",
    "transition_records_by_scopes",
    "list_records_by_scopes",
    "ViolationReport",
    "dispatch_violation_alert",
    "compute_violation_hash",
    "ScheduledViolationDetector",
    "ScheduledCheckResult",
    "IDEMPOTENCY_VIOLATION_CHECK_LOCK_KEY",
    "IdempotencyViolationStreamProcessor",
    "check_detector_liveness",
]

