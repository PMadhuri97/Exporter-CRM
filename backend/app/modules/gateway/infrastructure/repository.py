"""SQLAlchemy implementation of ``domain.ports.ApiRequestLogPort``."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.gateway.domain.entities.gateway import ApiRequestLog


class ApiRequestLogRepository:
    """Writes and commits a single ``api_request_logs`` row per call.

    Commits its own session rather than leaving that to the caller: the
    caller (``GatewayRequestLogger``) hands this repository a session created
    and owned exclusively for this one write, so there is nothing else the
    commit could interfere with.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            ApiRequestLog(
                correlation_id=correlation_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                customer_id=customer_id,
            )
        )
        await self._session.commit()
