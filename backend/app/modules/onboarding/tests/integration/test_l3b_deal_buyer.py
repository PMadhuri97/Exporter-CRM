"""Migration 0018, the deal record, its buyer, and seam S1 (L3-05, L3-06).

The database-level cases go straight through ``psycopg2`` so they prove the
*database* refuses the bad row and not just the service — migration register §2:
every new constraint gets a direct-SQL violation test. The rest go through the
service and the API as a person would.

Real Postgres, each test minting its own company, like the rest of this package.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    DealBuyerRequiredError,
    DealCompanyNotFoundError,
    DealNotFoundError,
    DealTerminalError,
    DealTransitionNotAllowedError,
    DealWithdrawalReasonRequiredError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"

BUYER = {
    "name": "Rotterdam Trading BV",
    "country": "NL",
    "registration_number": "NL-8899",
    "tax_id": "NL123456789B01",
    "contact_email": "ap@rotterdamtrading.example",
    "contact_phone": "+31 10 555 0101",
}


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _company(journey: ExporterJourney = ExporterJourney.PROSPECT) -> uuid.UUID:
    """A company at ``journey``.

    The journey is set directly rather than driven through a qualification
    outcome: this file is about deals, and moving Developer 2's gauge properly
    would make every test here depend on their rules too.
    """
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = journey
        await db.commit()
    return company_id


async def _open(company_id: uuid.UUID, reference: str = "Rotterdam shipment, March"):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).open_deal(
            company_id, reference=reference, actor_id="tester"
        )


async def _transition(deal_id: uuid.UUID, to_stage: DealStage, **kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).transition_stage(
            deal_id, to_stage, actor_id=kwargs.pop("actor_id", "tester"), **kwargs
        )


async def _set_buyer(deal_id: uuid.UUID, **overrides):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).set_buyer(
            deal_id, actor_id="tester", **{**BUYER, **overrides}
        )


async def _get(deal_id: uuid.UUID):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).get_deal(deal_id)


async def _profile(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


async def _deal_history(company_id: uuid.UUID) -> list:
    """This company's deal history, **oldest first**.

    ``list_for_company`` returns newest first, which is what a panel wants;
    reversing here lets the assertions below read in the order the events
    happened.
    """
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(company_id, dimension="deal")
    return list(reversed(rows))


# ── The database refuses what the contract forbids ───────────────────────────


def test_a_deal_for_a_ghost_company_is_refused_by_the_database():
    """``fk_deal_company_id``. A deal whose company does not exist would be a
    financing need for nobody."""
    with _connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO onboarding.deal (company_id, reference, stage)"
                " VALUES (%s, %s, 'OPEN')",
                (str(uuid.uuid4()), "ghost"),
            )


def test_a_withdrawn_deal_without_a_reason_is_refused_by_the_database():
    """``ck_deal_withdrawal_reason``, first half — assumption A7."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO onboarding.deal (company_id, reference, stage)"
                " VALUES (%s, %s, 'WITHDRAWN')",
                (str(company_id), "no reason given"),
            )


def test_a_live_deal_carrying_a_withdrawal_reason_is_refused_by_the_database():
    """``ck_deal_withdrawal_reason``, second half. Both halves, so the column
    cannot fill with reasons for deals that are still live."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO onboarding.deal (company_id, reference, stage, withdrawal_reason)"
                " VALUES (%s, %s, 'OPEN', %s)",
                (str(company_id), "still open", "but has a reason"),
            )


def test_a_company_with_deals_cannot_be_deleted():
    """``ON DELETE RESTRICT``. Deleting the company would destroy the record of
    what was financed, so the database refuses rather than cascading."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.deal (company_id, reference, stage)"
            " VALUES (%s, %s, 'OPEN')",
            (str(company_id), "keeps the company alive"),
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "DELETE FROM onboarding.exporter_profile WHERE customer_id = %s",
                (str(company_id),),
            )


def test_a_second_buyer_on_one_deal_is_refused_by_the_database():
    """``uq_deal_buyer_deal_id``. "The buyer" on the handover payload has to be
    unambiguous (architecture §3.6)."""
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.deal (company_id, reference, stage)"
            " VALUES (%s, %s, 'OPEN') RETURNING id",
            (str(company_id), "two buyers?"),
        )
        deal_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO onboarding.deal_buyer (deal_id, name, country)"
            " VALUES (%s, %s, 'NL')",
            (str(deal_id), "First BV"),
        )
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(
                "INSERT INTO onboarding.deal_buyer (deal_id, name, country)"
                " VALUES (%s, %s, 'DE')",
                (str(deal_id), "Second GmbH"),
            )


def test_a_buyer_country_that_is_not_two_uppercase_letters_is_refused():
    """``ck_deal_buyer_country_iso``, so one country is not stored three ways.

    Two different refusals, both from the database and both worth pinning: the
    ``varchar(2)`` length rejects anything longer before the check ever runs, and
    the check itself rejects lowercase, digits and blanks.
    """
    cases = [
        ("nl", psycopg2.errors.CheckViolation),
        ("N1", psycopg2.errors.CheckViolation),
        ("  ", psycopg2.errors.CheckViolation),
        ("", psycopg2.errors.CheckViolation),
        ("NLD", psycopg2.errors.StringDataRightTruncation),
    ]
    with _connect() as connection, connection.cursor() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.deal (company_id, reference, stage)"
            " VALUES (%s, %s, 'OPEN') RETURNING id",
            (str(company_id), "bad country"),
        )
        deal_id = cursor.fetchone()[0]
        for bad, expected in cases:
            # A savepoint per attempt: a plain rollback would undo the company and
            # the deal these inserts depend on, and the next attempt would fail on
            # a foreign key instead of the constraint under test.
            cursor.execute("SAVEPOINT bad_country")
            with pytest.raises(expected):
                cursor.execute(
                    "INSERT INTO onboarding.deal_buyer (deal_id, name, country)"
                    " VALUES (%s, %s, %s)",
                    (str(deal_id), "Bad Country BV", bad),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT bad_country")


# ── Opening a deal, and seam S1 ──────────────────────────────────────────────


async def test_opening_a_deal_records_it_at_open_with_its_history():
    company_id = await _company()
    view = await _open(company_id)

    assert view.stage is DealStage.OPEN
    assert view.reference == "Rotterdam shipment, March"
    assert view.withdrawal_reason is None
    assert view.handed_over_at is None
    assert view.buyer is None

    rows = await _deal_history(company_id)
    assert [row.event_type for row in rows] == ["deal_initial"]
    assert rows[0].to_status == "OPEN"
    assert rows[0].from_status is None
    # A deal's history is part of its company's story, and says which deal.
    assert rows[0].customer_id == company_id
    assert rows[0].deal_id == view.id


async def test_opening_a_deal_sets_the_conversation_to_ready_now():
    """Seam S1 — architecture §3.3: "opening a deal also sets this". The gauge is
    moved through Developer 3A's service, never by assigning their column."""
    company_id = await _company()
    assert (await _profile(company_id)).conversation is ExporterConversation.NOT_CONTACTED

    deal = await _open(company_id)

    assert (await _profile(company_id)).conversation is ExporterConversation.READY_NOW
    # 3A's history row carries the deal that caused it.
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            company_id, dimension="conversation"
        )
    assert [row.deal_id for row in rows] == [deal.id]


async def test_a_second_deal_on_a_ready_company_is_not_an_error():
    """3A's method is idempotent, which is what makes this ordinary rather than a
    failure: opening another deal for a company that is already ready is normal
    (engagement contract §6)."""
    company_id = await _company()
    first = await _open(company_id, "first")
    second = await _open(company_id, "second")

    assert first.id != second.id
    assert (await _profile(company_id)).conversation is ExporterConversation.READY_NOW

    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            company_id, dimension="conversation"
        )
    # One gauge move, not two: the second open wrote no history row.
    assert len(rows) == 1


async def test_a_company_may_have_many_deals():
    company_id = await _company()
    for reference in ("one", "two", "three"):
        await _open(company_id, reference)

    async with db_services.AsyncSessionLocal() as db:
        views, total = await DealService(db).list_for_company(company_id)
    assert total == 3
    # Newest first.
    assert [view.reference for view in views] == ["three", "two", "one"]


async def test_opening_a_deal_for_a_company_that_does_not_exist_is_refused():
    with pytest.raises(DealCompanyNotFoundError):
        await _open(uuid.uuid4())


async def test_a_deal_needs_a_reference():
    company_id = await _company()
    with pytest.raises(ValidationError):
        await _open(company_id, "   ")


# ── Stage moves ──────────────────────────────────────────────────────────────


async def test_open_moves_to_gathering_paperwork_with_history():
    company_id = await _company()
    deal = await _open(company_id)

    moved = await _transition(deal.id, DealStage.GATHERING_PAPERWORK)
    assert moved.stage is DealStage.GATHERING_PAPERWORK

    rows = await _deal_history(company_id)
    assert [row.event_type for row in rows] == ["deal_initial", "deal_transition"]
    assert rows[-1].from_status == "OPEN"
    assert rows[-1].to_status == "GATHERING_PAPERWORK"


async def test_withdrawing_requires_a_reason_and_keeps_it():
    company_id = await _company()
    deal = await _open(company_id)

    with pytest.raises(DealWithdrawalReasonRequiredError):
        await _transition(deal.id, DealStage.WITHDRAWN)

    withdrawn = await _transition(
        deal.id, DealStage.WITHDRAWN, reason="Buyer cancelled the order"
    )
    assert withdrawn.stage is DealStage.WITHDRAWN
    assert withdrawn.withdrawal_reason == "Buyer cancelled the order"

    rows = await _deal_history(company_id)
    assert rows[-1].reason == "Buyer cancelled the order"


async def test_a_reason_on_a_non_withdrawal_is_refused_not_dropped():
    """Silently discarding it would leave the operator believing it was stored."""
    company_id = await _company()
    deal = await _open(company_id)

    with pytest.raises(ValidationError):
        await _transition(
            deal.id, DealStage.GATHERING_PAPERWORK, reason="not where this belongs"
        )


async def test_an_illegal_move_is_refused_and_changes_nothing():
    company_id = await _company()
    deal = await _open(company_id)

    with pytest.raises(DealTransitionNotAllowedError):
        await _transition(deal.id, DealStage.HANDED_OVER)

    assert (await _get(deal.id)).stage is DealStage.OPEN
    # Refused before anything was assigned, so no history row either.
    assert len(await _deal_history(company_id)) == 1


@pytest.mark.parametrize("target", [DealStage.GATHERING_PAPERWORK, DealStage.WITHDRAWN])
async def test_a_withdrawn_deal_never_moves_again(target: DealStage):
    company_id = await _company()
    deal = await _open(company_id)
    await _transition(deal.id, DealStage.WITHDRAWN, reason="fell through")

    with pytest.raises(DealTerminalError):
        await _transition(deal.id, target, reason="fell through")


async def test_a_move_on_a_deal_that_does_not_exist_is_a_404():
    with pytest.raises(DealNotFoundError):
        await _transition(uuid.uuid4(), DealStage.WITHDRAWN, reason="nothing there")


# ── The buyer ────────────────────────────────────────────────────────────────


async def test_a_buyer_is_recorded_and_returned_with_the_deal():
    company_id = await _company()
    deal = await _open(company_id)

    view = await _set_buyer(deal.id)
    assert view.buyer is not None
    assert view.buyer.name == "Rotterdam Trading BV"
    assert view.buyer.country == "NL"
    assert view.buyer.tax_id == "NL123456789B01"

    rows = await _deal_history(company_id)
    assert rows[-1].event_type == "deal_buyer_changed"
    assert rows[-1].event_metadata["buyer_name"] == "Rotterdam Trading BV"


async def test_setting_the_buyer_twice_replaces_the_same_row():
    """One buyer per deal (contract §3): the second call is an update, not a
    second row, which is what keeps the handover payload unambiguous."""
    company_id = await _company()
    deal = await _open(company_id)

    first = await _set_buyer(deal.id)
    second = await _set_buyer(deal.id, name="Hamburg Handels GmbH", country="DE")

    assert second.buyer is not None
    assert second.buyer.id == first.buyer.id
    assert second.buyer.name == "Hamburg Handels GmbH"
    assert second.buyer.country == "DE"

    rows = await _deal_history(company_id)
    changed = rows[-1].event_metadata["changed"]
    assert "name" in changed and "country" in changed


async def test_a_buyer_country_is_upper_cased_rather_than_refused():
    company_id = await _company()
    deal = await _open(company_id)

    view = await _set_buyer(deal.id, country="nl")
    assert view.buyer.country == "NL"


@pytest.mark.parametrize("bad_country", ["N", "NLD", "12", "  "])
async def test_a_buyer_country_that_is_not_two_letters_is_refused(bad_country: str):
    company_id = await _company()
    deal = await _open(company_id)

    with pytest.raises(ValidationError):
        await _set_buyer(deal.id, country=bad_country)


async def test_a_buyer_needs_a_name():
    company_id = await _company()
    deal = await _open(company_id)

    with pytest.raises(ValidationError):
        await _set_buyer(deal.id, name="  ")


async def test_blank_optional_buyer_fields_become_null():
    """"Not given" is one value in the database rather than three."""
    company_id = await _company()
    deal = await _open(company_id)

    view = await _set_buyer(deal.id, tax_id="   ", contact_phone="")
    assert view.buyer.tax_id is None
    assert view.buyer.contact_phone is None


async def test_a_terminal_deals_buyer_cannot_be_edited():
    """A withdrawn deal's buyer is history, and a handed-over deal's is what the
    lending team was given."""
    company_id = await _company()
    deal = await _open(company_id)
    await _set_buyer(deal.id)
    await _transition(deal.id, DealStage.WITHDRAWN, reason="fell through")

    with pytest.raises(DealTerminalError):
        await _set_buyer(deal.id, name="Too late BV")


# ── The A5 handover guard (Phase 4 completes it) ─────────────────────────────


async def test_handover_needs_a_buyer_before_anything_else():
    company_id = await _company(ExporterJourney.CUSTOMER)
    deal = await _open(company_id)
    await _transition(deal.id, DealStage.GATHERING_PAPERWORK)

    with pytest.raises(DealBuyerRequiredError):
        await _transition(deal.id, DealStage.HANDED_OVER)


async def test_handover_is_blocked_because_no_background_check_exists_yet():
    """Assumption A5's second half cannot be evaluated: Developer 4's migration
    0015 has not landed, so ``exporter_profile`` has no ``background_check``
    column. "Not recorded" must not be treated as "clear" — that would hand a deal
    to the lending team on the strength of a column that does not exist.

    When 0015 lands, this test should start failing on the *reason* rather than on
    the refusal, which is the signal to wire Developer 4's read helper in.
    """
    company_id = await _company(ExporterJourney.CUSTOMER)
    deal = await _open(company_id)
    await _set_buyer(deal.id)
    await _transition(deal.id, DealStage.GATHERING_PAPERWORK)

    view = await _get(deal.id)
    assert view.handover_blocked_reason is not None
    assert "background check is not recorded yet" in view.handover_blocked_reason
    # Not offered, so the screen explains instead of showing a button that 409s.
    assert DealStage.HANDED_OVER not in {move.to for move in view.allowed_stage_moves}

    with pytest.raises(Exception) as caught:
        await _transition(deal.id, DealStage.HANDED_OVER)
    assert getattr(caught.value, "error_code", None) == "DEAL_HANDOVER_BLOCKED"


async def test_a_prospect_is_blocked_for_the_journey_reason():
    """A5's first half, which *can* be evaluated today."""
    company_id = await _company(ExporterJourney.PROSPECT)
    deal = await _open(company_id)
    await _set_buyer(deal.id)
    await _transition(deal.id, DealStage.GATHERING_PAPERWORK)

    view = await _get(deal.id)
    assert "not CUSTOMER" in (view.handover_blocked_reason or "")


# ── The API ──────────────────────────────────────────────────────────────────


async def test_the_api_opens_lists_and_reads_a_deal(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    opened = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "Dubai order"},
        headers=auth_header(token),
    )
    assert opened.status_code == 201, opened.text
    deal_id = opened.json()["id"]
    assert opened.json()["stage"] == "OPEN"

    listing = await client.get(
        f"{BASE}/exporters/{company_id}/deals", headers=auth_header(token)
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["deals"][0]["reference"] == "Dubai order"

    detail = await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text
    # The server serves the allowed moves (§7.5), so the screen keeps no copy.
    assert {move["to_stage"] for move in detail.json()["allowed_stage_moves"]} == {
        "GATHERING_PAPERWORK",
        "WITHDRAWN",
    }


async def test_the_api_moves_a_stage_and_records_a_buyer(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    company_id = await _company()
    opened = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "Hamburg order"},
        headers=auth_header(token),
    )
    deal_id = opened.json()["id"]

    buyer = await client.put(
        f"{BASE}/deals/{deal_id}/buyer", json=BUYER, headers=auth_header(token)
    )
    assert buyer.status_code == 200, buyer.text
    assert buyer.json()["buyer"]["name"] == "Rotterdam Trading BV"

    moved = await client.post(
        f"{BASE}/deals/{deal_id}/transitions",
        json={"to_stage": "GATHERING_PAPERWORK"},
        headers=auth_header(token),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["stage"] == "GATHERING_PAPERWORK"


async def test_the_api_refuses_an_illegal_move_with_its_code(client: AsyncClient):
    token = await token_with_role(client, UserRole.ADMIN)
    company_id = await _company()
    opened = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "skip ahead"},
        headers=auth_header(token),
    )

    resp = await client.post(
        f"{BASE}/deals/{opened.json()['id']}/transitions",
        json={"to_stage": "HANDED_OVER"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "DEAL_TRANSITION_NOT_ALLOWED"


async def test_the_api_refuses_a_stage_on_the_open_request(client: AsyncClient):
    """``extra="forbid"``: a caller cannot create a deal that is already handed
    over, skipping every guard."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _company()

    resp = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "sneaky", "stage": "HANDED_OVER"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_developer_may_read_a_deal_but_not_open_one(client: AsyncClient):
    """Architecture §3.7: DEVELOPER reads the CRM and writes nothing."""
    staff = await token_with_role(client, UserRole.OPERATIONS)
    developer = await token_with_role(client, UserRole.DEVELOPER)
    company_id = await _company()
    opened = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "read only"},
        headers=auth_header(staff),
    )
    deal_id = opened.json()["id"]

    assert (
        await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(developer))
    ).status_code == 200
    refused = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        json={"reference": "nope"},
        headers=auth_header(developer),
    )
    assert refused.status_code == 403, refused.text
