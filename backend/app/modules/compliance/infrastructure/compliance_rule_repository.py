"""SQLAlchemy reader for the compliance rule registry."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.ports import ComplianceRuleRepository


class SQLAlchemyComplianceRuleRepository(ComplianceRuleRepository):
    """Returns rows as stored. Effective-date filtering belongs to the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_rules(self) -> list[ComplianceRule]:
        stmt = select(ComplianceRule)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
