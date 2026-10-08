"""Repository for ``exporter_profile`` rows."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.company_identity import registration_key
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    CompanyTradeRole,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
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

    async def trade_roles_for(
        self, customer_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, CompanyTradeRole]:
        """Which side of a trade each of these companies has been on.

        **Two queries for a whole page, never one per row** — the same rule the GSTINs
        follow. A company absent from the result has traded on neither side and is left
        out rather than given a role, because "no deals yet" is not a third kind of
        company.

        Every column read here is indexed (`ix_deal_company_recent`,
        `ix_deal_buyer_company_recent`, `ix_trade_relationship_seller`,
        `ix_trade_relationship_buyer`), so this stays cheap as the page grows.
        """
        if not customer_ids:
            return {}
        ids = list(customer_ids)

        async def _matching(deal_column, relationship_column) -> set[uuid.UUID]:
            result = await self.session.execute(
                select(deal_column).where(deal_column.in_(ids)).distinct()
            )
            found = set(result.scalars())
            result = await self.session.execute(
                select(relationship_column).where(relationship_column.in_(ids)).distinct()
            )
            return found | set(result.scalars())

        sellers = await _matching(Deal.company_id, TradeRelationship.seller_company_id)
        buyers = await _matching(Deal.buyer_company_id, TradeRelationship.buyer_company_id)

        roles: dict[uuid.UUID, CompanyTradeRole] = {}
        for customer_id in ids:
            sells, buys = customer_id in sellers, customer_id in buyers
            if sells and buys:
                roles[customer_id] = CompanyTradeRole.BOTH
            elif sells:
                roles[customer_id] = CompanyTradeRole.SELLER
            elif buys:
                roles[customer_id] = CompanyTradeRole.BUYER
        return roles

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
        country: str | None = None,
        industry: str | None = None,
        background_check: BackgroundCheckState | None = None,
        trade_role: CompanyTradeRole | None = None,
        has_open_deals: bool | None = None,
        exclude_ended: bool = False,
        exclude_not_in_pipeline: bool = False,
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
        if country is not None:
            # Case-insensitive and whole: a country is picked from a list, not typed,
            # so there is nothing to match partially.
            stmt = stmt.where(func.upper(ExporterProfile.country) == country.strip().upper())
        if industry is not None:
            # Partial and case-insensitive, like `name_contains`: this is typed into a
            # box a character at a time, so "ma" has to find "Marine exports" while it
            # is still being typed. A whole-value match would show nothing until the
            # last letter and read as "no such industry".
            stmt = stmt.where(
                ExporterProfile.industry.ilike(f"%{_escape_like(industry)}%", escape="\\")
            )
        if background_check is not None:
            stmt = stmt.where(ExporterProfile.background_check == background_check)
        if trade_role is not None:
            sells = _is_seller()
            buys = _is_buyer()
            if trade_role is CompanyTradeRole.SELLER:
                stmt = stmt.where(sells)
            elif trade_role is CompanyTradeRole.BUYER:
                stmt = stmt.where(buys)
            else:  # BOTH — has been on both sides, not "either".
                stmt = stmt.where(sells, buys)
        if has_open_deals is not None:
            open_deal = exists().where(
                Deal.company_id == ExporterProfile.customer_id,
                Deal.stage.in_(_OPEN_DEAL_STAGES),
            )
            stmt = stmt.where(open_deal if has_open_deals else ~open_deal)

        # `customer_id` breaks ties: companies created in one transaction share
        # a `created_at`, and without it a page boundary could repeat or skip one.
        stmt = (
            stmt.order_by(ExporterProfile.created_at.desc(), ExporterProfile.customer_id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


#: The stages a deal can still move on from. Derived from `DealStage.is_terminal`
#: rather than listed, so a fifth stage added there is classified once, in the enum
#: that owns the idea, and this query follows without being edited.
_OPEN_DEAL_STAGES = frozenset(stage for stage in DealStage if not stage.is_terminal)


def _is_seller():
    """Has this company sold — a deal of its own, or the seller side of a trade.

    Both sources, because they answer the same question at different stages: a deal is
    the live one, a trade relationship is the recorded history. A company whose only
    deal was withdrawn has still been a seller, so no stage filter here.
    """
    return exists().where(Deal.company_id == ExporterProfile.customer_id) | exists().where(
        TradeRelationship.seller_company_id == ExporterProfile.customer_id
    )


def _is_buyer():
    """Has this company been bought from — named as a deal's buyer, or the buyer side
    of a trade relationship."""
    return exists().where(Deal.buyer_company_id == ExporterProfile.customer_id) | exists().where(
        TradeRelationship.buyer_company_id == ExporterProfile.customer_id
    )


def _escape_like(value: str) -> str:
    """`value` for a LIKE pattern with a backslash as the escape character,
    so its own `%`, `_` and backslashes are matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["ExporterProfileRepository"]
