from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.database.models import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic async CRUD repository. Subclass per domain model."""

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, pk: Any) -> ModelType | None:
        return await self.session.get(self.model, pk)

    async def list(self, *, skip: int = 0, limit: int = 100) -> Sequence[ModelType]:
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def create(self, instance: ModelType) -> ModelType:
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelType) -> None:
        await self.session.delete(instance)
        await self.session.flush()


class AppendOnlyRepository(Generic[ModelType]):
    """
    Repository for append-only tables (ledger_entries, audit_events, etc.).
    No update or delete operations are exposed.
    """

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, pk: Any) -> ModelType | None:
        return await self.session.get(self.model, pk)

    async def list(self, *, skip: int = 0, limit: int = 100) -> Sequence[ModelType]:
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def create(self, instance: ModelType) -> ModelType:
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
