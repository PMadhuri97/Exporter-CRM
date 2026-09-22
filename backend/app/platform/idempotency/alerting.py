"""SRE Alerting and Deduplication router for Idempotency Violations (S4T2).

Ensures violation alerts:
1. Include all 6 strictly-typed Protobuf ViolationReport fields.
2. Route to SRE on-call via Epic 1.4 operational readiness (CRITICAL / PAGE_SRE_ONCALL).
3. Record every violation detection into audit.audit_events (with UUID validation).
4. Deduplicate alerts via cache to prevent paging SRE twice for Kafka retries or re-sweeps.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
import uuid
from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy import text

from app.platform.idempotency.proto import ViolationReport
from app.platform.observability.metrics import record_idempotency_violation
from app.shared.constants.idempotency import IDEMPOTENCY_VIOLATION_EVENT_TYPE

logger = structlog.get_logger(__name__)

SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# In-memory deduplication cache backstop (hash -> timestamp) if Redis is offline
_ALERT_CACHE: dict[str, float] = {}
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours retention for alert deduplication


def _ensure_valid_uuid(val: str | None) -> str:
    """Validate or convert correlation ID into a valid UUID string format for postgres UUID column."""
    if not val:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(val))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:aner:correlation:{val}"))


def compute_violation_hash(
    key_value: str,
    scope: str,
    operation_type: str,
    involved_ids: Sequence[str],
) -> str:
    """Compute a deterministic hash for a violation incident."""
    sorted_ids = ",".join(sorted(involved_ids))
    raw = f"{key_value}:{scope}:{operation_type}:{sorted_ids}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def dispatch_violation_alert(
    db: Any,
    *,
    key_value: str,
    scope: str,
    operation_type: str,
    execution_count: int,
    involved_object_ids: Sequence[str],
    correlation_id: str | None = None,
) -> ViolationReport:
    """Construct protobuf violation report, check cache deduplication, alert SRE, and record audit."""
    corr_id_str = correlation_id or str(uuid.uuid4())
    audit_uuid = _ensure_valid_uuid(corr_id_str)
    involved_ids_list = [str(x) for x in involved_object_ids]

    # Create strictly-typed Protobuf ViolationReport payload
    report = ViolationReport(
        key_value=key_value,
        scope=scope,
        operation_type=operation_type,
        execution_count=execution_count,
        involved_object_ids=involved_ids_list,
        correlation_id=corr_id_str,
    )

    # Compute violation hash for deduplication
    v_hash = compute_violation_hash(key_value, scope, operation_type, involved_ids_list)
    now = time.time()

    # Check in-memory / cache deduplication
    already_alerted = False
    if v_hash in _ALERT_CACHE and (now - _ALERT_CACHE[v_hash]) < _CACHE_TTL_SECONDS:
        already_alerted = True

    # Record Prometheus violation counter
    record_idempotency_violation()

    # 1. ALWAYS emit SRE Critical Operational Readiness Alert FIRST (unless duplicate)
    if not already_alerted:
        _ALERT_CACHE[v_hash] = now
        logger.error(
            "idempotency_violation_detected",
            alert_severity="CRITICAL",
            alert_action="PAGE_SRE_ONCALL",
            key_value=report.key_value,
            scope=report.scope,
            operation_type=report.operation_type,
            execution_count=report.execution_count,
            involved_object_ids=report.involved_object_ids,
            correlation_id=report.correlation_id,
            violation_report=report.to_dict(),
        )
    else:
        logger.info(
            "idempotency_violation_alert_suppressed_duplicate",
            violation_hash=v_hash,
            key_value=key_value,
            correlation_id=corr_id_str,
        )

    # 2. Record audit log event into audit.audit_events (resilient against DB format errors)
    if db is not None and hasattr(db, "execute"):
        try:
            audit_sql = text("""
                INSERT INTO audit.audit_events (
                    id, event_type, actor_id, actor_type, correlation_id, payload, created_at
                ) VALUES (
                    gen_random_uuid(), :event_type, :actor_id, CAST(:actor_type AS audit.actor_type_enum), CAST(:correlation_id AS uuid), :payload, NOW()

                )
            """)
            payload_data = {
                "violation_hash": v_hash,
                "key_value": report.key_value,
                "scope": report.scope,
                "operation_type": report.operation_type,
                "execution_count": report.execution_count,
                "involved_object_ids": report.involved_object_ids,
                "correlation_id": report.correlation_id,
                "already_alerted": already_alerted,
                "protobuf_bytes_hex": report.SerializeToString().hex(),
            }
            audit_params = {
                "event_type": IDEMPOTENCY_VIOLATION_EVENT_TYPE,
                "actor_id": str(SYSTEM_ACTOR_ID),
                "actor_type": "SYSTEM",
                "correlation_id": audit_uuid,
                "payload": json.dumps(payload_data),
            }

            res = db.execute(audit_sql, audit_params)
            if inspect.isawaitable(res):
                await res
        except Exception as err:
            logger.exception("idempotency_violation_audit_log_failed", error=str(err))

    return report


def clear_alert_cache() -> None:
    """Clear deduplication cache (used for unit tests)."""
    _ALERT_CACHE.clear()
