import uuid

import structlog
import structlog.contextvars
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.api.schemas import AuditEventListResponse, AuditEventResponse
from app.modules.audit.domain.entities.audit import ActorType, AuditEvent
from app.modules.audit.infrastructure.repository import AuditEventRepository
from app.modules.payments import TransactionRepository
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


def _resolve_correlation_id(explicit: uuid.UUID | None) -> uuid.UUID | None:
    """Use the explicit value if given, otherwise the request's correlation ID
    from structlog contextvars (bound by CorrelationIdMiddleware). Non-UUID
    correlation IDs are dropped rather than stored, keeping the column strongly
    typed — the transaction_id FK still ties such events together."""
    if explicit is not None:
        return explicit
    raw = structlog.contextvars.get_contextvars().get("correlation_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


class AuditService:
    """Single write path — and read path — for all audit events across every module."""

    def __init__(self, db: AsyncSession) -> None:
        self._repo = AuditEventRepository(db)
        self._tx_repo = TransactionRepository(db)

    # ── Write path ────────────────────────────────────────────────────────────

    async def record(
        self,
        event_type: str,
        *,
        transaction_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        payload: dict | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        resolved_correlation_id = _resolve_correlation_id(correlation_id)
        event = AuditEvent(
            transaction_id=transaction_id,
            correlation_id=resolved_correlation_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_type=actor_type,
            payload=payload or {},
        )
        event = await self._repo.create(event)
        logger.info(
            "audit_event_written",
            event_type=event_type,
            transaction_id=str(transaction_id) if transaction_id else None,
            correlation_id=str(resolved_correlation_id) if resolved_correlation_id else None,
            actor_type=actor_type.value,
        )
        return event

    # ── Read path (audit query API) ───────────────────────────────────────────

    async def get_event(self, event_id: uuid.UUID) -> AuditEventResponse:
        event = await self._repo.get(event_id)
        if event is None:
            raise NotFoundError(f"Audit event {event_id} not found")
        return AuditEventResponse.from_model(event)

    async def list_for_transaction(
        self, transaction_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> AuditEventListResponse:
        tx = await self._tx_repo.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundError(f"Transaction {transaction_id} not found")
        events = await self._repo.list_by_transaction(
            transaction_id, skip=offset, limit=limit
        )
        total = await self._repo.count(transaction_id=transaction_id)
        return self._page(events, total=total, limit=limit, offset=offset)

    async def list_for_correlation(
        self, correlation_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> AuditEventListResponse:
        events = await self._repo.list_by_correlation(
            correlation_id, skip=offset, limit=limit
        )
        total = await self._repo.count(correlation_id=correlation_id)
        return self._page(events, total=total, limit=limit, offset=offset)

    async def query(
        self,
        *,
        event_type: str | None = None,
        actor_type: ActorType | None = None,
        transaction_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AuditEventListResponse:
        events = await self._repo.query(
            event_type=event_type,
            actor_type=actor_type,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            skip=offset,
            limit=limit,
        )
        total = await self._repo.count(
            event_type=event_type,
            actor_type=actor_type,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
        )
        return self._page(events, total=total, limit=limit, offset=offset)

    @staticmethod
    def _page(events, *, total: int, limit: int, offset: int) -> AuditEventListResponse:
        return AuditEventListResponse(
            events=[AuditEventResponse.from_model(e) for e in events],
            total=total,
            limit=limit,
            offset=offset,
        )
