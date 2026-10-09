"""``PaymentTermService`` — the payment terms administrators keep, and a company's
default term.

A term is its ``code``. Adding one writes version 1; changing or retiring one writes
the next version and marks the old one superseded, in one transaction, so a deal keeps
the exact term it was agreed on. Only the current, active version of a term is offered
for a new choice; any version stays readable.

A company's default (``exporter_profile.default_payment_term_id``) is where a new deal's
term comes from: the deal takes the **current** version of the default's code, so an
administrator's later rewording reaches new deals without anyone re-picking the default.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.payment_term import DAYS_KINDS, KINDS, PaymentTerm
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    PaymentTermNotFoundError,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)


def _check(kind: str, days: int | None) -> None:
    if kind not in KINDS:
        raise ValidationError(f"Unknown payment term kind {kind!r}")
    if kind in DAYS_KINDS and (days is None or days <= 0):
        raise ValidationError("This kind of term needs a number of days")
    if kind not in DAYS_KINDS and days is not None:
        raise ValidationError("This kind of term has no number of days")


def term_summary(term: PaymentTerm | None) -> dict | None:
    """A term as a history row or a handover snapshot records it."""
    if term is None:
        return None
    return {
        "id": str(term.id),
        "code": term.code,
        "version": term.version,
        "label": term.label,
        "kind": term.kind,
        "days": term.days,
    }


class PaymentTermService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def current(self) -> list[PaymentTerm]:
        """The current version of every term, retired ones included, by label."""
        return list(
            await self._db.scalars(
                select(PaymentTerm).where(PaymentTerm.is_current.is_(True)).order_by(PaymentTerm.label)
            )
        )

    async def history(self) -> list[PaymentTerm]:
        return list(
            await self._db.scalars(
                select(PaymentTerm).order_by(PaymentTerm.code, PaymentTerm.version.desc())
            )
        )

    async def get(self, term_id: uuid.UUID) -> PaymentTerm:
        term = await self._db.get(PaymentTerm, term_id)
        if term is None:
            raise PaymentTermNotFoundError(term_id)
        return term

    async def current_of(self, code: str) -> PaymentTerm | None:
        return await self._db.scalar(
            select(PaymentTerm).where(PaymentTerm.code == code, PaymentTerm.is_current.is_(True))
        )

    async def offerable(self, term_id: uuid.UUID) -> PaymentTerm:
        """A term someone may choose now: the current version, and not retired."""
        term = await self.get(term_id)
        if not (term.is_current and term.active):
            raise ValidationError(f"{term.label} is no longer offered; choose a current term")
        return term

    # ── Settings ─────────────────────────────────────────────────────────────

    async def add(
        self, *, code: str, label: str, kind: str, days: int | None, actor_id: str
    ) -> PaymentTerm:
        code = code.strip().upper()
        _check(kind, days)
        if await self._db.scalar(select(PaymentTerm.id).where(PaymentTerm.code == code)):
            raise ValidationError(f"A payment term with the code {code} already exists")
        term = PaymentTerm(
            code=code, version=1, label=label.strip(), kind=kind, days=days, created_by=actor_id
        )
        self._db.add(term)
        await self._db.commit()
        await self._db.refresh(term)
        logger.info("payment_term.added", code=code, actor_id=actor_id)
        return term

    async def revise(
        self,
        code: str,
        *,
        label: str | None,
        kind: str | None,
        days: int | None,
        days_sent: bool,
        active: bool | None,
        actor_id: str,
    ) -> PaymentTerm:
        """Write the next version of ``code`` with the changes given; the old version
        stays, superseded. A change that changes nothing is refused."""
        old = await self._db.scalar(
            select(PaymentTerm)
            .where(PaymentTerm.code == code, PaymentTerm.is_current.is_(True))
            .with_for_update()
        )
        if old is None:
            raise PaymentTermNotFoundError(code)
        new_kind = kind or old.kind
        new_days = days if days_sent else (old.days if new_kind == old.kind else None)
        new_label = (label or old.label).strip()
        new_active = old.active if active is None else active
        _check(new_kind, new_days)
        if (new_label, new_kind, new_days, new_active) == (old.label, old.kind, old.days, old.active):
            raise ValidationError("That leaves the payment term as it already is")
        old.is_current = False
        await self._db.flush()
        term = PaymentTerm(
            code=old.code,
            version=old.version + 1,
            label=new_label,
            kind=new_kind,
            days=new_days,
            active=new_active,
            created_by=actor_id,
        )
        self._db.add(term)
        await self._db.commit()
        await self._db.refresh(term)
        logger.info("payment_term.revised", code=code, version=term.version, actor_id=actor_id)
        return term

    # ── A company's default ──────────────────────────────────────────────────

    async def set_company_default(
        self, customer_id: uuid.UUID, term_id: uuid.UUID | None, *, actor_id: str
    ) -> PaymentTerm | None:
        profile = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == customer_id).with_for_update()
        )
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        term = await self.offerable(term_id) if term_id is not None else None
        if profile.default_payment_term_id == (term.id if term else None):
            return term
        previous = (
            await self._db.get(PaymentTerm, profile.default_payment_term_id)
            if profile.default_payment_term_id
            else None
        )
        profile.default_payment_term_id = term.id if term else None
        await HistoryService(self._db).record(
            customer_id,
            dimension=history_dimensions.PROFILE,
            event_type="default_payment_term_set",
            to_value="default_payment_term",
            actor_id=actor_id,
            source="payment_term_service.set_company_default",
            details={
                "field": "default_payment_term",
                "from": previous.label if previous else None,
                "to": term.label if term else None,
            },
        )
        await self._db.commit()
        return term


__all__ = ["PaymentTermService", "term_summary"]
