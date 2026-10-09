"""``QualificationAutoEvaluator`` — answer automatic qualification criteria.

Run when a source changes: a company edit (year established, CIN, industry, export
markets), an IEC verification, a recorded export, a deal value. For every current,
active criterion with an auto source (only the sources that changed, when given):

* work out the answer (``domain/qualification_auto.py``) — or nothing, when the data
  to answer it is not there; nothing is ever written as Unknown;
* **leave it alone when a person answered it**: if the latest result for that
  criterion was recorded by a person, it stands — the evaluator never replaces it;
* write nothing when the latest automatic result already says the same;
* otherwise record a result with source AUTOMATED, decided by the system, the value it
  observed and what it rests on, through ``QualificationService.record_results`` — so it
  is checked and written to history like any other result.

The suggestion recalculates from the new result on read; the outcome stays a person's
decision. A qualified company's results are closed, so it is skipped.

Best effort by design: it runs after the change that triggered it has committed, and a
failure is logged, never raised into that change.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationResultStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.qualification import QualificationResult
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionResultValue,
    DecidedByKind,
    QualificationSource,
    QualificationState,
)
from app.modules.onboarding.domain.entities.trade_invoice import TradeInvoice
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.modules.onboarding.domain.entities.verification_result import (
    VerificationResult,
    about_company,
)
from app.modules.onboarding.domain.qualification_auto import (
    SOURCE_LABEL,
    AutoSource,
    allowed_result,
    incorporation_year,
    threshold_result,
)
from app.modules.onboarding.domain.qualification_views import EvidenceRef, ResultEntry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Answer:
    result: CriterionResultValue
    observed: str
    note: str
    refs: tuple[EvidenceRef, ...] = ()


class QualificationAutoEvaluator:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def evaluate(
        self,
        company_id: uuid.UUID,
        sources: Iterable[AutoSource] | None = None,
    ) -> list[QualificationResult]:
        """Answer the company's automatic criteria; returns the results written."""
        from app.modules.onboarding.application.qualification_service import (
            QualificationService,
        )

        wanted = set(sources) if sources is not None else set(AutoSource)
        profile = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        if profile is None or profile.qualification is QualificationState.QUALIFIED:
            return []
        service = QualificationService(self._db)
        criteria = [
            c
            for c in await service.list_criteria()
            if c.active and c.auto_source is not None and AutoSource(c.auto_source) in wanted
        ]
        if not criteria:
            return []
        latest: dict[str, QualificationResult] = {}
        for result in await service._repo.results_for(company_id):  # newest first
            latest.setdefault(result.criterion.key, result)

        entries = []
        for criterion in criteria:
            previous = latest.get(criterion.key)
            if previous is not None and previous.decided_by_kind is not DecidedByKind.AUTOMATED:
                continue  # a person answered it; that stands
            answer = await self._answer(AutoSource(criterion.auto_source), criterion, profile)
            if answer is None:
                continue
            if (
                previous is not None
                and previous.criterion_id == criterion.id
                and previous.result is answer.result
                and previous.observed_value == answer.observed
            ):
                continue
            entries.append(
                ResultEntry(
                    criterion_key=criterion.key,
                    result=answer.result,
                    observed_value=answer.observed,
                    evidence_note=answer.note,
                    evidence_refs=answer.refs,
                    decided_by_kind=DecidedByKind.AUTOMATED,
                )
            )
        if not entries:
            return []
        rows = await service.record_results(
            company_id,
            entries,
            actor_id=None,
            source=QualificationSource.AUTOMATED,
            decided_by_kind=DecidedByKind.AUTOMATED,
        )
        logger.info(
            "qualification.auto.recorded",
            company_id=str(company_id),
            keys=[entry.criterion_key for entry in entries],
        )
        return rows

    async def evaluate_quietly(
        self, company_id: uuid.UUID, sources: Iterable[AutoSource] | None = None
    ) -> None:
        """``evaluate``, for a caller whose own change has already committed: a failure is
        logged and rolled back, never raised into that caller."""
        try:
            await self.evaluate(company_id, sources)
        except Exception:  # noqa: BLE001 - best effort by design (module docstring)
            await self._db.rollback()
            logger.exception("qualification.auto.failed", company_id=str(company_id))

    # ── The answers ──────────────────────────────────────────────────────────

    async def _answer(self, source: AutoSource, criterion, profile: ExporterProfile) -> Answer | None:
        label = SOURCE_LABEL[source]
        if source is AutoSource.IEC_VERIFICATION:
            row = await self._db.scalar(
                select(VerificationResult)
                .where(
                    about_company(profile.customer_id),
                    VerificationResult.verification_type == VerificationType.IEC,
                    VerificationResult.status.in_(
                        (VerificationResultStatus.PASSED, VerificationResultStatus.FAILED)
                    ),
                )
                .order_by(VerificationResult.performed_at.desc(), VerificationResult.created_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            passed = row.status is VerificationResultStatus.PASSED
            return Answer(
                CriterionResultValue.PASS if passed else CriterionResultValue.FAIL,
                f"IEC check {row.status.value.lower()} on {row.performed_at.date().isoformat()}",
                f"Automatic: {label}",
                (EvidenceRef(type="verification_result", ref=str(row.id)),),
            )
        if source is AutoSource.YEARS_ESTABLISHED:
            year = profile.year_established or incorporation_year(profile.cin)
            if year is None:
                return None
            years = datetime.now(UTC).year - year
            result = threshold_result(years, criterion.comparison, criterion.threshold)
            if result is None:
                return None
            from_where = "year established" if profile.year_established else "the CIN"
            return Answer(result, f"{years} years (since {year}, from {from_where})", f"Automatic: {label}")
        if source is AutoSource.INDUSTRY:
            result = allowed_result([profile.industry], criterion.allowed_values)
            if result is None:
                return None
            return Answer(result, profile.industry or "", f"Automatic: {label}")
        if source is AutoSource.EXPORT_MARKETS:
            markets = [str(m) for m in (profile.export_markets or [])]
            result = allowed_result(markets, criterion.allowed_values)
            if result is None:
                return None
            return Answer(result, ", ".join(markets), f"Automatic: {label}")
        if source is AutoSource.TRADE_HISTORY:
            count = await self._db.scalar(
                select(func.count())
                .select_from(TradeInvoice)
                .join(TradeRelationship, TradeRelationship.id == TradeInvoice.relationship_id)
                .where(TradeRelationship.seller_company_id == profile.customer_id)
            )
            if not count:
                return None
            return Answer(
                CriterionResultValue.PASS,
                f"{count} recorded export{'s' if count != 1 else ''}",
                f"Automatic: {label}",
            )
        if source is AutoSource.DEAL_VALUE:
            # Amounts in different currencies are never compared with each other or with
            # the threshold: a currency unit picks its deals; with no currency unit the
            # deals must all be in one currency, or there is no answer.
            unit = (criterion.unit or "").strip().upper()
            by_currency = dict(
                (
                    await self._db.execute(
                        select(Deal.currency, func.max(Deal.value_amount))
                        .where(
                            Deal.company_id == profile.customer_id,
                            Deal.value_amount.is_not(None),
                        )
                        .group_by(Deal.currency)
                    )
                ).all()
            )
            if len(unit) == 3 and unit.isalpha():
                currency = unit
            elif len(by_currency) == 1:
                currency = next(iter(by_currency))
            else:
                return None
            largest = by_currency.get(currency)
            result = threshold_result(largest, criterion.comparison, criterion.threshold)
            if result is None:
                return None
            return Answer(result, f"largest deal {currency} {largest:,.2f}", f"Automatic: {label}")
        return None


__all__ = ["QualificationAutoEvaluator"]
