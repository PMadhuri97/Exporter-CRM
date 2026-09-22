"""Scheduled Violation Detector (S4T2).

Executes scheduled checks every 15 minutes across:
1. Epic 2.1 Ledger Transactions (same settlement leg posted twice under a drifted idempotency key).
2. Epic 2.2 Settlements (cross-table joins & non-terminal settlement correlation ID duplicates).
3. Epic 2.4 Rail Submissions (duplicate partner status confirmations).

Updates Prometheus gauge `aner_idempotency_scheduled_check_last_run_timestamp` on run completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.platform.idempotency.alerting import dispatch_violation_alert
from app.platform.observability.metrics import IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN

logger = structlog.get_logger(__name__)

#: Postgres advisory lock key for scheduled violation detection sweep.
IDEMPOTENCY_VIOLATION_CHECK_LOCK_KEY = 1040002

NON_TERMINAL_SETTLEMENT_STATUSES = (
    "initiated",
    "funded",
    "screened",
    "authorized",
    "routed",
    "settling",
    "failed_pending_compensation",
)


@dataclass
class ScheduledCheckResult:
    """Outcome of one scheduled check run."""

    violations_detected: int = 0
    ran: bool = True
    details: list[dict[str, Any]] = field(default_factory=list)


class ScheduledViolationDetector:
    """Scheduled violation detection engine."""

    def __init__(self, session: AsyncSession | Session) -> None:
        self._session = session

    async def run_scheduled_check(self) -> ScheduledCheckResult:
        """Run violation detection queries across ledger, settlement, and rail records.

        Acquires a transaction-scoped advisory lock so only one replica executes the check.
        """
        logger.info("scheduled_violation_check_started")

        lock_acquired = await self._try_acquire_lock()
        if not lock_acquired:
            logger.info("scheduled_violation_check_skipped_already_running")
            return ScheduledCheckResult(violations_detected=0, ran=False)

        result = ScheduledCheckResult(violations_detected=0, ran=True)

        # 1. Check Ledger duplicate postings (same settlement leg posted twice under a drifted key)
        ledger_violations = await self._check_ledger_duplicates()
        result.details.extend(ledger_violations)

        # 2. Check Settlement non-terminal correlation ID duplicates & registry joins
        settlement_violations = await self._check_settlement_duplicates()
        result.details.extend(settlement_violations)

        # 3. Check Rail Partner duplicate confirmations
        rail_violations = await self._check_rail_duplicates()
        result.details.extend(rail_violations)

        result.violations_detected = len(result.details)

        # Dispatch alerts for all detected violations
        for item in result.details:
            await dispatch_violation_alert(
                self._session,
                key_value=item["key_value"],
                scope=item["scope"],
                operation_type=item["operation_type"],
                execution_count=item["execution_count"],
                involved_object_ids=item["involved_object_ids"],
                correlation_id=item.get("correlation_id"),
            )

        # Update last run timestamp in Prometheus metric
        IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN.set(time.time())

        logger.info(
            "scheduled_violation_check_completed",
            violations_detected=result.violations_detected,
        )

        return result

    async def _try_acquire_lock(self) -> bool:
        res = await self._execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": IDEMPOTENCY_VIOLATION_CHECK_LOCK_KEY},
        )
        return bool(res.scalar_one())

    async def _check_ledger_duplicates(self) -> list[dict[str, Any]]:
        """Detect a real duplicate posting caused by idempotency-key format drift.

        `posting_key()` (ledger_postings.py) documents the actual failure mode this
        guards against: "a second definition [of the key format] that drifted from
        this one would silently double-post rather than fail." That is concretely
        possible today — `derive_internal_key(settlement_id, step)` (S2T2/AL-102,
        used by the Temporal activities in activities.py) produces
        "{settlement_id}:{step}", while `posting_key(transaction_id, leg)` produces
        "settle:{transaction_id}:{leg}". Two different formats for the same
        (settlement, leg): if both code paths ever post the same leg of the same
        settlement, the two rows get different idempotency_key values, so
        `uq_ledger_txn_idem` (unique on idempotency_key alone) cannot catch it.

        Every posting call site tags `metadata->>'leg'` (the ORM's `transaction_metadata`
        attribute; the DB column is named `metadata`) with a stable
        name regardless of which key format was used ("customer_debit",
        "usdc_bridge", "inr_conversion", "customer_credit" — see ledger_postings.py),
        so (settlement_id, leg) is the correct grouping key: it is what "the same
        logical operation" actually means here. A raw idempotency_key or
        correlation_id comparison is wrong — idempotency_key is unique per row by
        construction (so a same-key comparison can never fire), and correlation_id
        is deliberately shared across a settlement's own legs (post_customer_debit,
        post_conversion x2, post_customer_credit all pass one correlation_id), so
        grouping by it alone flags every ordinary multi-leg settlement.
        """
        sql = text("""
            SELECT
                t.settlement_id::text AS settlement_id,
                t.metadata->>'leg' AS leg,
                COUNT(*) AS execution_count,
                ARRAY_AGG(t.id::text) AS involved_object_ids,
                MAX(t.created_by) AS scope,
                MAX(t.correlation_id::text) AS correlation_id
            FROM ledger.ledger_transaction t
            WHERE t.status = 'posted'
              AND t.transaction_type <> 'compensation'
              AND t.compensates_transaction_id IS NULL
              AND t.settlement_id IS NOT NULL
            GROUP BY t.settlement_id, t.metadata->>'leg'
            HAVING COUNT(*) > 1;
        """)

        res = await self._execute(sql)
        rows = res.fetchall()

        violations = []
        for r in rows:
            leg = r.leg or "unknown_leg"
            violations.append({
                "key_value": f"settle:{r.settlement_id}:{leg}",
                "scope": str(r.scope or "ledger"),
                "operation_type": "ledger_posting",
                "execution_count": int(r.execution_count),
                "involved_object_ids": list(r.involved_object_ids),
                "correlation_id": str(r.correlation_id or ""),
            })
        return violations

    async def _check_settlement_duplicates(self) -> list[dict[str, Any]]:
        """Cross-table comparison between idempotency registry & settlement.settlement."""
        # Query A: Registry JOIN settlement.settlement (detects multiple settlements tied to registry record/correlation)
        sql_join = text("""
            SELECT
                r.key_value,
                s.sender_account_id::text AS scope,
                COUNT(s.id) AS execution_count,
                ARRAY_AGG(s.id::text) AS involved_object_ids,
                MAX(s.correlation_id) AS correlation_id
            FROM ledger.idempotency_record r
            JOIN settlement.settlement s
              ON r.key_value = s.idempotency_key
              OR (r.correlation_id IS NOT NULL AND r.correlation_id = s.correlation_id)
            WHERE LOWER(s.status::text) = ANY(:non_terminal_statuses)
              AND r.status <> 'expired'
            GROUP BY r.key_value, s.sender_account_id
            HAVING COUNT(s.id) > 1;
        """)

        # Query B: Settlement non-terminal correlation ID duplicates
        sql_tx = text("""
            SELECT
                COALESCE(MAX(s.idempotency_key), MAX(s.correlation_id), 'unknown_key') AS key_value,
                s.sender_account_id::text AS scope,
                COUNT(*) AS execution_count,
                ARRAY_AGG(s.id::text) AS involved_object_ids,
                s.correlation_id AS correlation_id
            FROM settlement.settlement s
            WHERE LOWER(s.status::text) = ANY(:non_terminal_statuses)
              AND s.correlation_id IS NOT NULL
            GROUP BY s.correlation_id, s.sender_account_id
            HAVING COUNT(*) > 1;
        """)

        res_join = await self._execute(
            sql_join, {"non_terminal_statuses": list(NON_TERMINAL_SETTLEMENT_STATUSES)}
        )
        rows_join = res_join.fetchall()

        res_tx = await self._execute(
            sql_tx, {"non_terminal_statuses": list(NON_TERMINAL_SETTLEMENT_STATUSES)}
        )
        rows_tx = res_tx.fetchall()

        seen_keys = set()
        seen_correlations = set()
        violations = []

        for r in list(rows_join) + list(rows_tx):
            corr = str(r.correlation_id or "")
            key = (str(r.key_value), str(r.scope))
            if key in seen_keys or (corr and corr in seen_correlations):
                continue
            seen_keys.add(key)
            if corr:
                seen_correlations.add(corr)
            violations.append({
                "key_value": str(r.key_value),
                "scope": str(r.scope),
                "operation_type": "settlement_creation",
                "execution_count": int(r.execution_count),
                "involved_object_ids": list(r.involved_object_ids),
                "correlation_id": corr,
            })
        return violations

    async def _check_rail_duplicates(self) -> list[dict[str, Any]]:
        """Query rails.leg_status_update_record for multiple confirmations of the same rail reference."""
        sql = text("""
            SELECT
                u.rail_reference AS key_value,
                u.rail_id AS scope,
                COUNT(*) AS execution_count,
                ARRAY_AGG(u.id::text) AS involved_object_ids,
                MAX(u.leg_id::text) AS correlation_id
            FROM rails.leg_status_update_record u
            WHERE LOWER(u.status::text) IN ('settled', 'processing')
            GROUP BY u.rail_reference, u.rail_id
            HAVING COUNT(*) > 1;
        """)
        res = await self._execute(sql)
        rows = res.fetchall()

        violations = []
        for r in rows:
            violations.append({
                "key_value": str(r.key_value),
                "scope": str(r.scope),
                "operation_type": "rail_submission",
                "execution_count": int(r.execution_count),
                "involved_object_ids": list(r.involved_object_ids),
                "correlation_id": str(r.correlation_id or ""),
            })
        return violations

    async def _execute(self, statement, params: dict | None = None):
        import inspect

        if isinstance(self._session, AsyncSession):
            return await self._session.execute(statement, params)
        res = self._session.execute(statement, params)
        if inspect.isawaitable(res):
            return await res
        return res
