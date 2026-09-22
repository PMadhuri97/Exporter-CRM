import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.domain.entities.audit import ActorType, AuditEvent
from app.platform.database.adapters.repository import AppendOnlyRepository


class AuditEventRepository(AppendOnlyRepository[AuditEvent]):
    """Write-only. DB trigger prevents UPDATE and DELETE on audit_events."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditEvent, session)

    @staticmethod
    def _filters(
        *,
        event_type: str | None = None,
        actor_type: ActorType | None = None,
        transaction_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if event_type is not None:
            conditions.append(AuditEvent.event_type == event_type)
        if actor_type is not None:
            conditions.append(AuditEvent.actor_type == actor_type)
        if transaction_id is not None:
            conditions.append(AuditEvent.transaction_id == transaction_id)
        if correlation_id is not None:
            conditions.append(AuditEvent.correlation_id == correlation_id)
        return conditions

    async def list_by_transaction(
        self, transaction_id: uuid.UUID, *, skip: int = 0, limit: int = 200
    ) -> Sequence[AuditEvent]:
        """Chronological (oldest → newest) — reconstructs a transaction's lifecycle."""
        result = await self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.transaction_id == transaction_id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_correlation(
        self, correlation_id: uuid.UUID, *, skip: int = 0, limit: int = 200
    ) -> Sequence[AuditEvent]:
        """Chronological — every audit event across services sharing a correlation ID."""
        result = await self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.correlation_id == correlation_id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def query(
        self,
        *,
        event_type: str | None = None,
        actor_type: ActorType | None = None,
        transaction_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditEvent]:
        """Global filtered feed — most recent first."""
        result = await self.session.execute(
            select(AuditEvent)
            .where(*self._filters(
                event_type=event_type,
                actor_type=actor_type,
                transaction_id=transaction_id,
                correlation_id=correlation_id,
            ))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def count(
        self,
        *,
        event_type: str | None = None,
        actor_type: ActorType | None = None,
        transaction_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(*self._filters(
                event_type=event_type,
                actor_type=actor_type,
                transaction_id=transaction_id,
                correlation_id=correlation_id,
            ))
        )
        return int(result.scalar_one())
