"""The move to CUSTOMER (L2-11 / 4A-9): whichever of PROSPECT and CLEAR comes second.

Architecture §3.2 and decision 2: a company becomes a ``CUSTOMER`` when it is a
``PROSPECT`` and its background check is ``CLEAR``, whichever becomes true second.
Decision U4 is taken as **one transaction**: the move that completes the condition —
Developer 4A's ``CLEAR`` or Developer 2's ``QUALIFIED`` outcome — promotes the
company before its own commit, so there is never a committed company that is
``PROSPECT`` and ``CLEAR`` at once, and ``company.became_customer`` is announced once,
after the commit (``company-record.md`` §3.2, ``background-check.md`` §11.3).

Everything here runs through the real services, the real 4A ↔ 4B reader and the
shipped ``CLEAR_POLICY`` — nothing about the check is substituted.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.modules.onboarding.application import exporter_profile_service as profile_module
from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue,
)
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.platform.messaging.ports import InMemoryEventBus
from app.platform.messaging.schemas import EventType

pytestmark = pytest.mark.asyncio

COMPLIANCE = "compliance-officer"


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> InMemoryEventBus:
    """An in-memory bus the test can read. The publisher resolves the bus when it is
    constructed, and the announcement constructs one per call, so this covers it."""
    injected = InMemoryEventBus()
    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: injected)
    return injected


def _became_customer(bus: InMemoryEventBus) -> list:
    return [e for e in bus.published if e.event_type is EventType.COMPANY_BECAME_CUSTOMER]


async def _answer_the_screening(company_id: uuid.UUID) -> None:
    """All eight checklist items PASSED, through Developer 4B's service — the inputs
    the shipped CLEAR policy needs (A3; D1–D4)."""
    for key in SCREENING_CATALOGUE:
        async with db_services.AsyncSessionLocal() as db:
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key=key, status="PASSED", comment=None, actor_id=COMPLIANCE
            )


async def _in_review_and_answered(company_id: uuid.UUID) -> None:
    await _answer_the_screening(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )


async def _clear(company_id: uuid.UUID, risk: BackgroundCheckRisk = BackgroundCheckRisk.LOW):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).clear(
            company_id,
            risk=risk,
            reason="Screening complete, nothing adverse.",
            actor_id=COMPLIANCE,
            actor_role=UserRole.COMPLIANCE,
        )


async def _qualify(company_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            company_id, QualificationOutcomeValue.QUALIFIED, actor_id="reviewer"
        )


async def _profile(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


async def _journey_rows(company_id: uuid.UUID) -> list:
    """The company's journey history, oldest first."""
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            company_id, dimension="journey", limit=50
        )
    return list(reversed(rows))


def _moves(rows) -> list[tuple[str | None, str]]:
    return [(row.from_status, row.to_status) for row in rows]


async def _decision_count(company_id: uuid.UUID) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id == company_id)
        )


# ── Qualified first, cleared second ──────────────────────────────────────────


async def test_a_prospect_whose_check_clears_becomes_a_customer(bus: InMemoryEventBus):
    company_id = await make_prospect()
    await _in_review_and_answered(company_id)

    decision = await _clear(company_id)

    profile = await _profile(company_id)
    assert profile.journey is ExporterJourney.CUSTOMER
    assert profile.background_check is BackgroundCheckState.CLEAR

    rows = await _journey_rows(company_id)
    assert _moves(rows) == [("LEAD", "PROSPECT"), ("PROSPECT", "CUSTOMER")]
    [promotion] = [row for row in rows if row.to_status == "CUSTOMER"]
    assert promotion.event_type == "lifecycle_transition"
    assert promotion.actor_id == COMPLIANCE
    assert promotion.event_metadata["terminal"] is True
    assert promotion.event_metadata["cause"] == "background_check_clear"
    assert promotion.event_metadata["clearing_decision_id"] == str(decision.id)

    [event] = _became_customer(bus)
    assert event.payload["company_id"] == str(company_id)
    assert event.payload["clearing_decision_id"] == str(decision.id)
    assert event.payload["risk_rating"] == "LOW"
    assert event.actor_id == COMPLIANCE


# ── Cleared first, qualified second ──────────────────────────────────────────


async def test_a_cleared_lead_that_is_qualified_goes_straight_through_to_customer(
    bus: InMemoryEventBus,
):
    company_id = await make_company()  # a LEAD
    await _in_review_and_answered(company_id)
    decision = await _clear(company_id, BackgroundCheckRisk.MEDIUM)

    # Cleared, but still a lead: nothing to promote yet, nothing announced.
    assert (await _profile(company_id)).journey is ExporterJourney.LEAD
    assert _became_customer(bus) == []

    await _qualify(company_id)

    assert (await _profile(company_id)).journey is ExporterJourney.CUSTOMER
    rows = await _journey_rows(company_id)
    # Both rows are written in one transaction, so they share `created_at`
    # (`now()` is the transaction's start) and the log does not order them: assert
    # the two moves, not their order.
    assert sorted(_moves(rows)) == [("LEAD", "PROSPECT"), ("PROSPECT", "CUSTOMER")]
    [promotion] = [row for row in rows if row.to_status == "CUSTOMER"]
    assert promotion.event_metadata["cause"] == "qualification_outcome"
    assert promotion.event_metadata["clearing_decision_id"] == str(decision.id)
    assert promotion.event_metadata["terminal"] is True

    [event] = _became_customer(bus)
    assert event.payload["clearing_decision_id"] == str(decision.id)
    assert event.payload["risk_rating"] == "MEDIUM"


async def test_a_lead_that_is_cleared_stays_a_lead(bus: InMemoryEventBus):
    """Qualification is the other half; a CLEAR alone promotes nobody."""
    company_id = await make_company()
    await _in_review_and_answered(company_id)
    await _clear(company_id)

    assert (await _profile(company_id)).journey is ExporterJourney.LEAD
    assert await _journey_rows(company_id) == []
    assert _became_customer(bus) == []


# ── Exactly once ─────────────────────────────────────────────────────────────


async def test_reopening_and_clearing_a_customer_again_promotes_and_announces_nothing(
    bus: InMemoryEventBus,
):
    """A customer stays a customer through a reopen (A5), and the second clearance
    finds nothing to do — the move is idempotent."""
    company_id = await make_prospect()
    await _in_review_and_answered(company_id)
    await _clear(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).reopen(
            company_id,
            reason="New adverse media to look at.",
            actor_id=COMPLIANCE,
            actor_role=UserRole.COMPLIANCE,
        )
    assert (await _profile(company_id)).journey is ExporterJourney.CUSTOMER

    await _clear(company_id)

    assert (await _profile(company_id)).journey is ExporterJourney.CUSTOMER
    assert _moves(await _journey_rows(company_id)).count(("PROSPECT", "CUSTOMER")) == 1
    assert len(_became_customer(bus)) == 1


async def test_a_clear_and_a_qualification_landing_together_promote_exactly_once(
    bus: InMemoryEventBus,
):
    """Both moves lock the company row first, so they serialise: whichever commits
    second sees the other's result and makes the move. Never twice, never zero."""
    company_id = await make_company()
    await _in_review_and_answered(company_id)

    await asyncio.gather(_clear(company_id), _qualify(company_id))

    assert (await _profile(company_id)).journey is ExporterJourney.CUSTOMER
    assert _moves(await _journey_rows(company_id)).count(("PROSPECT", "CUSTOMER")) == 1
    assert len(_became_customer(bus)) == 1


# ── One transaction ──────────────────────────────────────────────────────────


async def test_a_failed_promotion_rolls_the_clear_back_with_it(
    bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch
):
    """U4 as one transaction: if the promotion fails, the CLEAR decision, its
    evidence, the gauge and its history row are not left behind either — there is no
    committed state that is PROSPECT and CLEAR at once."""
    company_id = await make_prospect()
    await _in_review_and_answered(company_id)
    decisions_before = await _decision_count(company_id)

    async def _broken(self, profile, **kwargs):
        raise RuntimeError("promotion failed")

    monkeypatch.setattr(
        profile_module.ExporterProfileService, "promote_to_customer_if_ready", _broken
    )
    with pytest.raises(RuntimeError, match="promotion failed"):
        await _clear(company_id)

    profile = await _profile(company_id)
    assert profile.background_check is BackgroundCheckState.IN_REVIEW
    assert profile.journey is ExporterJourney.PROSPECT
    assert await _decision_count(company_id) == decisions_before
    assert _became_customer(bus) == []


async def test_a_dead_event_bus_does_not_undo_a_committed_promotion(
    monkeypatch: pytest.MonkeyPatch,
):
    """The history row is the source of truth; the announcement is best effort
    (architecture §3.6)."""

    class _BrokenBus(InMemoryEventBus):
        async def publish(self, envelope) -> None:
            raise ConnectionError("bus is down")

    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: _BrokenBus())
    company_id = await make_prospect()
    await _in_review_and_answered(company_id)

    await _clear(company_id)

    assert (await _profile(company_id)).journey is ExporterJourney.CUSTOMER
    assert ("PROSPECT", "CUSTOMER") in _moves(await _journey_rows(company_id))
