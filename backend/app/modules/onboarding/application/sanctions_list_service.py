"""``SanctionsListService`` — the sanctions lists administrators keep.

A list is its ``code``. Adding one writes version 1; any change — its name, whether it
is active or mandatory, or a **new version date** of the published list — writes the
next version and supersedes the old one, so a run keeps the exact list version it
screened against. Recording a newer version date is what puts companies on the
"Re-screen due" worklist.
"""

from __future__ import annotations

from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.sanctions import SanctionsList
from app.modules.onboarding.exceptions import SanctionsListNotFoundError
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)


class SanctionsListService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def current(self) -> list[SanctionsList]:
        """The current version of every list, inactive ones included, by name."""
        return list(
            await self._db.scalars(
                select(SanctionsList)
                .where(SanctionsList.is_current.is_(True))
                .order_by(SanctionsList.name)
            )
        )

    async def history(self) -> list[SanctionsList]:
        return list(
            await self._db.scalars(
                select(SanctionsList).order_by(SanctionsList.code, SanctionsList.version.desc())
            )
        )

    async def add(
        self,
        *,
        code: str,
        name: str,
        authority: str | None,
        mandatory: bool,
        list_version_date: date,
        actor_id: str,
    ) -> SanctionsList:
        code = code.strip().upper()
        if await self._db.scalar(select(SanctionsList.id).where(SanctionsList.code == code)):
            raise ValidationError(f"A sanctions list with the code {code} already exists")
        row = SanctionsList(
            code=code,
            version=1,
            name=name.strip(),
            authority=(authority or "").strip() or None,
            mandatory=mandatory,
            list_version_date=list_version_date,
            created_by=actor_id,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        logger.info("sanctions_list.added", code=code, actor_id=actor_id)
        return row

    async def revise(
        self,
        code: str,
        *,
        name: str | None,
        authority: str | None,
        authority_sent: bool,
        active: bool | None,
        mandatory: bool | None,
        list_version_date: date | None,
        actor_id: str,
    ) -> SanctionsList:
        old = await self._db.scalar(
            select(SanctionsList)
            .where(SanctionsList.code == code, SanctionsList.is_current.is_(True))
            .with_for_update()
        )
        if old is None:
            raise SanctionsListNotFoundError(code)
        new = {
            "name": (name or old.name).strip(),
            "authority": ((authority or "").strip() or None) if authority_sent else old.authority,
            "active": old.active if active is None else active,
            "mandatory": old.mandatory if mandatory is None else mandatory,
            "list_version_date": list_version_date or old.list_version_date,
        }
        if new["list_version_date"] < old.list_version_date:
            raise ValidationError("A list's version date cannot go back in time")
        if all(getattr(old, key) == value for key, value in new.items()):
            raise ValidationError("That leaves the list as it already is")
        old.is_current = False
        await self._db.flush()
        row = SanctionsList(
            code=old.code, version=old.version + 1, created_by=actor_id, **new
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        logger.info("sanctions_list.revised", code=code, version=row.version, actor_id=actor_id)
        return row


__all__ = ["SanctionsListService"]
