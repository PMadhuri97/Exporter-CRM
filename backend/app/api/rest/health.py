import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.configuration.config import settings
from app.platform.database.services import get_db
from app.platform.health.models import HealthResponse, ReadinessResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 if the application process is running. No dependency checks.",
    tags=["Health"],
)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Returns 200 only when all critical dependencies (database, cache) are reachable.",
    tags=["Health"],
)
async def readiness(db: AsyncSession = Depends(get_db)) -> ReadinessResponse:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as exc:
        logger.error("database_health_check_failed", error=str(exc))
        checks["database"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"

    return ReadinessResponse(
        status=overall,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        checks=checks,
        observability={
            "tracing_enabled": settings.OTEL_ENABLED,
            "metrics_endpoint": "/metrics",
            "otlp_endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            "service_name": settings.OTEL_SERVICE_NAME,
        },
    )
