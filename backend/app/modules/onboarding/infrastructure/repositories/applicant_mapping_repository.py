import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.applicant_mapping import ApplicantMapping
from app.platform.database.adapters.repository import BaseRepository


class ApplicantMappingRepository(BaseRepository[ApplicantMapping]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ApplicantMapping, session)

    async def get_by_customer(self, customer_id: uuid.UUID) -> ApplicantMapping | None:
        result = await self.session.execute(
            select(ApplicantMapping).where(ApplicantMapping.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_applicant_id(self, applicant_id: str) -> ApplicantMapping | None:
        result = await self.session.execute(
            select(ApplicantMapping).where(ApplicantMapping.applicant_id == applicant_id)
        )
        return result.scalar_one_or_none()
