"""Repository for ``deal``.

Mutable, unlike the append-only tables in this module: a deal's stage genuinely
changes, and the record of *how* it changed is a history row
(``dimension="deal"``), not a second deal row. So this extends
``BaseRepository`` — but note there is deliberately **no delete path used
anywhere**: ``WITHDRAWN`` is how a deal ends (deal contract §2), and the base
class's ``delete`` is simply never called.

The buyer is loaded with the deal (``lazy="selectin"`` on the relationship), so a
list of deals costs two statements rather than one per row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, String, and_, case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.onboarding.domain.deal_views import UNKNOWN_CORRIDOR, DealFilters
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database.adapters.repository import BaseRepository

_Seller = aliased(ExporterProfile, name="seller")
_BuyerCompany = aliased(ExporterProfile, name="buyer_company")

# The buyer is the company once the deal names one, and the older `deal_buyer`
# details until then — the same authority `DealService` gives them on one deal.
_BUYER_NAME = case(
    (Deal.buyer_company_id.is_not(None), _BuyerCompany.name), else_=DealBuyer.name
)
_BUYER_COUNTRY = case(
    (Deal.buyer_company_id.is_not(None), _BuyerCompany.country), else_=DealBuyer.country
)
# Seller's country, then buyer's: "IN-US". NULL while either is unknown. The hyphen
# is inlined rather than bound: `corridor_counts` groups by this expression, and
# Postgres only matches the SELECT to the GROUP BY when they are textually equal,
# which two separately numbered parameters are not.
_CORRIDOR = case(
    (
        and_(_Seller.country.is_not(None), _BUYER_COUNTRY.is_not(None)),
        _Seller.country.op("||", return_type=String)(literal_column("'-'")).op(
            "||", return_type=String
        )(_BUYER_COUNTRY),
    ),
    else_=None,
)


def _with_parties(statement: Select[Any]) -> Select[Any]:
    return (
        statement.select_from(Deal)
        .join(_Seller, _Seller.customer_id == Deal.company_id)
        .outerjoin(_BuyerCompany, _BuyerCompany.customer_id == Deal.buyer_company_id)
        .outerjoin(DealBuyer, DealBuyer.deal_id == Deal.id)
    )


def _escape_like(value: str) -> str:
    """`value` for a LIKE pattern with a backslash as the escape character,
    so its own `%`, `_` and backslashes are matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DealRepository(BaseRepository[Deal]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Deal, session)

    async def get_by_id(self, deal_id: uuid.UUID) -> Deal | None:
        result = await self.session.execute(select(Deal).where(Deal.id == deal_id))
        return result.scalar_one_or_none()

    async def lock_by_id(self, deal_id: uuid.UUID) -> Deal | None:
        """The deal row, locked for the rest of the transaction and read fresh.

        Two concurrent stage moves are then judged one after the other, and the
        second sees the first — so the history can never show two moves out of the
        same stage. The same reason ``ConversationService._lock_profile`` and
        ``QualificationService`` lock.

        ``populate_existing`` matters as much as the lock: without it a row
        already in this session's identity map would be returned from memory, and
        the guard would judge a stale stage.
        """
        result = await self.session.execute(
            select(Deal)
            .where(Deal.id == deal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    def _for_company(self, company_id: uuid.UUID) -> Select[tuple[Deal]]:
        return select(Deal).where(Deal.company_id == company_id)

    def _for_buyer_company(self, company_id: uuid.UUID) -> Select[tuple[Deal]]:
        """Deals this company is the **buyer** on.

        Only ``buyer_company_id``, never the legacy ``deal_buyer`` row: a
        ``deal_buyer`` is a set of details, not a company, so there is nothing to
        match it to a company by. A deal the buyer migration has not reached yet
        therefore does not appear here — correctly, because until it does, nothing
        in the database says that buyer *is* this company.
        """
        return select(Deal).where(Deal.buyer_company_id == company_id)

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        stages: tuple[DealStage, ...] | None = None,
        as_buyer: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Deal], int]:
        """One company's deals, newest first, with the total behind the page.

        ``as_buyer`` lists the deals it buys on instead of the ones it sells on.
        Never both at once: a company could be seller on one deal and buyer on
        another, and a single list mixing the two would show a stage and a buyer
        name whose meaning flipped row by row. The two sides are separate questions
        and the screen asks them separately.

        Newest first because the deal someone is working on is almost always the one
        they just opened; ``ix_deal_company_recent`` and
        ``ix_deal_buyer_company_recent`` serve exactly these two queries.
        """
        statement = (
            self._for_buyer_company(company_id) if as_buyer else self._for_company(company_id)
        )
        if stages:
            statement = statement.where(Deal.stage.in_(stages))

        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        result = await self.session.execute(
            statement.order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_all(
        self, filters: DealFilters, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Any], int]:
        """Every deal matching ``filters``, newest first, with both parties and the
        corridor worked out, and the total behind the page.

        One statement per page, whatever its length: the parties are joined, not
        loaded per row. Rows carry ``id, reference, stage, seller_company_id,
        seller_name, seller_country, buyer_company_id, buyer_name, buyer_country,
        corridor, created_at, updated_at``.
        """
        statement = _with_parties(
            select(
                Deal.id,
                Deal.reference,
                Deal.stage,
                Deal.company_id.label("seller_company_id"),
                _Seller.name.label("seller_name"),
                _Seller.country.label("seller_country"),
                Deal.buyer_company_id,
                _BUYER_NAME.label("buyer_name"),
                _BUYER_COUNTRY.label("buyer_country"),
                _CORRIDOR.label("corridor"),
                Deal.created_at,
                Deal.updated_at,
                Deal.value_amount,
                Deal.currency,
            )
        ).where(*self._conditions(filters))

        total = await self.session.scalar(
            _with_parties(select(func.count())).where(*self._conditions(filters))
        )
        result = await self.session.execute(
            statement.order_by(Deal.created_at.desc(), Deal.id.desc()).limit(limit).offset(offset)
        )
        return list(result.all()), int(total or 0)

    async def corridor_counts(self) -> list[tuple[str | None, int]]:
        """Every corridor some deal is on, with how many deals, across all deals —
        not the filtered ones, so the choices on offer do not vanish as filters are
        applied. Known corridors alphabetically, then the unknown ones."""
        result = await self.session.execute(
            _with_parties(select(_CORRIDOR.label("corridor"), func.count()))
            .group_by(_CORRIDOR)
            .order_by(_CORRIDOR.asc().nulls_last())
        )
        return [(row[0], int(row[1])) for row in result.all()]

    @staticmethod
    def _conditions(filters: DealFilters) -> list[Any]:
        conditions: list[Any] = []
        if filters.corridors:
            known = [value for value in filters.corridors if value != UNKNOWN_CORRIDOR]
            either = []
            if known:
                either.append(_CORRIDOR.in_(known))
            if UNKNOWN_CORRIDOR in filters.corridors:
                either.append(_CORRIDOR.is_(None))
            conditions.append(or_(*either))
        if filters.stages:
            conditions.append(Deal.stage.in_(filters.stages))
        if filters.search:
            pattern = f"%{_escape_like(filters.search)}%"
            conditions.append(
                or_(
                    Deal.reference.ilike(pattern, escape="\\"),
                    _Seller.name.ilike(pattern, escape="\\"),
                    _BUYER_NAME.ilike(pattern, escape="\\"),
                )
            )
        if filters.company_id is not None:
            conditions.append(
                or_(
                    Deal.company_id == filters.company_id,
                    Deal.buyer_company_id == filters.company_id,
                )
            )
        if filters.opened_from is not None:
            conditions.append(Deal.created_at >= filters.opened_from)
        if filters.opened_before is not None:
            conditions.append(Deal.created_at < filters.opened_before)
        return conditions

    async def count_for_company(self, company_id: uuid.UUID) -> int:
        """How many deals a company has, at any stage.

        Used by the company panel's header, which wants the number without the
        rows.
        """
        total = await self.session.scalar(
            select(func.count()).select_from(Deal).where(Deal.company_id == company_id)
        )
        return int(total or 0)
