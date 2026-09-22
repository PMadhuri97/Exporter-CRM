import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.domain.entities.customers import BeneficiaryBankAccount, Customer
from app.platform.database.adapters.repository import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Customer, session)

    async def get_by_customer_id(self, customer_id: uuid.UUID) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, *, skip: int = 0, limit: int = 100) -> Sequence[Customer]:
        result = await self.session.execute(
            select(Customer).offset(skip).limit(limit).order_by(Customer.created_at.desc())
        )
        return result.scalars().all()


class BankAccountRepository(BaseRepository[BeneficiaryBankAccount]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BeneficiaryBankAccount, session)

    async def list_by_customer(
        self, customer_id: uuid.UUID
    ) -> Sequence[BeneficiaryBankAccount]:
        result = await self.session.execute(
            select(BeneficiaryBankAccount).where(
                BeneficiaryBankAccount.customer_id == customer_id
            )
        )
        return result.scalars().all()
