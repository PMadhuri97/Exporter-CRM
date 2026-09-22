import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.compliance import (
    ApproverRole,
    ComplianceApproval,
    ComplianceCase,
    ComplianceScreening,
)
from app.platform.database.adapters.repository import AppendOnlyRepository


class ScreeningRepository(AppendOnlyRepository[ComplianceScreening]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ComplianceScreening, session)

    async def list_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[ComplianceScreening]:
        result = await self.session.execute(
            select(ComplianceScreening)
            .where(ComplianceScreening.transaction_id == transaction_id)
            .order_by(ComplianceScreening.created_at.asc())
        )
        return result.scalars().all()


class ApprovalRepository(AppendOnlyRepository[ComplianceApproval]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ComplianceApproval, session)

    async def list_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[ComplianceApproval]:
        result = await self.session.execute(
            select(ComplianceApproval)
            .where(ComplianceApproval.transaction_id == transaction_id)
            .order_by(ComplianceApproval.created_at.asc())
        )
        return result.scalars().all()

    async def get_maker(self, transaction_id: uuid.UUID) -> ComplianceApproval | None:
        result = await self.session.execute(
            select(ComplianceApproval).where(
                ComplianceApproval.transaction_id == transaction_id,
                ComplianceApproval.approver_role == ApproverRole.MAKER,
            )
        )
        return result.scalar_one_or_none()

    async def get_checker(self, transaction_id: uuid.UUID) -> ComplianceApproval | None:
        result = await self.session.execute(
            select(ComplianceApproval).where(
                ComplianceApproval.transaction_id == transaction_id,
                ComplianceApproval.approver_role == ApproverRole.CHECKER,
            )
        )
        return result.scalar_one_or_none()


class CaseRepository(AppendOnlyRepository[ComplianceCase]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ComplianceCase, session)

    async def list_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[ComplianceCase]:
        result = await self.session.execute(
            select(ComplianceCase)
            .where(ComplianceCase.transaction_id == transaction_id)
            .order_by(ComplianceCase.created_at.asc())
        )
        return result.scalars().all()
