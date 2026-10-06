"""The background-check entities and repository through the ORM.

The database refusals themselves are proved by direct SQL in
``test_background_check_schema.py``. This file proves the Python side maps onto
them: the column's default on the entity, ``record`` flushing without committing,
the chain-head and newest-first reads, the evidence lookup, and that a locked row
cannot be changed through the ORM either.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.onboarding.domain.entities import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.background_check_decision import LEGAL_MOVES
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.infrastructure.repositories import (
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.migrations import onboarding_0015_bg_check as migration
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState


def _decision(
    company_id: uuid.UUID,
    from_value: State,
    to_value: State,
    *,
    supersedes: BackgroundCheckDecision | None = None,
    reason: str | None = "because",
    risk: BackgroundCheckRisk | None = None,
) -> BackgroundCheckDecision:
    return BackgroundCheckDecision(
        company_id=company_id,
        from_value=from_value,
        to_value=to_value,
        decided_by="compliance-user",
        decided_by_kind=BackgroundCheckDecidedByKind.MANUAL,
        source=BackgroundCheckDecisionSource.MANUAL,
        reason=reason,
        risk_rating=risk,
        supersedes_decision_id=supersedes.id if supersedes else None,
    )


async def _chain(company_id: uuid.UUID, moves: list[tuple[State, State]]) -> list[uuid.UUID]:
    """Record `moves` in order, each superseding the last, committing once."""
    ids: list[uuid.UUID] = []
    async with db_services.AsyncSessionLocal() as db:
        repo = BackgroundCheckDecisionRepository(db)
        head: BackgroundCheckDecision | None = None
        for from_value, to_value in moves:
            head = await repo.record(
                _decision(
                    company_id,
                    from_value,
                    to_value,
                    supersedes=head,
                    reason=None if from_value is State.NOT_STARTED else "because",
                    risk=BackgroundCheckRisk.MEDIUM if to_value is State.CLEAR else None,
                )
            )
            ids.append(head.id)
        await db.commit()
    return ids


# ── The column and the vocabularies ──────────────────────────────────────────


async def test_a_new_company_reads_not_started_through_the_orm():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
    assert profile.background_check is State.NOT_STARTED


async def test_the_entity_default_is_not_started_before_any_flush():
    assert ExporterProfile.__table__.c.background_check.default.arg is State.NOT_STARTED
    assert ExporterProfile.__table__.c.background_check.nullable is False


async def test_the_python_move_table_matches_the_migrations():
    assert {(a.value, b.value) for a, b in LEGAL_MOVES} == set(migration.LEGAL_MOVES)
    assert len(LEGAL_MOVES) == 9
    assert (State.CLEAR, State.FLAGGED) not in LEGAL_MOVES


async def test_the_python_values_match_the_migrations():
    assert [s.value for s in State] == list(migration.BACKGROUND_CHECK_VALUES)
    assert [r.value for r in BackgroundCheckRisk] == list(migration.RISK_VALUES)


# ── record: flush, never commit ──────────────────────────────────────────────


async def test_record_flushes_but_leaves_the_commit_to_the_caller():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        decision = await BackgroundCheckDecisionRepository(db).record(
            _decision(company_id, State.NOT_STARTED, State.IN_REVIEW, reason=None)
        )
        assert decision.id is not None
        assert db.in_transaction()
        await db.rollback()

    async with db_services.AsyncSessionLocal() as db:
        assert await BackgroundCheckDecisionRepository(db).latest_for_company(company_id) is None


async def test_record_pins_the_evidence_to_the_decision_it_was_given():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        screening = ScreeningReviewItem(
            customer_id=company_id, item_key="website-reviewed", status="PASSED"
        )
        db.add(screening)
        await db.flush()
        stray_decision_id = uuid.uuid4()
        evidence = BackgroundCheckEvidence(
            decision_id=stray_decision_id,
            kind=BackgroundCheckEvidenceKind.SCREENING_ITEM,
            screening_review_item_id=screening.id,
        )
        decision = await BackgroundCheckDecisionRepository(db).record(
            _decision(company_id, State.NOT_STARTED, State.IN_REVIEW, reason=None),
            [evidence],
        )
        await db.commit()
        decision_id = decision.id

    async with db_services.AsyncSessionLocal() as db:
        snapshots = await BackgroundCheckDecisionRepository(db).evidence_for([decision_id])
    [pinned] = snapshots[decision_id]
    assert pinned.decision_id == decision_id != stray_decision_id
    assert pinned.kind is BackgroundCheckEvidenceKind.SCREENING_ITEM


async def test_the_database_still_refuses_what_the_service_should_have():
    """The repository does not re-validate; the database is the backstop."""
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        start = await BackgroundCheckDecisionRepository(db).record(
            _decision(company_id, State.NOT_STARTED, State.IN_REVIEW, reason=None)
        )
        with pytest.raises(IntegrityError):
            await BackgroundCheckDecisionRepository(db).record(
                _decision(company_id, State.IN_REVIEW, State.CLEAR, supersedes=start, risk=None)
            )
        await db.rollback()


# ── Reads ────────────────────────────────────────────────────────────────────


async def test_a_company_with_no_decisions_has_no_head_and_an_empty_list():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        repo = BackgroundCheckDecisionRepository(db)
        assert await repo.latest_for_company(company_id) is None
        assert await repo.list_for_company(company_id) == ([], 0)
        assert await repo.evidence_for([]) == {}


async def test_the_latest_decision_is_the_chain_head_even_within_one_transaction():
    """Every decision below shares one `decided_at` (one transaction). The head is found
    by the chain, not by the clock."""
    company_id = await make_company()
    ids = await _chain(
        company_id,
        [
            (State.NOT_STARTED, State.IN_REVIEW),
            (State.IN_REVIEW, State.CLEAR),
            (State.CLEAR, State.IN_REVIEW),
            (State.IN_REVIEW, State.FLAGGED),
        ],
    )
    async with db_services.AsyncSessionLocal() as db:
        head = await BackgroundCheckDecisionRepository(db).latest_for_company(company_id)
    assert head.id == ids[-1]
    assert head.to_value is State.FLAGGED
    assert head.supersedes_decision_id == ids[-2]


async def test_decisions_list_newest_first_with_a_total():
    company_id = await make_company()
    first = await _chain(company_id, [(State.NOT_STARTED, State.IN_REVIEW)])
    async with db_services.AsyncSessionLocal() as db:
        repo = BackgroundCheckDecisionRepository(db)
        start = await db.get(BackgroundCheckDecision, first[0])
        more_info = await repo.record(
            _decision(company_id, State.IN_REVIEW, State.MORE_INFO, supersedes=start)
        )
        await db.commit()
        more_info_id = more_info.id

    async with db_services.AsyncSessionLocal() as db:
        repo = BackgroundCheckDecisionRepository(db)
        rows, total = await repo.list_for_company(company_id)
        page, _ = await repo.list_for_company(company_id, limit=1, offset=1)
    assert total == 2
    assert [row.id for row in rows] == [more_info_id, first[0]]
    assert [row.id for row in page] == [first[0]]


async def test_evidence_for_returns_every_requested_decision():
    company_id = await make_company()
    ids = await _chain(company_id, [(State.NOT_STARTED, State.IN_REVIEW)])
    async with db_services.AsyncSessionLocal() as db:
        snapshots = await BackgroundCheckDecisionRepository(db).evidence_for(ids)
    assert snapshots == {ids[0]: []}


async def test_a_reopen_leaves_the_clearing_decision_exactly_as_it_was():
    company_id = await make_company()
    ids = await _chain(
        company_id,
        [(State.NOT_STARTED, State.IN_REVIEW), (State.IN_REVIEW, State.CLEAR)],
    )
    async with db_services.AsyncSessionLocal() as db:
        before = await db.get(BackgroundCheckDecision, ids[1])
        snapshot = (before.to_value, before.risk_rating, before.reason, before.decided_at)
    async with db_services.AsyncSessionLocal() as db:
        clear = await db.get(BackgroundCheckDecision, ids[1])
        await BackgroundCheckDecisionRepository(db).record(
            _decision(company_id, State.CLEAR, State.IN_REVIEW, supersedes=clear)
        )
        await db.commit()
    async with db_services.AsyncSessionLocal() as db:
        after = await db.get(BackgroundCheckDecision, ids[1])
    assert (after.to_value, after.risk_rating, after.reason, after.decided_at) == snapshot


# ── Locked through the ORM too ───────────────────────────────────────────────


async def test_the_repository_offers_no_update_or_delete():
    for name in ("update", "delete"):
        assert not hasattr(BackgroundCheckDecisionRepository, name)


async def test_editing_a_loaded_decision_is_refused_at_the_database():
    company_id = await make_company()
    ids = await _chain(company_id, [(State.NOT_STARTED, State.IN_REVIEW)])
    async with db_services.AsyncSessionLocal() as db:
        decision = await db.get(BackgroundCheckDecision, ids[0])
        decision.reason = "rewritten after the fact"
        with pytest.raises(DBAPIError):
            await db.flush()
        await db.rollback()


async def test_deleting_a_loaded_decision_is_refused_at_the_database():
    company_id = await make_company()
    ids = await _chain(company_id, [(State.NOT_STARTED, State.IN_REVIEW)])
    async with db_services.AsyncSessionLocal() as db:
        decision = await db.get(BackgroundCheckDecision, ids[0])
        await db.delete(decision)
        with pytest.raises(DBAPIError):
            await db.flush()
        await db.rollback()
