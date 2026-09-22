import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.domain.entities.payments import (
    IdempotencyKey,
    Transaction,
    TransactionStatusHistory,
)
from app.platform.database.adapters.repository import AppendOnlyRepository, BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Transaction, session)

    async def get_by_transaction_id(self, transaction_id: uuid.UUID) -> Transaction | None:
        result = await self.session.execute(
            select(Transaction).where(Transaction.transaction_id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Transaction | None:
        result = await self.session.execute(
            select(Transaction).where(Transaction.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def list_by_sender(
        self, sender_customer_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> Sequence[Transaction]:
        result = await self.session.execute(
            select(Transaction)
            .where(Transaction.sender_customer_id == sender_customer_id)
            .order_by(Transaction.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()


class StatusHistoryRepository(AppendOnlyRepository[TransactionStatusHistory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(TransactionStatusHistory, session)

    async def list_by_transaction(
        self, transaction_id: uuid.UUID
    ) -> Sequence[TransactionStatusHistory]:
        result = await self.session.execute(
            select(TransactionStatusHistory)
            .where(TransactionStatusHistory.transaction_id == transaction_id)
            .order_by(TransactionStatusHistory.created_at.asc())
        )
        return result.scalars().all()


class IdempotencyKeyRepository(BaseRepository[IdempotencyKey]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(IdempotencyKey, session)

    async def get_by_key(self, key: str) -> IdempotencyKey | None:
        return await self.session.get(IdempotencyKey, key)

    async def is_valid(self, key: str) -> bool:
        record = await self.get_by_key(key)
        if record is None:
            return False
        return record.expires_at > datetime.utcnow().replace(tzinfo=record.expires_at.tzinfo)
