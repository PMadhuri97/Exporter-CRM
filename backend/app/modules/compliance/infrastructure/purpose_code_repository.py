from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.registry import (
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)
from app.modules.compliance.domain.ports import PurposeCodeRepository


class SQLAlchemyPurposeCodeRepository(PurposeCodeRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_canonical_history(self, canonical_code: str) -> list[PurposeCodeCanonical]:
        # Every row for this code, oldest first. A code with no history at all
        # (never retired/reinstated) returns a single-element list, so callers
        # do not need a special case for the common case.
        stmt = (
            select(PurposeCodeCanonical)
            .where(PurposeCodeCanonical.canonical_code == canonical_code)
            .order_by(PurposeCodeCanonical.effective_from.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_corridor_mappings(
        self, canonical_code: str, corridor_id: str
    ) -> list[PurposeCodeCorridorMapping]:
        stmt = select(PurposeCodeCorridorMapping).where(
            PurposeCodeCorridorMapping.canonical_code == canonical_code,
            PurposeCodeCorridorMapping.corridor_id == corridor_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_mappings(
        self, corridor_id: str, external_code: str
    ) -> list[PurposeCodeCorridorMapping]:
        # 'external_code' here corresponds to 'external_code' in the new schema
        stmt = select(PurposeCodeCorridorMapping).where(
            PurposeCodeCorridorMapping.corridor_id == corridor_id,
            PurposeCodeCorridorMapping.external_code == external_code,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
