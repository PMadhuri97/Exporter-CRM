"""``CompanyGroupService`` — parent and child companies.

A company may sit under one parent, with a relationship (subsidiary, branch office,
group company, joint venture). Linking refuses a loop — a company can never be its own
ancestor — here first, by walking up from the new parent, and in the database
(``trg_exporter_profile_no_group_cycle``) for anything that bypasses this. The
**ultimate parent** is worked out on read, never stored.

The group view is the whole tree from the ultimate parent down, each member with its
stage, background check, risk, open deals and their value by currency. There are no
group-level limits or decisions.

**Possible members** are companies that share a beneficial owner with this one, matched
on the person's name (and date of birth where both records hold it). They are only ever
suggestions: a person links a company.

Every link and unlink writes a ``group`` history row on **both** companies.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

RELATIONSHIPS = ("SUBSIDIARY", "BRANCH_OFFICE", "GROUP_COMPANY", "JOINT_VENTURE")
#: How far up a chain is walked before it is treated as broken.
MAX_DEPTH = 100
_CLOSED = (DealStage.HANDED_OVER, DealStage.WITHDRAWN)


@dataclass(frozen=True)
class GroupMember:
    company_id: uuid.UUID
    name: str | None
    parent_company_id: uuid.UUID | None
    group_relationship: str | None
    depth: int
    journey: str
    background_check: str
    risk_rating: str | None
    open_deals: int
    #: Open deals' value, per currency: {"USD": Decimal("125000.00")}.
    open_deal_value: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyGroup:
    company_id: uuid.UUID
    ultimate_parent_id: uuid.UUID
    members: list[GroupMember]


@dataclass(frozen=True)
class GroupSuggestion:
    company_id: uuid.UUID
    name: str | None
    #: The people both companies record as beneficial owners.
    shared_people: list[str]


class CompanyGroupService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Link ─────────────────────────────────────────────────────────────────

    async def set_parent(
        self,
        company_id: uuid.UUID,
        *,
        parent_id: uuid.UUID | None,
        relationship: str | None,
        actor_id: str,
    ) -> ExporterProfile:
        """Put ``company_id`` under ``parent_id`` (or take it out of its group)."""
        if parent_id is not None and relationship not in RELATIONSHIPS:
            raise ValidationError("Say how the companies are related")
        if parent_id == company_id:
            raise ValidationError("A company cannot be its own parent")
        locked = await self._lock(
            {company_id, parent_id} | ({await self._parent_of(company_id)} - {None})
        )
        company = locked.get(company_id)
        if company is None:
            raise ExporterProfileNotFoundError(company_id)
        if parent_id is not None and parent_id not in locked:
            raise ExporterProfileNotFoundError(parent_id)
        if parent_id is not None and company_id in await self._ancestors(parent_id):
            raise ValidationError(
                f"{locked[parent_id].name or 'That company'} already sits under "
                f"{company.name or 'this company'}; linking it as the parent would make "
                "a loop"
            )
        old_parent_id = company.parent_company_id
        if (old_parent_id, company.group_relationship) == (
            parent_id,
            relationship if parent_id else None,
        ):
            return company

        company.parent_company_id = parent_id
        company.group_relationship = relationship if parent_id else None
        history = HistoryService(self._db)
        names = {cid: row.name for cid, row in locked.items()}
        await history.record(
            company_id,
            dimension=history_dimensions.GROUP,
            event_type="group_parent_set" if parent_id else "group_parent_cleared",
            from_value=str(old_parent_id) if old_parent_id else None,
            to_value=str(parent_id) if parent_id else "NONE",
            actor_id=actor_id,
            source="company_group_service.set_parent",
            details={
                "parent_company_id": str(parent_id) if parent_id else None,
                "parent_name": names.get(parent_id) if parent_id else None,
                "previous_parent_name": names.get(old_parent_id) if old_parent_id else None,
                "relationship": company.group_relationship,
            },
        )
        if old_parent_id is not None and old_parent_id != parent_id:
            await history.record(
                old_parent_id,
                dimension=history_dimensions.GROUP,
                event_type="group_member_removed",
                to_value=str(company_id),
                actor_id=actor_id,
                source="company_group_service.set_parent",
                details={"member_company_id": str(company_id), "member_name": company.name},
            )
        if parent_id is not None:
            await history.record(
                parent_id,
                dimension=history_dimensions.GROUP,
                event_type="group_member_added",
                to_value=str(company_id),
                actor_id=actor_id,
                source="company_group_service.set_parent",
                details={
                    "member_company_id": str(company_id),
                    "member_name": company.name,
                    "relationship": relationship,
                },
            )
        await self._db.commit()
        await self._db.refresh(company)
        logger.info(
            "company_group.parent_set",
            company_id=str(company_id),
            parent_id=str(parent_id) if parent_id else None,
            actor_id=actor_id,
        )
        return company

    # ── Read ─────────────────────────────────────────────────────────────────

    async def group(self, company_id: uuid.UUID) -> CompanyGroup:
        """The whole tree this company belongs to, from its ultimate parent down."""
        if not await self._exists(company_id):
            raise ExporterProfileNotFoundError(company_id)
        ancestors = await self._ancestors(company_id)
        root = ancestors[-1] if ancestors else company_id

        rows: dict[uuid.UUID, ExporterProfile] = {}
        depth: dict[uuid.UUID, int] = {root: 0}
        frontier = [root]
        while frontier and len(depth) < 5000:
            found = list(
                await self._db.scalars(
                    select(ExporterProfile).where(
                        (ExporterProfile.customer_id.in_(frontier))
                        | (ExporterProfile.parent_company_id.in_(frontier))
                    )
                )
            )
            next_frontier = []
            for row in found:
                rows[row.customer_id] = row
                if row.customer_id not in depth and row.parent_company_id in depth:
                    depth[row.customer_id] = depth[row.parent_company_id] + 1
                    next_frontier.append(row.customer_id)
            frontier = next_frontier

        ids = list(depth)
        open_counts: dict[uuid.UUID, int] = defaultdict(int)
        values: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(dict)
        for seller, currency, count, total in await self._db.execute(
            select(Deal.company_id, Deal.currency, func.count(), func.sum(Deal.value_amount))
            .where(Deal.company_id.in_(ids), Deal.stage.not_in(_CLOSED))
            .group_by(Deal.company_id, Deal.currency)
        ):
            open_counts[seller] += count
            if currency is not None and total is not None:
                values[seller][currency] = total

        reader = BackgroundCheckReader(self._db)
        members = []
        for member_id in sorted(ids, key=lambda cid: (depth[cid], rows[cid].name or "")):
            row = rows[member_id]
            standing = await reader.standing(member_id)
            members.append(
                GroupMember(
                    company_id=member_id,
                    name=row.name,
                    parent_company_id=row.parent_company_id if member_id != root else None,
                    group_relationship=row.group_relationship if member_id != root else None,
                    depth=depth[member_id],
                    journey=row.journey.value,
                    background_check=standing.value,
                    risk_rating=standing.risk_rating,
                    open_deals=open_counts[member_id],
                    open_deal_value=dict(values[member_id]),
                )
            )
        return CompanyGroup(company_id=company_id, ultimate_parent_id=root, members=members)

    async def suggestions(self, company_id: uuid.UUID, *, limit: int = 20) -> list[GroupSuggestion]:
        """Companies outside this one's group that share a beneficial owner with it."""
        mine = await self._people_of([company_id])
        if not mine:
            return []
        in_group = {member.company_id for member in (await self.group(company_id)).members}
        keys = {key for key, _name, _cid in mine}
        others = [
            (key, name, cid)
            for key, name, cid in await self._people_with(keys)
            if cid not in in_group
        ]
        shared: dict[uuid.UUID, set[str]] = defaultdict(set)
        for _key, name, cid in others:
            shared[cid].add(name)
        names = {
            row.customer_id: row.name
            for row in await self._db.execute(
                select(ExporterProfile.customer_id, ExporterProfile.name).where(
                    ExporterProfile.customer_id.in_(list(shared))
                )
            )
        }
        return [
            GroupSuggestion(company_id=cid, name=names.get(cid), shared_people=sorted(people))
            for cid, people in sorted(shared.items(), key=lambda item: -len(item[1]))[:limit]
        ]

    # ── Internals ────────────────────────────────────────────────────────────

    async def _exists(self, company_id: uuid.UUID) -> bool:
        return (
            await self._db.scalar(
                select(ExporterProfile.customer_id).where(
                    ExporterProfile.customer_id == company_id
                )
            )
            is not None
        )

    async def _parent_of(self, company_id: uuid.UUID) -> uuid.UUID | None:
        return await self._db.scalar(
            select(ExporterProfile.parent_company_id).where(
                ExporterProfile.customer_id == company_id
            )
        )

    async def _ancestors(self, company_id: uuid.UUID) -> list[uuid.UUID]:
        """Parent, grandparent, ... up to the ultimate parent."""
        chain: list[uuid.UUID] = []
        current = await self._parent_of(company_id)
        while current is not None and current not in chain and len(chain) < MAX_DEPTH:
            chain.append(current)
            current = await self._parent_of(current)
        return chain

    async def _lock(self, ids: set) -> dict[uuid.UUID, ExporterProfile]:
        wanted = sorted((cid for cid in ids if cid is not None), key=str)
        rows = await self._db.scalars(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id.in_(wanted))
            .order_by(ExporterProfile.customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {row.customer_id: row for row in rows}

    @staticmethod
    def _person_key(record: UboRecord) -> str:
        name = f"{record.first_name} {record.last_name}".strip().lower()
        return f"{' '.join(name.split())}|{(record.date_of_birth or '').strip()}"

    async def _people_of(self, company_ids: list[uuid.UUID]) -> list[tuple[str, str, uuid.UUID]]:
        rows = await self._db.execute(
            select(UboRecord, OnboardingRequest.customer_id)
            .join(OnboardingRequest, OnboardingRequest.id == UboRecord.onboarding_request_id)
            .where(OnboardingRequest.customer_id.in_(company_ids))
        )
        return [
            (self._person_key(ubo), f"{ubo.first_name} {ubo.last_name}".strip(), cid)
            for ubo, cid in rows
        ]

    async def _people_with(self, keys: set[str]) -> list[tuple[str, str, uuid.UUID]]:
        """Every recorded beneficial owner whose name (and birth date) matches a key."""
        names = {key.split("|", 1)[0] for key in keys}
        rows = await self._db.execute(
            select(UboRecord, OnboardingRequest.customer_id)
            .join(OnboardingRequest, OnboardingRequest.id == UboRecord.onboarding_request_id)
            .where(
                func.lower(
                    func.concat(func.trim(UboRecord.first_name), " ", func.trim(UboRecord.last_name))
                ).in_(names)
            )
        )
        # A name matches when the birth dates agree, or when either record lacks one.
        births: dict[str, set[str]] = defaultdict(set)
        for key in keys:
            name, _, birth = key.partition("|")
            births[name].add(birth)
        out = []
        for ubo, cid in rows:
            key = self._person_key(ubo)
            name, _, birth = key.partition("|")
            known = births.get(name, set())
            if birth in known or "" in known or (not birth and known):
                out.append((key, f"{ubo.first_name} {ubo.last_name}".strip(), cid))
        return out


__all__ = ["CompanyGroup", "CompanyGroupService", "GroupMember", "GroupSuggestion", "RELATIONSHIPS"]
