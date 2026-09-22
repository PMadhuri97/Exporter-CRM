"""Gateway application services: request logging and health aggregation.

Kept out of api/ per ARCHITECTURE.md §3 ("api/ contains no business logic") —
every decision ("is this request worth persisting", "is the database healthy")
lives here, leaving api/router.py and application/middleware.py as thin wiring.
"""
import time
import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.database.services as database
from app.modules.gateway.infrastructure.repository import ApiRequestLogRepository

logger = structlog.get_logger(__name__)


class GatewayRequestLogger:
    """Writes one ``api_request_logs`` row per request the gateway observed.

    Uses its own session, independent of whatever session a matched route
    handler used, so a logging failure can never roll back — or be rolled
    back by — the business transaction it is describing. Failures are caught
    and logged, never raised: an audit-trail write must not turn an
    otherwise-successful customer-facing response into a 500.

    Reads ``database.AsyncSessionLocal`` through the module (not imported by
    name) so it always sees the session factory current at call time — tests
    swap it for a NullPool engine (see backend/conftest.py's
    ``_use_nullpool_engine``), and a name-bound import here would keep using
    the pre-swap pooled engine for the lifetime of the process.
    """

    async def record(
        self,
        *,
        correlation_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        customer_id: uuid.UUID | None = None,
    ) -> None:
        try:
            async with database.AsyncSessionLocal() as session:
                await ApiRequestLogRepository(session).record(
                    correlation_id=correlation_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    customer_id=customer_id,
                )
        except Exception as exc:  # noqa: BLE001 — must never break the request it logs
            logger.error(
                "api_request_log_write_failed",
                correlation_id=correlation_id,
                path=path,
                error=str(exc),
            )


class GatewayHealthService:
    """Checks the gateway's declared dependencies.

    Exactly one today — the database — because there is nothing else to route
    to yet; later Epic 4.4 stories add the services the gateway proxies to.
    The per-dependency breakdown is a dict keyed by dependency name precisely
    so a new dependency is a new key, not a response-shape change: an existing
    caller reading ``dependencies["database"]`` is unaffected by a
    ``dependencies["payments_service"]`` key appearing beside it later.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check(self) -> tuple[str, dict[str, dict[str, str]]]:
        dependencies: dict[str, dict[str, str]] = {}

        start = time.perf_counter()
        try:
            await self._db.execute(text("SELECT 1"))
            dependencies["database"] = {
                "status": "healthy",
                "latency_ms": str(round((time.perf_counter() - start) * 1000, 2)),
            }
        except Exception as exc:  # noqa: BLE001 — a failed check is reported, not raised
            logger.error("gateway_health_check_failed", dependency="database", error=str(exc))
            dependencies["database"] = {"status": "unhealthy", "detail": "connection failed"}

        overall = (
            "healthy"
            if all(dep["status"] == "healthy" for dep in dependencies.values())
            else "degraded"
        )
        return overall, dependencies
