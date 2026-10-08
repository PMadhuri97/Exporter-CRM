"""Repository for ``exporter_profile`` rows."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.company_identity import registration_key
from app.modules.onboarding.domain.entities.engagement_enums import ContactStatus
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.platform.authentication.models import User
from app.platform.database.adapters.repository import BaseRepository


class ExporterProfileRepository(BaseRepository[ExporterProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExporterProfile, session)

    async def get_by_customer_id(self, customer_id: uuid.UUID) -> ExporterProfile | None:
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_pan(self, pan: str) -> ExporterProfile | None:
        """The company holding ``pan`` — at most one (``uq_exporter_profile_pan``)."""
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.pan == pan)
        )
        return result.scalar_one_or_none()

    async def get_by_registration_number(
        self, *, country: str, registration_number: str
    ) -> ExporterProfile | None:
        """The company holding this registration number in this country — at most
        one (``uq_exporter_profile_country_registration_number``).

        Matched through the index's own expression, written here as the same SQL,
        so this finds exactly the row the constraint would refuse. Comparing the
        stored text instead would miss ``KVK 12.345`` when asked for ``kvk-12345``
        and report "no holder" for a number the insert then rejects.
        """
        normalised = func.upper(
            func.regexp_replace(ExporterProfile.registration_number, "[^A-Za-z0-9]", "", "g")
        )
        wanted = registration_key(registration_number)
        result = await self.session.execute(
            select(ExporterProfile).where(
                ExporterProfile.country == country.strip().upper(),
                ExporterProfile.registration_number.isnot(None),
                normalised == wanted,
            )
        )
        return result.scalar_one_or_none()

    async def get_many(self, customer_ids: Sequence[uuid.UUID]) -> list[ExporterProfile]:
        if not customer_ids:
            return []
        result = await self.session.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id.in_(customer_ids))
        )
        return list(result.scalars().all())

    async def holders_of_identifiers(
        self,
        *,
        gstins: Sequence[str] = (),
        iec: str | None = None,
        cin: str | None = None,
    ) -> dict[uuid.UUID, set[str]]:
        """Every company holding any of these identifiers, with which ones it
        holds (`"gstin"`, `"iec"`, `"cin"`). PAN is looked up on its own: it
        is unique, and says which company a row *is*, not which it resembles."""
        holders: dict[uuid.UUID, set[str]] = {}
        if gstins:
            result = await self.session.execute(
                select(ExporterGstin.customer_id).where(ExporterGstin.gstin.in_(gstins)).distinct()
            )
            for customer_id in result.scalars():
                holders.setdefault(customer_id, set()).add("gstin")
        for column, value, label in (
            (ExporterProfile.iec, iec, "iec"),
            (ExporterProfile.cin, cin, "cin"),
        ):
            if value is None:
                continue
            result = await self.session.execute(
                select(ExporterProfile.customer_id).where(column == value)
            )
            for customer_id in result.scalars():
                holders.setdefault(customer_id, set()).add(label)
        return holders

    async def other_holders_of_gstins(
        self, gstins: Sequence[str], customer_id: uuid.UUID
    ) -> dict[str, list[uuid.UUID]]:
        """For each of ``gstins`` that another company also holds, those
        companies' ids. GSTINs nobody else holds are absent."""
        if not gstins:
            return {}
        result = await self.session.execute(
            select(ExporterGstin.gstin, ExporterGstin.customer_id)
            .where(
                ExporterGstin.gstin.in_(gstins),
                ExporterGstin.customer_id != customer_id,
            )
            .order_by(ExporterGstin.gstin, ExporterGstin.customer_id)
        )
        holders: dict[str, list[uuid.UUID]] = {}
        for gstin, holder in result.all():
            holders.setdefault(gstin, []).append(holder)
        return holders

    async def search(
        self,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        name_contains: str | None = None,
        source: ExporterSource | None = None,
        journey: ExporterJourney | None = None,
        qualification: QualificationState | None = None,
        marker: ExporterMarker | None = None,
        pipeline_status: CompanyPipelineStatus | None = None,
        exclude_ended: bool = False,
        exclude_not_in_pipeline: bool = False,
        relationship_manager_user_id: uuid.UUID | None = None,
        relationship_manager_unassigned: bool = False,
        relationship_manager_inactive: bool = False,
        missing_primary_contact: bool = False,
        collections_owner_user_id: uuid.UUID | None = None,
        collections_owner_unassigned: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfile]:
        """Filtered profile search, newest first.

        ``name_contains`` is a case-insensitive partial match on the name,
        taken literally: ``%`` and ``_`` in it match only themselves.
        ``gstin`` matches any of a company's GSTINs. ``exclude_ended`` drops
        ``ENDED`` companies and ``exclude_not_in_pipeline`` drops buyer-only ones
        — the service decides when (the default working list); this query only
        applies them.
        """
        stmt = select(ExporterProfile)
        if relationship_manager_user_id is not None:
            stmt = stmt.where(
                ExporterProfile.relationship_manager_user_id == relationship_manager_user_id
            )
        if relationship_manager_unassigned:
            stmt = stmt.where(ExporterProfile.relationship_manager_user_id.is_(None))
        if relationship_manager_inactive:
            stmt = stmt.where(
                ExporterProfile.relationship_manager_user_id.in_(
                    select(User.id).where(User.is_active.is_(False))
                )
            )
        if missing_primary_contact:
            stmt = stmt.where(~_has_active_primary_contact())
        if collections_owner_user_id is not None:
            stmt = stmt.where(ExporterProfile.collections_owner_user_id == collections_owner_user_id)
        if collections_owner_unassigned:
            stmt = stmt.where(ExporterProfile.collections_owner_user_id.is_(None))
        if gstin is not None:
            stmt = stmt.where(
                exists().where(
                    ExporterGstin.customer_id == ExporterProfile.customer_id,
                    ExporterGstin.gstin == gstin,
                )
            )
        if pan is not None:
            stmt = stmt.where(ExporterProfile.pan == pan)
        if iec is not None:
            stmt = stmt.where(ExporterProfile.iec == iec)
        if name_contains is not None:
            stmt = stmt.where(
                ExporterProfile.name.ilike(f"%{_escape_like(name_contains)}%", escape="\\")
            )
        if source is not None:
            stmt = stmt.where(ExporterProfile.source == source)
        if journey is not None:
            stmt = stmt.where(ExporterProfile.journey == journey)
        if qualification is not None:
            stmt = stmt.where(ExporterProfile.qualification == qualification)
        if marker is not None:
            stmt = stmt.where(ExporterProfile.marker == marker)
        elif exclude_ended:
            stmt = stmt.where(ExporterProfile.marker != ExporterMarker.ENDED)
        if pipeline_status is not None:
            stmt = stmt.where(ExporterProfile.pipeline_status == pipeline_status)
        elif exclude_not_in_pipeline:
            stmt = stmt.where(
                ExporterProfile.pipeline_status != CompanyPipelineStatus.NOT_IN_PIPELINE
            )

        # `customer_id` breaks ties: companies created in one transaction share
        # a `created_at`, and without it a page boundary could repeat or skip one.
        stmt = (
            stmt.order_by(ExporterProfile.created_at.desc(), ExporterProfile.customer_id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def owned_by(
        self,
        user_id: uuid.UUID,
        *,
        company_ids: Sequence[uuid.UUID] | None = None,
        journey: ExporterJourney | None = None,
    ) -> list[uuid.UUID]:
        """The companies whose RM is ``user_id``, optionally narrowed to ``company_ids``
        and a journey stage, in ``customer_id`` order — the order a bulk reassignment
        locks them in, so two bulk runs never deadlock on each other."""
        stmt = select(ExporterProfile.customer_id).where(
            ExporterProfile.relationship_manager_user_id == user_id
        )
        if company_ids is not None:
            stmt = stmt.where(ExporterProfile.customer_id.in_(list(company_ids)))
        if journey is not None:
            stmt = stmt.where(ExporterProfile.journey == journey)
        result = await self.session.execute(stmt.order_by(ExporterProfile.customer_id))
        return list(result.scalars().all())


def _escape_like(value: str) -> str:
    """`value` for a LIKE pattern with a backslash as the escape character,
    so its own `%`, `_` and backslashes are matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["ExporterProfileRepository"]


def _has_active_primary_contact():
    """The company has a primary contact who is still active."""
    return exists().where(
        ExporterContact.customer_id == ExporterProfile.customer_id,
        ExporterContact.is_primary_contact.is_(True),
        ExporterContact.status == ContactStatus.ACTIVE.value,
    )


async def companies_with_active_primary_contact(
    db: AsyncSession, customer_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of ``customer_ids`` have an active primary contact — one query for a page."""
    if not customer_ids:
        return set()
    rows = await db.scalars(
        select(ExporterContact.customer_id).where(
            ExporterContact.customer_id.in_(customer_ids),
            ExporterContact.is_primary_contact.is_(True),
            ExporterContact.status == ContactStatus.ACTIVE.value,
        )
    )
    return set(rows)
