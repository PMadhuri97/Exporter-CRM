import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.verification import Verification
from app.platform.database.adapters.repository import AppendOnlyRepository


class VerificationRepository(AppendOnlyRepository[Verification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Verification, session)

    async def list_by_customer(self, customer_id: uuid.UUID) -> Sequence[Verification]:
        result = await self.session.execute(
            select(Verification)
            .where(Verification.customer_id == customer_id)
            .order_by(Verification.created_at.desc())
        )
        return result.scalars().all()
