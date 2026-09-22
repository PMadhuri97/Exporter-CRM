import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.platform.audit_framework.sink import get_audit_sink_logger
from app.platform.database.services import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# Single lock key for the background dispatcher
AUDIT_DISPATCHER_LOCK_KEY = 4430003

# audit_events is the shared, append-only audit trail written by every module
# (compliance, settlement, onboarding, fx, reconciliation, ledger account
# lifecycle, ...), not just ledger postings. This dispatcher forwards to the
# ledger-posting GCP sink specifically, so it must only ever pick up rows from
# that path — otherwise every other module's audit history gets forwarded too,
# mislabeled (outcome forced to REJECTED, transaction_type defaulted to
# "posting") the moment this runs against a database with existing history.
LEDGER_POSTING_EVENT_TYPES = (
    "ledger.transaction.posted",
    "ledger.transaction.failed",
    "ledger.transaction.rejected",
)


class AuditDispatcher:
    """Background service that polls the DB for unsynced audit events,

    secures a Postgres advisory lock to ensure single-instance safety,
    and logs them to the GCP Audit Sink logger. Uses pg NOTIFY trigger for near-instant execution.
    """

    def __init__(self) -> None:
        self._notify_event = asyncio.Event()
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._listen_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the dispatcher loop and notification listener."""
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop(), name="audit-dispatcher-loop")
        self._listen_task = asyncio.create_task(self._listen_notifications(), name="audit-dispatcher-listener")
        logger.info("audit_dispatcher_started")

    async def stop(self) -> None:
        """Stop the dispatcher loop and notification listener."""
        self._running = False

        # Signal notification event to break out of wait
        self._notify_event.set()

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        logger.info("audit_dispatcher_stopped")

    async def _run_loop(self) -> None:
        """Main dispatcher loop."""
        while self._running:
            try:
                # Perform a sync run
                await self.sync_pending_events()
            except Exception as exc:  # noqa: BLE001
                logger.error("audit_dispatcher_sync_cycle_failed", error=str(exc))

            # Wait for either notification (eager trigger) or timeout (10-second polling backstop)
            try:
                await asyncio.wait_for(self._notify_event.wait(), timeout=10.0)
                self._notify_event.clear()
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                break

    async def _listen_notifications(self) -> None:
        """Listen to PG NOTIFY on audit_event_channel using a raw connection."""
        import asyncpg  # type: ignore[import-untyped]

        from app.platform.configuration.config import settings

        # Parse postgresql+asyncpg:// to postgresql:// for asyncpg direct connection
        pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

        while self._running:
            conn = None
            try:
                conn = await asyncpg.connect(pg_url)

                def handle_notification(*args: Any) -> None:
                    self._notify_event.set()

                await conn.add_listener("audit_event_channel", handle_notification)
                logger.info("audit_dispatcher_listener_connected")

                while self._running:
                    # Connection health-check keepalive
                    await conn.execute("SELECT 1")
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("audit_dispatcher_listener_connection_failed", error=str(exc))
            finally:
                if conn:
                    try:
                        await conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                if self._running:
                    await asyncio.sleep(5)  # Backoff before reconnecting

    async def sync_pending_events(self) -> None:
        """Fetch unsynced events and dispatch them to the GCP log sink."""
        async with AsyncSessionLocal() as session:
            # Try to acquire the Postgres advisory lock (session-level)
            lock_res = await session.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": AUDIT_DISPATCHER_LOCK_KEY}
            )
            locked = lock_res.scalar()
            if not locked:
                # Lock is already held by another replica instance
                return

            try:
                # Fetch a batch of unsynced events sorted chronologically (oldest first) using raw SQL
                # to respect application layering contracts (app.platform cannot import app.modules).
                # Scoped to ledger-posting event types only — see LEDGER_POSTING_EVENT_TYPES.
                stmt = text("""
                    SELECT id, payload, correlation_id, event_type, created_at
                    FROM audit.audit_events
                    WHERE synced_to_sink_at IS NULL
                      AND event_type = ANY(:event_types)
                    ORDER BY created_at ASC, id ASC
                    LIMIT 50
                """)
                result = await session.execute(stmt, {"event_types": list(LEDGER_POSTING_EVENT_TYPES)})
                events = result.fetchall()

                if not events:
                    return

                logger.info("audit_dispatcher_sync_started", batch_size=len(events))
                sink_logger = get_audit_sink_logger()

                synced_ids = []
                for event in events:
                    try:
                        # Defensive: the WHERE clause already scopes the query to
                        # LEDGER_POSTING_EVENT_TYPES, so this should be unreachable —
                        # but audit_events is shared platform-wide, and mislabeling a
                        # non-posting event as a ledger REJECTED is worse than skipping
                        # it. Never mark it synced; leave it for a human to notice.
                        if event.event_type not in LEDGER_POSTING_EVENT_TYPES:
                            logger.warning(
                                "audit_dispatcher_unexpected_event_type",
                                event_id=str(event.id),
                                event_type=event.event_type,
                            )
                            continue

                        # Extract and structure GCP payload fields
                        payload_data = event.payload or {}
                        idempotency_key = payload_data.get("idempotency_key") or ""

                        if event.correlation_id:
                            correlation_id = str(event.correlation_id)
                        else:
                            correlation_id = payload_data.get("correlation_id") or ""

                        transaction_type = payload_data.get("transaction_type") or "posting"

                        # Determine outcome from the event type string
                        if event.event_type == "ledger.transaction.posted":
                            outcome = "SUCCESS"
                        elif event.event_type == "ledger.transaction.failed":
                            outcome = "FAILED"
                        else:
                            outcome = "REJECTED"

                        rejection_reason = payload_data.get("rejection_reason") or payload_data.get("reason")
                        calling_service_identity = payload_data.get("calling_service_identity")

                        # Reconstruct extra details metadata
                        extra_fields = {
                            k: v for k, v in payload_data.items()
                            if k not in (
                                "idempotency_key",
                                "correlation_id",
                                "transaction_type",
                                "outcome",
                                "rejection_reason",
                                "calling_service_identity",
                            )
                        }

                        # Log GCP Audit entry
                        sink_logger.emit_audit_entry(
                            idempotency_key=idempotency_key,
                            correlation_id=correlation_id,
                            transaction_type=transaction_type,
                            outcome=outcome,
                            rejection_reason=rejection_reason,
                            calling_service_identity=calling_service_identity,
                            timestamp=event.created_at.isoformat(),
                            extra_fields=extra_fields,
                            event_type=event.event_type,
                        )

                        synced_ids.append(event.id)

                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "audit_dispatcher_event_dispatch_failed",
                            event_id=str(event.id),
                            error=str(exc),
                        )
                        # Skip this event and keep going — a single permanently-bad
                        # row (malformed payload, etc.) must not block every other
                        # event behind it forever. This row stays unsynced and gets
                        # retried next cycle; everything else in the batch still
                        # gets a chance to dispatch this cycle.
                        continue

                if synced_ids:
                    # Update DB records with synced timestamp
                    update_stmt = text("""
                        UPDATE audit.audit_events
                        SET synced_to_sink_at = :now
                        WHERE id = ANY(:ids)
                    """)
                    await session.execute(update_stmt, {"now": datetime.now(UTC), "ids": synced_ids})
                    await session.commit()
                    logger.info("audit_dispatcher_sync_completed", synced_count=len(synced_ids))

            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                raise exc
            finally:
                # Release Postgres advisory lock
                await session.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": AUDIT_DISPATCHER_LOCK_KEY}
                )


# Global singleton dispatcher instance
_dispatcher: AuditDispatcher | None = None


async def start_audit_dispatcher() -> None:
    """Start the global audit event background dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AuditDispatcher()
        await _dispatcher.start()


async def stop_audit_dispatcher() -> None:
    """Stop the global audit event background dispatcher."""
    global _dispatcher
    if _dispatcher is not None:
        await _dispatcher.stop()
        _dispatcher = None
