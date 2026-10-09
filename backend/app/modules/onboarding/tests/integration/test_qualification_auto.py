"""Automatic qualification results.

Recording a passed IEC verification at once answers "Holds an export licence (IEC)":
Pass, automatically. A person's later answer stands and is never replaced. A company
edit answers the criteria it feeds (years in business, industry); a criterion's auto
source must fit its kind. Every criterion a test creates is retired at the end, so the
rest of the suite never sees it.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    DecidedByKind,
    QualificationSource,
    ThresholdComparison,
)
from app.modules.onboarding.domain.qualification_views import CriterionDefinition, ResultEntry
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def criterion(definition: CriterionDefinition):
    key = f"auto_{uuid.uuid4().hex[:10]}"
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).create_criterion(key, definition, actor_id="test")
    try:
        yield key
    finally:
        retired = CriterionDefinition(**{**definition.__dict__, "active": False})
        async with db_services.AsyncSessionLocal() as db:
            await QualificationService(db).add_version(key, retired, actor_id="test")


async def latest(company_id, key):
    async with db_services.AsyncSessionLocal() as db:
        view = await QualificationService(db).get_qualification(company_id)
    standing = next(s for s in view.standings if s.criterion.key == key)
    return standing.latest_result


async def iec(company_id, status="PASSED"):
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.IEC,
            VerificationEntityType.EXPORTER,
            company_id,
            payload={"status": status, "provider_reference": uuid.uuid4().hex},
            actor_id=str(uuid.uuid4()),
            evidence=VerificationEvidence(note="DGFT lookup"),
        )


IEC = CriterionDefinition(
    label="Holds an export licence (IEC)", kind=CriterionKind.YES_NO, required=False,
    auto_source="IEC_VERIFICATION",
)


async def test_a_passed_iec_check_answers_the_criterion_automatically():
    company_id = await make_company()
    async with criterion(IEC) as key:
        await iec(company_id)

        result = await latest(company_id, key)
        assert result is not None
        assert result.result is CriterionResultValue.PASS
        assert result.source is QualificationSource.AUTOMATED
        assert result.decided_by_kind is DecidedByKind.AUTOMATED
        assert result.recorded_by is None
        assert result.observed_value.startswith("IEC check passed")
        assert result.evidence_refs[0]["type"] == "verification_result"


async def test_a_persons_later_answer_stands_and_is_not_replaced():
    company_id = await make_company()
    async with criterion(IEC) as key:
        await iec(company_id)
        async with db_services.AsyncSessionLocal() as db:
            await QualificationService(db).record_results(
                company_id,
                [ResultEntry(key, CriterionResultValue.FAIL, evidence_note="Licence suspended")],
                actor_id=str(uuid.uuid4()),
            )
        await iec(company_id)

        result = await latest(company_id, key)
        assert result.result is CriterionResultValue.FAIL
        assert result.decided_by_kind is DecidedByKind.MANUAL


async def test_the_same_answer_is_not_written_twice():
    company_id = await make_company()
    async with criterion(IEC) as key:
        await iec(company_id)
        first = await latest(company_id, key)
        await iec(company_id)
        assert (await latest(company_id, key)).id == first.id


async def test_a_company_edit_answers_years_in_business_and_industry():
    company_id = await make_company()
    years = CriterionDefinition(
        label="In business at least 3 years", kind=CriterionKind.NUMBER_THRESHOLD, required=False,
        comparison=ThresholdComparison.AT_LEAST, threshold=Decimal(3), unit="years",
        auto_source="YEARS_ESTABLISHED",
    )
    industry = CriterionDefinition(
        label="Industry we finance", kind=CriterionKind.ALLOWED_VALUES, required=False,
        allowed_values=("Textiles", "Engineering"), auto_source="INDUSTRY",
    )
    async with criterion(years) as years_key, criterion(industry) as industry_key:
        async with db_services.AsyncSessionLocal() as db:
            await ExporterProfileService(db).update_profile(
                company_id,
                {"year_established": 2010, "industry": "textiles", "name": f"Auto {uuid.uuid4().hex[:6]}"},
                actor_id="test",
            )
        assert (await latest(company_id, years_key)).result is CriterionResultValue.PASS
        assert (await latest(company_id, industry_key)).result is CriterionResultValue.PASS

        async with db_services.AsyncSessionLocal() as db:
            await ExporterProfileService(db).update_profile(
                company_id, {"industry": "Mining"}, actor_id="test"
            )
        assert (await latest(company_id, industry_key)).result is CriterionResultValue.FAIL


async def test_an_auto_source_must_fit_the_kind_of_criterion():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="answers a YES_NO criterion"):
            await QualificationService(db).create_criterion(
                f"auto_{uuid.uuid4().hex[:10]}",
                CriterionDefinition(
                    label="x", kind=CriterionKind.NUMBER_THRESHOLD, required=False,
                    comparison=ThresholdComparison.AT_LEAST, threshold=Decimal(1),
                    auto_source="IEC_VERIFICATION",
                ),
                actor_id="test",
            )


async def test_deal_values_in_different_currencies_are_never_compared():
    """A currency unit picks its own deals; with no currency unit the deals must all be
    in one currency, or there is no answer at all."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.modules.onboarding.application.deal_service import DealService, DealTerms
    from app.modules.onboarding.application.qualification_auto_service import (
        QualificationAutoEvaluator,
    )
    from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
    from app.modules.onboarding.domain.qualification_auto import AutoSource
    from app.modules.onboarding.tests.fixtures.companies import make_prospect

    company_id = await make_prospect()
    for amount, currency in (("90000", "INR"), ("2000", "USD")):
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).open_deal(
                company_id,
                reference=f"VAL-{uuid.uuid4().hex[:8]}",
                actor_id="test",
                terms=DealTerms(
                    sent=frozenset({"value_amount", "currency"}),
                    value_amount=Decimal(amount),
                    currency=currency,
                ),
            )

    def at_least(threshold: int, unit: str | None):
        return SimpleNamespace(
            comparison=ThresholdComparison.AT_LEAST, threshold=Decimal(threshold), unit=unit
        )

    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        evaluator = QualificationAutoEvaluator(db)
        # 90,000 INR is not "at least 5,000" USD: only the USD deal counts.
        usd = await evaluator._answer(AutoSource.DEAL_VALUE, at_least(5000, "USD"), profile)
        assert usd is not None and usd.result is CriterionResultValue.FAIL
        assert usd.observed == "largest deal USD 2,000.00"
        inr = await evaluator._answer(AutoSource.DEAL_VALUE, at_least(5000, "inr"), profile)
        assert inr is not None and inr.result is CriterionResultValue.PASS
        # No currency unit and two currencies: nothing to compare.
        assert await evaluator._answer(AutoSource.DEAL_VALUE, at_least(5000, None), profile) is None
