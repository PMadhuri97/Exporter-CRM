"""Exceptions for idempotency platform capability."""

from app.platform.idempotency.models import KeyValidationResult


class IdempotencyError(Exception):
    """Base exception for all idempotency-related errors."""


class InvalidKeyFormatError(IdempotencyError):
    """Raised when an idempotency key fails format validation."""

    def __init__(self, validation_result: KeyValidationResult):
        self.validation_result = validation_result
        message = (
            f"Invalid key format: {validation_result.reason.value if validation_result.reason else 'UNKNOWN'} - "
            f"{validation_result.message}"
        )
        super().__init__(message)


class KeyExpiryConfigurationError(IdempotencyError):
    """Raised when the GitOps key-expiry configuration is missing, malformed or incomplete.

    Deliberately fatal rather than falling back to a built-in default. A default would be a
    hardcoded expiry duration by another name, and the failure it hides — a key type nobody
    configured, silently never expiring — surfaces only when an auditor asks why.
    """


class IdempotencyKeyNotFoundError(IdempotencyError):
    """Raised when an idempotency key is not found in the registry."""

    def __init__(self, key_value: str, scope_id: str):
        self.key_value = key_value
        self.scope_id = scope_id
        super().__init__(f"Idempotency record not found for key '{key_value}' in scope '{scope_id}'")


class RegistrationRaceError(IdempotencyError):
    """Raised when registration cannot resolve to either a new or an existing record.

    Registration inserts, and on conflict reads back the live record that blocked it. If
    that record is expired by the sweep in between, the read finds nothing and the key is
    free again — so registration retries. Exhausting the retries means the insert kept
    conflicting with a row that kept vanishing, which is not the expiry race and should
    surface rather than spin.
    """

    def __init__(self, key_value: str, scope_id: str, attempts: int):
        self.key_value = key_value
        self.scope_id = scope_id
        self.attempts = attempts
        super().__init__(
            f"Could not register idempotency key '{key_value}' in scope '{scope_id}' after "
            f"{attempts} attempts: the conflicting record was expired concurrently each time"
        )


class InvalidStateTransitionError(IdempotencyError):
    """Raised when attempting an illegal status transition on an idempotency key."""

    def __init__(self, key_value: str, current_status: str, target_status: str):
        self.key_value = key_value
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"Cannot transition idempotency key '{key_value}' from status '{current_status}' to '{target_status}'"
        )


class DuplicateOperationConflictError(IdempotencyError):
    """Raised when an operation key registration is active and currently in-progress (maps to HTTP 409 Conflict)."""

    def __init__(self, key_value: str, scope_id: str):
        self.key_value = key_value
        self.scope_id = scope_id
        super().__init__(
            f"Operation with idempotency key '{key_value}' in scope '{scope_id}' is currently active and in progress"
        )


class DuplicateOperationFailedError(IdempotencyError):
    """Raised when re-execution is attempted on a failed key without generating a new key."""

    def __init__(self, key_value: str, scope_id: str, cached_response: dict | None = None):
        self.key_value = key_value
        self.scope_id = scope_id
        self.cached_response = cached_response
        super().__init__(
            f"Operation with idempotency key '{key_value}' in scope '{scope_id}' previously failed. "
            "A new key must be generated to retry the operation."
        )


class ResponseCacheExceededError(IdempotencyError):
    """Raised when response cache payload exceeds maximum allowed size (64 KB)."""

    def __init__(self, size_bytes: int, max_bytes: int = 65536):
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Response cache payload size ({size_bytes} bytes) exceeds maximum limit of {max_bytes} bytes"
        )


