"""SQLAlchemy reader for the sector registry."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    SectorCodeExternalMapping,
    SectorCodeRegistry,
    SectorRiskClassification,
)
from app.modules.compliance.domain.ports import SectorRiskRepository


class SQLAlchemySectorRiskRepository(SectorRiskRepository):
    """Returns rows as stored. Effective-date filtering belongs to the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_sector(self, sector_code: str) -> SectorCodeRegistry | None:
        stmt = select(SectorCodeRegistry).where(SectorCodeRegistry.sector_code == sector_code)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_classifications(
        self,
        sector_code: str,
        jurisdiction_type: JurisdictionType,
        jurisdiction_value: str,
    ) -> list[SectorRiskClassification]:
        stmt = select(SectorRiskClassification).where(
            SectorRiskClassification.sector_code == sector_code,
            SectorRiskClassification.jurisdiction_type == jurisdiction_type,
            SectorRiskClassification.jurisdiction_value == jurisdiction_value,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_external_mappings(
        self, sector_code: str, external_standard: str
    ) -> list[SectorCodeExternalMapping]:
        stmt = select(SectorCodeExternalMapping).where(
            SectorCodeExternalMapping.sector_code == sector_code,
            SectorCodeExternalMapping.external_standard == external_standard,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
