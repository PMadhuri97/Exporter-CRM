import os
from collections import deque
from datetime import UTC, datetime
from typing import Any

import structlog

from app.platform.audit_framework.config import (
    AUDIT_BUCKET_NAME,
    GCP_PROJECT_ID,
    LOG_SINK_LOGGER_NAME,
    SERVICE_ACCOUNT_EMAIL,
)

logger = structlog.get_logger(__name__)

_audit_sink_logger_instance: "AuditSinkLogger | None" = None


def get_audit_sink_logger() -> "AuditSinkLogger":
    global _audit_sink_logger_instance
    if _audit_sink_logger_instance is None:
        _audit_sink_logger_instance = AuditSinkLogger()
    return _audit_sink_logger_instance


class AuditSinkLogger:
    """Writes structured audit log entries to the immutable GCP Cloud Storage

    infrastructure via Cloud Logging and Log Sink.
    """

    recorded_entries: deque[dict[str, Any]] = deque(maxlen=1000)

    def __init__(self) -> None:
        self.project_id = GCP_PROJECT_ID
        self.bucket_name = AUDIT_BUCKET_NAME
        self.logger_name = LOG_SINK_LOGGER_NAME
        self._gcp_logger = None
        self._init_gcp_logger()

    def _init_gcp_logger(self) -> None:
        try:
            from google.cloud import logging as google_logging

            client = google_logging.Client(project=self.project_id)
            self._gcp_logger = client.logger(self.logger_name)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "gcp_cloud_logging_not_initialized",
                reason=str(exc),
                message="Falling back to standard structlog and test in-memory sink",
            )
            self._gcp_logger = None

    def _get_active_credential_identity(self) -> str:
        """Resolve the active credential email/identity from configuration."""
        return SERVICE_ACCOUNT_EMAIL

    def emit_audit_entry(
        self,
        *,
        idempotency_key: str,
        correlation_id: str,
        transaction_type: str,
        outcome: str,  # "SUCCESS" | "FAILED" | "REJECTED"
        rejection_reason: str | None = None,
        calling_service_identity: str | None = None,
        timestamp: str | None = None,
        extra_fields: dict[str, Any] | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        """Emit an immutable audit log entry containing all required fields."""
        entry_timestamp = timestamp or datetime.now(UTC).isoformat()
        identity = calling_service_identity or self._get_active_credential_identity()

        payload: dict[str, Any] = {
            "audit_type": "ledger_posting",
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "transaction_type": transaction_type,
            "outcome": outcome,
            "rejection_reason": rejection_reason,
            "calling_service_identity": identity,
            "timestamp": entry_timestamp,
            "event_type": event_type,
        }

        if extra_fields:
            payload["details"] = extra_fields

        # 1. Emit to GCP Cloud Logging if active
        if self._gcp_logger is not None:
            try:
                self._gcp_logger.log_struct(payload, severity="INFO")
            except Exception as exc:  # noqa: BLE001
                logger.error("gcp_audit_sink_write_failed", error=str(exc), payload=payload)

        # 2. Emit to structlog
        logger.info("posting_audit_log_entry", **payload)

        # 3. Store in test class attribute sink only if running under pytest
        if os.getenv("PYTEST_CURRENT_TEST"):
            AuditSinkLogger.recorded_entries.append(payload)

        return payload

    @classmethod
    def get_recorded_entries(cls) -> list[dict[str, Any]]:
        """Return recorded audit entries from test sink."""
        return list(cls.recorded_entries)

    @classmethod
    def clear_recorded_entries(cls) -> None:
        """Clear recorded entries from test sink."""
        cls.recorded_entries.clear()


def verify_bucket_immutability(object_name: str) -> dict[str, Any]:
    """Attempt direct deletion of an audit log object in GCP Cloud Storage bucket

    to confirm retention policy / locked immutability.
    """
    import google.cloud.storage as storage  # type: ignore[import-untyped]
    from google.api_core.exceptions import Forbidden

    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(AUDIT_BUCKET_NAME)
    blob = bucket.blob(object_name)

    try:
        # Attempt direct deletion
        blob.delete()
        return {
            "deleted": True,
            "immutable": False,
            "reason": "Direct deletion succeeded (retention lock inactive)",
        }
    except Forbidden as exc:
        # Narrowed to Forbidden exception. Check if it's due to retention lock.
        exc_str = str(exc)
        if "retentionPolicyNotMet" in exc_str or "retention policy" in exc_str.lower():
            return {
                "deleted": False,
                "immutable": True,
                "reason": f"Deletion rejected by GCP Storage lock policy: {exc!s}",
            }
        # If it's a different Forbidden error (e.g. permission denied for other reasons),
        # bubble it up so it does not get treated as immutable.
        raise
