"""Migration 0016, the conversation gauge, and seam S1.

The database-level cases go straight through ``psycopg2`` so they prove the
*database* refuses the bad row and not just the service — migration register §2:
every new constraint gets a direct-SQL violation test. The rest go through the
service and the API as a person would.

``follow_up_completion`` is covered here too, in raw SQL with no ORM entity,
because migration 0016 creates that table and writes no code against it: the lock
and the two foreign keys are tested against the migration, so the follow-ups code
inherits a table already known to be safe.

Real Postgres, each test minting its own company, like the rest of this package.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, date, datetime, timedelta

import psycopg2
import psycopg2.errors
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.conversation_service import (
    HISTORY_DIMENSION_CONVERSATION,
    ConversationService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    ConversationCheckBackInPastError,
    ConversationCheckBackNotAllowedError,
    ConversationCheckBackRequiredError,
    ConversationNotAvailableError,
    ExporterProfileNotFoundError,
    InvalidConversationTransitionError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
BACKEND = pathlib.Path(__file__).resolve().parents[5]
REVISION = "onboarding_0016_engagement"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _company(journey: ExporterJourney = ExporterJourney.PROSPECT) -> uuid.UUID:
    """A company at ``journey``.

    The journey is set directly rather than through a qualification outcome: this
    file is about the conversation gauge, and driving the qualification gauge to move
    the journey would make every test here depend on its rules too.
    """
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = journey
        await db.commit()
    return company_id


async def _read(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


async def _history(company_id: uuid.UUID) -> list:
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            company_id, dimension=HISTORY_DIMENSION_CONVERSATION
        )
    return list(rows)


async def _set(company_id: uuid.UUID, value: ExporterConversation, **kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await ConversationService(db).set_conversation(
            company_id, value, actor_id=kwargs.pop("actor_id", "tester"), **kwargs
        )


# ── The migration ────────────────────────────────────────────────────────────


def _script() -> ScriptDirectory:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(cfg)


async def test_0016_parents_onto_0020_and_the_chain_has_one_head():
    """The register's rules that actually bite: one head, a revision id inside
    Alembic's 32-character ``version_num``, and the parent this revision is meant
    to have. 0018 parents onto this revision, so if the parent moves, this says so."""
    script = _script()
    [head] = script.get_heads()
    assert script.get_revision(REVISION).down_revision == "onboarding_0020_retire_lifecycle"
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", head)}
    assert len(REVISION) <= 32


async def test_0016_creates_both_enums_with_the_documented_values():
    """The Postgres types, read back from the catalogue rather than from the
    Python enums — so a value added to one and not the other fails here. The
    conversation type is architecture §3.3's six; the outcome type is the
    engagement contract §5.3's four, created for follow-ups."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'exporter_conversation_enum' ORDER BY e.enumsortorder"
            )
            assert [r[0] for r in cur.fetchall()] == [
                "NOT_CONTACTED",
                "REACHING_OUT",
                "SPOKE_TO_THEM",
                "INTERESTED",
                "NOT_NOW",
                "READY_NOW",
            ]
            cur.execute(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'follow_up_outcome_enum' ORDER BY e.enumsortorder"
            )
            assert [r[0] for r in cur.fetchall()] == [
                "DONE",
                "NO_ANSWER",
                "RESCHEDULED",
                "CANCELLED",
            ]
    finally:
        conn.close()


async def test_the_conversation_column_defaults_to_not_contacted():
    """A company created after 0016 gets `NOT_CONTACTED` from the database, with
    no service call and — per engagement contract §8 — no history row: writing an
    `_initial` row for a value nobody chose would put a change in the log that
    never happened."""
    company_id = await make_company()
    profile = await _read(company_id)
    assert profile.conversation is ExporterConversation.NOT_CONTACTED
    assert profile.conversation_check_back_on is None
    assert await _history(company_id) == []


# ── Direct SQL: the check-back constraint ────────────────────────────────────


async def test_the_database_refuses_a_check_back_date_without_not_now():
    """`ck_exporter_profile_conversation_check_back` (engagement contract §2.3). A
    stale date on a company that has moved on would put it on the Follow-ups list
    for a conversation that is over, so the invariant is the database's and not
    only the service's."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE onboarding.exporter_profile "
                    "SET conversation = 'INTERESTED', conversation_check_back_on = %s "
                    "WHERE customer_id = %s",
                    (date(2027, 1, 15), str(company_id)),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_the_database_refuses_not_now_without_a_check_back_date():
    """The other half of the same constraint: `NOT_NOW` always carries a date."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE onboarding.exporter_profile SET conversation = 'NOT_NOW' "
                    "WHERE customer_id = %s",
                    (str(company_id),),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_the_database_accepts_not_now_with_a_check_back_date():
    """The constraint refuses the wrong shape and nothing else — a check that only
    ever rejected would pass its violation test while being useless."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(
                "UPDATE onboarding.exporter_profile "
                "SET conversation = 'NOT_NOW', conversation_check_back_on = %s "
                "WHERE customer_id = %s",
                (date(2027, 1, 15), str(company_id)),
            )
            assert cur.rowcount == 1
    finally:
        conn.rollback()
        conn.close()


# ── Direct SQL: follow_up_completion is locked, and really linked ────────────
#
# Migration 0016 creates this table and writes no code against it. These tests are
# therefore in raw SQL with no ORM entity: they test the migration, not the
# follow-ups code, which should inherit a table already known to be safe.


def _insert_completion(cur, *, activity_id, company_id, outcome="DONE", next_due_at=None):
    cur.execute(
        "INSERT INTO onboarding.follow_up_completion "
        "(id, activity_id, customer_id, outcome, note, next_due_at, completed_by) "
        "VALUES (%s, %s, %s, %s, 'raw sql', %s, 'tester') RETURNING id",
        (str(uuid.uuid4()), str(activity_id), str(company_id), outcome, next_due_at),
    )
    return cur.fetchone()[0]


def _insert_activity(cur, company_id) -> uuid.UUID:
    activity_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.exporter_activity "
        "(id, customer_id, activity_type, subject, actor_id, occurred_at, due_at) "
        "VALUES (%s, %s, 'FOLLOW_UP', 'Check back', 'tester', now(), now())",
        (str(activity_id), str(company_id)),
    )
    return activity_id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE onboarding.follow_up_completion SET note = 'edited'",
        "DELETE FROM onboarding.follow_up_completion",
    ],
)
async def test_a_follow_up_completion_cannot_be_updated_or_deleted(statement):
    """`trg_follow_up_completion_append_only`, via the shared
    `public.prevent_mutation()` — `RaiseException`, the same error every other
    locked table in this repository raises. A correction is a new activity plus its
    own completion, never an edit (engagement contract §5.4).

    Migration 0016 writes no code against this table, so this goes through raw SQL
    with no ORM entity: it proves the *migration* locked it, which is what the
    follow-ups code inherits.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            activity_id = _insert_activity(cur, company_id)
            _insert_completion(cur, activity_id=activity_id, company_id=company_id)
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cur.execute(statement)
    finally:
        conn.rollback()
        conn.close()
    assert "immutable" in str(caught.value).lower()


async def test_a_completion_needs_a_real_activity_and_a_real_company():
    """Both foreign keys, `ON DELETE RESTRICT`. A completion is the record that
    someone did the work; it cannot point at nothing."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                _insert_completion(
                    cur, activity_id=uuid.uuid4(), company_id=company_id
                )
        conn.rollback()
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            activity_id = _insert_activity(cur, company_id)
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                _insert_completion(
                    cur, activity_id=activity_id, company_id=uuid.uuid4()
                )
    finally:
        conn.rollback()
        conn.close()


async def test_a_follow_up_is_completed_at_most_once():
    """`uq_follow_up_completion_activity_id`. A reschedule is a *new* activity —
    the activity table is append-only and nothing may move a `due_at` — so nothing
    legitimate completes the same activity twice."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            activity_id = _insert_activity(cur, company_id)
            _insert_completion(cur, activity_id=activity_id, company_id=company_id)
            with pytest.raises(psycopg2.errors.UniqueViolation):
                _insert_completion(cur, activity_id=activity_id, company_id=company_id)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize(
    ("outcome", "next_due_at"),
    [
        ("RESCHEDULED", None),  # rescheduled to nowhere
        ("DONE", datetime(2027, 3, 1, tzinfo=UTC)),  # a new due date on a closed one
    ],
)
async def test_next_due_at_belongs_to_rescheduled_and_nothing_else(outcome, next_due_at):
    """`ck_follow_up_completion_next_due` (contract §5.4): a next due date exactly
    when the outcome is `RESCHEDULED`."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            activity_id = _insert_activity(cur, company_id)
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_completion(
                    cur,
                    activity_id=activity_id,
                    company_id=company_id,
                    outcome=outcome,
                    next_due_at=next_due_at,
                )
    finally:
        conn.rollback()
        conn.close()


async def test_only_0016_ever_touches_follow_up_completion():
    """The table's boundary, as a test rather than a promise in a document.

    0016 creates ``follow_up_completion`` and writes no code against it; the
    follow-ups code writes the entity, repository, service and routes and **no
    migration at all**. The half of that which stays true forever, and is worth a
    test, is the second half: exactly one migration in this repository may mention
    the table.

    Why it matters beyond tidiness: 0018 declares
    ``down_revision = "onboarding_0016_engagement"``. A second engagement migration
    landing after 0018 would have to parent onto 0019 or force a re-parent, for a
    reason purely internal to engagement — which is the chain damage keeping the
    table in one migration avoids.
    """
    migrations = sorted(
        (BACKEND / "app" / "modules" / "onboarding" / "migrations").glob("*.py")
    )
    mentioning = {
        path.name
        for path in migrations
        if "follow_up_completion" in path.read_text(encoding="utf-8")
    }
    assert mentioning == {"onboarding_0016_engagement.py"}, mentioning


# ── The service: the rules ───────────────────────────────────────────────────


async def test_a_move_updates_the_gauge_and_writes_one_history_row():
    """Architecture §3.8: the current value and the record of how it got there in
    one transaction. One row per move, carrying from, to, who and the code path."""
    company_id = await _company()
    await _set(company_id, ExporterConversation.REACHING_OUT, actor_id="user-1")

    profile = await _read(company_id)
    assert profile.conversation is ExporterConversation.REACHING_OUT

    [row] = await _history(company_id)
    assert row.dimension == HISTORY_DIMENSION_CONVERSATION
    assert row.event_type == "conversation_transition"
    assert row.from_status == "NOT_CONTACTED"
    assert row.to_status == "REACHING_OUT"
    assert row.actor_id == "user-1"
    assert row.event_metadata["source"] == "conversation_service.set_conversation"
    assert row.deal_id is None


async def test_an_operator_can_walk_a_company_from_not_contacted_to_ready_now():
    """The prompt's own definition of done for this phase: an operator can move a
    company from NOT_CONTACTED to READY_NOW. Every step is recorded, in order."""
    company_id = await _company()
    for value in (
        ExporterConversation.REACHING_OUT,
        ExporterConversation.SPOKE_TO_THEM,
        ExporterConversation.INTERESTED,
        ExporterConversation.READY_NOW,
    ):
        await _set(company_id, value)

    assert (await _read(company_id)).conversation is ExporterConversation.READY_NOW
    rows = await _history(company_id)
    assert [r.to_status for r in rows][::-1] == [
        "REACHING_OUT",
        "SPOKE_TO_THEM",
        "INTERESTED",
        "READY_NOW",
    ]


async def test_a_move_backwards_is_allowed():
    """Contract §1.1: any value may follow any other. A conversation that looked
    promising can go quiet, and the gauge has to be able to say so."""
    company_id = await _company()
    await _set(company_id, ExporterConversation.READY_NOW)
    await _set(company_id, ExporterConversation.REACHING_OUT)
    assert (await _read(company_id)).conversation is ExporterConversation.REACHING_OUT


async def test_a_move_on_a_lead_is_refused_and_writes_nothing():
    """The gauge applies from PROSPECT onward, and history contract §5's "an illegal move must leave
    nothing behind"."""
    company_id = await _company(ExporterJourney.LEAD)
    with pytest.raises(ConversationNotAvailableError) as caught:
        await _set(company_id, ExporterConversation.REACHING_OUT)
    assert caught.value.error_code == "CONVERSATION_NOT_AVAILABLE"
    assert caught.value.status_code == 409
    assert (await _read(company_id)).conversation is ExporterConversation.NOT_CONTACTED
    assert await _history(company_id) == []


async def test_a_move_to_the_current_value_is_refused():
    """The only refused move (contract §1.1): it records nothing, and would put a
    row whose from equals its to in the history log."""
    company_id = await _company()
    with pytest.raises(InvalidConversationTransitionError) as caught:
        await _set(company_id, ExporterConversation.NOT_CONTACTED)
    assert caught.value.error_code == "INVALID_CONVERSATION_TRANSITION"
    assert await _history(company_id) == []


async def test_a_move_on_a_company_that_does_not_exist_is_a_404():
    """Reused rather than redefined — engagement contract §7 marks this one for
    follow-ups too."""
    with pytest.raises(ExporterProfileNotFoundError):
        await _set(uuid.uuid4(), ExporterConversation.REACHING_OUT)


# ── The service: NOT_NOW ─────────────────────────────────────────────────────


async def test_not_now_stores_the_check_back_date_on_the_company():
    """The date lives on the company, never as a mark on an activity —
    activities are append-only, and §9.3's "Watch out for" lists that mistake
    first. The history row carries the date in its details too, so the log alone
    answers "what did we promise"."""
    company_id = await _company()
    check_back = date.today() + timedelta(days=45)
    await _set(
        company_id,
        ExporterConversation.NOT_NOW,
        reason="Said not now; revisit in the new year",
        check_back_on=check_back,
    )

    profile = await _read(company_id)
    assert profile.conversation is ExporterConversation.NOT_NOW
    assert profile.conversation_check_back_on == check_back

    [row] = await _history(company_id)
    assert row.reason == "Said not now; revisit in the new year"
    assert row.event_metadata["check_back_on"] == check_back.isoformat()


async def test_not_now_without_a_check_back_date_is_refused():
    """The documented refusal for a NOT_NOW with no date."""
    company_id = await _company()
    with pytest.raises(ConversationCheckBackRequiredError) as caught:
        await _set(company_id, ExporterConversation.NOT_NOW, reason="Not now")
    assert caught.value.error_code == "CONVERSATION_CHECK_BACK_REQUIRED"
    assert caught.value.status_code == 422
    assert (await _read(company_id)).conversation is ExporterConversation.NOT_CONTACTED
    assert await _history(company_id) == []


async def test_not_now_without_a_reason_is_refused():
    """Contract §4: `NOT_NOW` is the one value that records a setback, and "why
    not now" is the only thing that makes the row worth reading later."""
    company_id = await _company()
    with pytest.raises(ValidationError):
        await _set(
            company_id,
            ExporterConversation.NOT_NOW,
            check_back_on=date.today() + timedelta(days=7),
        )
    assert await _history(company_id) == []


def _utc_today() -> date:
    """The day the service compares against. Not ``date.today()``: that is the local
    date, which runs ahead of UTC between local and UTC midnight (00:00–05:30 in
    India), when "yesterday" locally is still "today" to the service."""
    return datetime.now(UTC).date()


async def test_a_check_back_date_in_the_past_is_refused():
    """A typo, and a Follow-ups list seeded with dates already overdue on the day
    they were entered is a list nobody trusts."""
    company_id = await _company()
    with pytest.raises(ConversationCheckBackInPastError) as caught:
        await _set(
            company_id,
            ExporterConversation.NOT_NOW,
            reason="Not now",
            check_back_on=_utc_today() - timedelta(days=1),
        )
    assert caught.value.error_code == "CONVERSATION_CHECK_BACK_IN_PAST"


async def test_a_check_back_date_of_today_is_accepted():
    """"Check back later today" is a real thing to promise, so the boundary is
    inclusive — and a boundary is worth a test in both directions."""
    company_id = await _company()
    await _set(
        company_id,
        ExporterConversation.NOT_NOW,
        reason="Calling back this afternoon",
        check_back_on=_utc_today(),
    )
    assert (await _read(company_id)).conversation_check_back_on == _utc_today()


async def test_a_check_back_date_on_any_other_move_is_refused_not_ignored():
    """Contract §4: silently dropping it would leave the operator believing a date
    was stored."""
    company_id = await _company()
    with pytest.raises(ConversationCheckBackNotAllowedError) as caught:
        await _set(
            company_id,
            ExporterConversation.INTERESTED,
            check_back_on=date.today() + timedelta(days=7),
        )
    assert caught.value.error_code == "CONVERSATION_CHECK_BACK_NOT_ALLOWED"
    assert await _history(company_id) == []


async def test_moving_away_from_not_now_clears_the_check_back_date():
    """Without being asked. A stale date would keep the company on the Follow-ups
    list for a conversation that has moved on, and the CHECK refuses the row
    anyway."""
    company_id = await _company()
    await _set(
        company_id,
        ExporterConversation.NOT_NOW,
        reason="Not now",
        check_back_on=date.today() + timedelta(days=30),
    )
    await _set(company_id, ExporterConversation.READY_NOW)

    profile = await _read(company_id)
    assert profile.conversation is ExporterConversation.READY_NOW
    assert profile.conversation_check_back_on is None
    # The clearing is recorded, as an explicit null rather than an absent key: an
    # absent key would be indistinguishable from an older row.
    newest = (await _history(company_id))[0]
    assert newest.event_metadata["check_back_on"] is None


# ── Seam S1 ──────────────────────────────────────────────────────────────────


async def test_seam_s1_sets_ready_now_and_carries_the_deal_id():
    """Architecture §3.3: opening a deal also sets READY_NOW. The history row
    carries `deal_id`, per history contract §2, so the log says which deal did
    it."""
    company_id = await _company()
    deal_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).mark_ready_now_for_opened_deal(
            company_id, deal_id=deal_id, actor_id="user-7"
        )
        # The caller owns the transaction: this is the deal's commit, standing
        # in for the one that also writes the deal row.
        await db.commit()

    assert (await _read(company_id)).conversation is ExporterConversation.READY_NOW
    [row] = await _history(company_id)
    assert row.to_status == "READY_NOW"
    assert row.deal_id == deal_id
    assert row.actor_id == "user-7"
    assert (
        row.event_metadata["source"]
        == "conversation_service.mark_ready_now_for_opened_deal"
    )
    assert row.event_metadata["cause"] == "deal_opened"


async def test_seam_s1_is_idempotent():
    """Opening a second deal for a company that is already ready is normal, not an
    error — and writes no second history row."""
    company_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        service = ConversationService(db)
        await service.mark_ready_now_for_opened_deal(
            company_id, deal_id=uuid.uuid4(), actor_id="user-7"
        )
        await db.commit()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).mark_ready_now_for_opened_deal(
            company_id, deal_id=uuid.uuid4(), actor_id="user-7"
        )
        await db.commit()

    assert len(await _history(company_id)) == 1


async def test_seam_s1_does_not_commit_so_the_caller_can_roll_it_back():
    """The rule that makes the seam safe: the deal row, the deal's history row and
    this gauge move land together or not at all. If this method committed, a
    deal transaction that failed after calling it would leave a company
    marked READY_NOW for a deal that was never opened."""
    company_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).mark_ready_now_for_opened_deal(
            company_id, deal_id=uuid.uuid4(), actor_id="user-7"
        )
        await db.rollback()

    assert (await _read(company_id)).conversation is ExporterConversation.NOT_CONTACTED
    assert await _history(company_id) == []


async def test_seam_s1_works_on_a_lead_and_clears_a_check_back_date():
    """Two deliberate differences from `set_conversation` (contract §6): no
    journey check, because refusing after the deal row is written would fail
    the deal's whole transaction over a gauge; and the check-back date is
    cleared, because the CHECK requires it and a company with an open deal is not
    waiting to be called back."""
    lead_id = await _company(ExporterJourney.LEAD)
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).mark_ready_now_for_opened_deal(
            lead_id, deal_id=uuid.uuid4(), actor_id="user-7"
        )
        await db.commit()
    assert (await _read(lead_id)).conversation is ExporterConversation.READY_NOW

    parked_id = await _company()
    await _set(
        parked_id,
        ExporterConversation.NOT_NOW,
        reason="Not now",
        check_back_on=date.today() + timedelta(days=30),
    )
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).mark_ready_now_for_opened_deal(
            parked_id, deal_id=uuid.uuid4(), actor_id="user-7"
        )
        await db.commit()
    profile = await _read(parked_id)
    assert profile.conversation is ExporterConversation.READY_NOW
    assert profile.conversation_check_back_on is None


# ── The routes ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {
        role: await token_with_role(client, role)
        for role in (UserRole.OPERATIONS, UserRole.DEVELOPER)
    }


async def test_the_read_serves_the_gauge_and_the_moves(client: AsyncClient, tokens):
    company_id = await _company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/conversation",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation"] == "NOT_CONTACTED"
    assert body["check_back_on"] is None
    assert body["journey"] == "PROSPECT"
    not_now = next(m for m in body["allowed_moves"] if m["to"] == "NOT_NOW")
    assert not_now == {
        "to": "NOT_NOW",
        "reason_required": True,
        "check_back_required": True,
    }


async def test_the_moves_route_answers_the_same_as_the_read(client: AsyncClient, tokens):
    """Two routes, one service method — §7.5's allowed-moves route on its own, and
    the panel's single-request read. They cannot disagree, and this is what says
    so."""
    company_id = await _company()
    headers = auth_header(tokens[UserRole.OPERATIONS])
    full = await client.get(f"{BASE}/exporters/{company_id}/conversation", headers=headers)
    moves = await client.get(
        f"{BASE}/exporters/{company_id}/conversation/moves", headers=headers
    )
    assert moves.status_code == 200, moves.text
    assert moves.json()["allowed_moves"] == full.json()["allowed_moves"]
    assert moves.json()["conversation"] == full.json()["conversation"]


async def test_a_reader_who_may_not_set_the_gauge_is_offered_no_moves(
    client: AsyncClient, tokens
):
    """DEVELOPER reads the CRM and writes nothing (contract §3), so it gets the
    gauge and an empty move list — never a button that would come back 403."""
    company_id = await _company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/conversation",
        headers=auth_header(tokens[UserRole.DEVELOPER]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["conversation"] == "NOT_CONTACTED"
    assert resp.json()["allowed_moves"] == []


async def test_a_lead_is_served_no_moves_but_still_reads(client: AsyncClient, tokens):
    company_id = await _company(ExporterJourney.LEAD)
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/conversation",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["journey"] == "LEAD"
    assert resp.json()["allowed_moves"] == []


async def test_the_write_route_moves_the_gauge_and_returns_the_new_moves(
    client: AsyncClient, tokens
):
    company_id = await _company()
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/conversation",
        json={"conversation": "NOT_NOW", "reason": "Q1 shipments", "check_back_on": "2027-01-15"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation"] == "NOT_NOW"
    assert body["check_back_on"] == "2027-01-15"
    # The moves that come back are the ones available *now* — NOT_NOW is no longer
    # among them, because it is the current value.
    assert "NOT_NOW" not in {m["to"] for m in body["allowed_moves"]}


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (
            {"conversation": "NOT_NOW", "reason": "Not now"},
            422,
            "CONVERSATION_CHECK_BACK_REQUIRED",
        ),
        (
            {"conversation": "INTERESTED", "check_back_on": "2027-01-15"},
            422,
            "CONVERSATION_CHECK_BACK_NOT_ALLOWED",
        ),
        (
            {"conversation": "NOT_NOW", "reason": "Not now", "check_back_on": "2020-01-15"},
            422,
            "CONVERSATION_CHECK_BACK_IN_PAST",
        ),
        (
            {"conversation": "NOT_CONTACTED"},
            409,
            "INVALID_CONVERSATION_TRANSITION",
        ),
    ],
)
async def test_the_route_refuses_with_the_documented_error_code(
    client: AsyncClient, tokens, body, status, code
):
    """Every refusal in engagement contract §7 reaches the caller as that
    contract's code — not as a 500, and not as a bare 422 a screen cannot explain
    (§7.7: at least one test for each refusal)."""
    company_id = await _company()
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/conversation",
        json=body,
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == status, resp.text
    assert resp.json()["error_code"] == code


async def test_the_route_refuses_a_move_on_a_lead(client: AsyncClient, tokens):
    company_id = await _company(ExporterJourney.LEAD)
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/conversation",
        json={"conversation": "REACHING_OUT"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "CONVERSATION_NOT_AVAILABLE"


async def test_the_route_404s_for_a_company_that_does_not_exist(client: AsyncClient, tokens):
    resp = await client.post(
        f"{BASE}/exporters/{uuid.uuid4()}/conversation",
        json={"conversation": "REACHING_OUT"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "EXPORTER_PROFILE_NOT_FOUND"


async def test_the_actor_comes_from_the_session_not_the_body(client: AsyncClient, tokens):
    """Architecture §7.5. `extra="forbid"` on the request schema means an attempt
    to supply one is a 422 rather than silently ignored — so the history can never
    name somebody the caller chose."""
    company_id = await _company()
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/conversation",
        json={"conversation": "REACHING_OUT", "actor_id": "somebody-else"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 422, resp.text
    assert await _history(company_id) == []


async def test_the_history_route_shows_the_conversation_dimension(
    client: AsyncClient, tokens
):
    """The gauge writes into the shared history log, so the panel's
    history comes from `?dimension=conversation` rather than from a second table
    of engagement's own."""
    company_id = await _company()
    await client.post(
        f"{BASE}/exporters/{company_id}/conversation",
        json={"conversation": "SPOKE_TO_THEM", "reason": "Spoke to the CFO"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history?dimension=conversation",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    [entry] = resp.json()["entries"]
    assert entry["dimension"] == "conversation"
    assert entry["to_value"] == "SPOKE_TO_THEM"
    assert entry["reason"] == "Spoke to the CFO"
    assert entry["source"] == "conversation_service.set_conversation"
