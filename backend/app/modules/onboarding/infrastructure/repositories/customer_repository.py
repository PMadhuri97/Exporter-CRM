import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.customer import Customer
from app.platform.database.adapters.repository import BaseRepository


class OnboardingCustomerRepository(BaseRepository[Customer]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Customer, session)

    async def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        return await self.get(customer_id)

    async def get_by_email(self, email: str) -> Customer | None:
        result = await self.session.execute(select(Customer).where(Customer.email == email))
        return result.scalar_one_or_none()

    async def get_by_external_user_id(self, external_user_id: str) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.external_user_id == external_user_id)
        )
        return result.scalar_one_or_none()
