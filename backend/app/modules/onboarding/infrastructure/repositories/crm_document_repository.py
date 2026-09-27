"""Repository for ``crm_document`` — **owner: Developer 3B** (L3-09).

Mutable in one respect only: the scan status moves once a verdict arrives.
Everything else about a stored document is fixed — there is no edit route, and
replacing a document means uploading a new one — so this exposes reads, a create
and a status update, and nothing that rewrites a file's own details.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.document_enums import DocumentCategory
from app.platform.database.adapters.repository import BaseRepository


class CrmDocumentRepository(BaseRepository[CrmDocument]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CrmDocument, session)

    async def get_by_id(self, document_id: uuid.UUID) -> CrmDocument | None:
        result = await self.session.execute(
            select(CrmDocument).where(CrmDocument.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_storage_key(self, storage_key: str) -> CrmDocument | None:
        """The row for one stored object.

        Used by the download route, which is handed a signed key rather than a
        document id: the signature covers the key, so the key is what identifies
        the row. `uq_crm_document_storage_key` is what makes this unambiguous.
        """
        result = await self.session.execute(
            select(CrmDocument).where(CrmDocument.storage_key == storage_key)
        )
        return result.scalar_one_or_none()

    def _owned_by(
        self, *, company_id: uuid.UUID | None, deal_id: uuid.UUID | None
    ) -> Select[tuple[CrmDocument]]:
        statement = select(CrmDocument)
        if company_id is not None:
            return statement.where(CrmDocument.company_id == company_id)
        return statement.where(CrmDocument.deal_id == deal_id)

    async def list_for_owner(
        self,
        *,
        company_id: uuid.UUID | None = None,
        deal_id: uuid.UUID | None = None,
        categories: tuple[DocumentCategory, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CrmDocument], int]:
        """One owner's documents, newest upload first, with the total behind the
        page. Exactly one of ``company_id`` and ``deal_id`` is given — the caller's
        own rule, mirroring ``ck_crm_document_one_owner``."""
        statement = self._owned_by(company_id=company_id, deal_id=deal_id)
        if categories:
            statement = statement.where(CrmDocument.category.in_(categories))

        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        result = await self.session.execute(
            statement.order_by(CrmDocument.uploaded_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_for_deal_ids(
        self, deal_ids: tuple[uuid.UUID, ...]
    ) -> list[CrmDocument]:
        """Every document on any of these deals.

        One statement rather than one per deal: Phase 4's handover snapshot needs
        the document ids for a deal at the moment it is handed over, and a company
        panel counting paperwork across deals asks the same question.
        """
        if not deal_ids:
            return []
        result = await self.session.execute(
            select(CrmDocument).where(CrmDocument.deal_id.in_(deal_ids))
        )
        return list(result.scalars().all())
