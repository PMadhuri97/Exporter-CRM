"""A deal's buyer as a company record — task 2.4 (**owner: Developer 2**, plan P4-4).

What matters here is not that the column can be written, but the rules around it:

* **Set once**, enforced by the service *and* by
  ``trg_deal_buyer_company_set_once`` behind it. Migration register §2 asks for a
  direct-SQL violation test on every new constraint, so the trigger is exercised
  through ``psycopg2`` and not only through the service — otherwise "the database
  refuses it" would be an untested claim.
* **Frozen with the deal.** ``prevent_terminal_deal_change()`` gains
  ``buyer_company_id``, also tested with raw SQL.
* **Either form, never both.** The route still accepts a legacy ``deal_buyer``
  body, because deals written before the buyer migration have one; a request
  carrying both is refused rather than merged.
* **"Needs a buyer" is satisfied by either**, so a handover is not blocked for a
  deal the migration has not reached and is not allowed for one with nothing.
* **The handover snapshot prefers the company**, since that is what the lending
  team is actually being handed.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.exceptions import (
    DealBuyerCompanyAlreadySetError,
    DealBuyerIsTheSellerError,
    DealBuyerRequiredError,
    DealCompanyNotFoundError,
    DealTerminalError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _connect():
    """The same sync connection `test_l3b_deal_buyer.py` uses for its raw-SQL cases."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _deal(seller: uuid.UUID | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """An open deal and its selling company."""
    seller = seller or await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    return view.id, seller


async def _reload(deal_id: uuid.UUID) -> Deal:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(select(Deal).where(Deal.id == deal_id))


# ── The write path ────────────────────────────────────────────────────────────


async def test_naming_a_buyer_company_records_it_and_its_history():
    deal_id, seller = await _deal()
    buyer = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )
    assert view.buyer_company is not None
    assert view.buyer_company.company_id == buyer
    assert (await _reload(deal_id)).buyer_company_id == buyer

    # On the seller's timeline, with the deal id, like every other deal row.
    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_deal(deal_id, limit=20)
    [row] = [r for r in rows if r.event_type == "deal_buyer_company_set"]
    assert row.customer_id == seller
    assert row.deal_id == deal_id
    assert row.event_metadata["buyer_company_id"] == str(buyer)
    assert row.event_metadata["had_legacy_buyer"] is False


async def test_naming_the_same_company_again_changes_nothing_and_is_not_an_error():
    """A retried request must not fail. Nothing changed, so nothing is recorded —
    a second history row would make the record read as two decisions."""
    deal_id, _seller = await _deal()
    buyer = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_deal(deal_id, limit=20)
    assert len([r for r in rows if r.event_type == "deal_buyer_company_set"]) == 1


async def test_a_different_buyer_company_is_refused():
    """Set once. The buyer company is what the buyer's checks are recorded against
    and read back through, so re-pointing it would silently reinterpret them."""
    deal_id, _seller = await _deal()
    first, second = await make_company(), await make_company()

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=first, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealBuyerCompanyAlreadySetError) as caught:
            await DealService(db).set_buyer_company(
                deal_id, buyer_company_id=second, actor_id="rm-1"
            )
    assert str(first) in caught.value.detail
    assert (await _reload(deal_id)).buyer_company_id == first


async def test_a_company_cannot_be_its_own_buyer():
    deal_id, seller = await _deal()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealBuyerIsTheSellerError):
            await DealService(db).set_buyer_company(
                deal_id, buyer_company_id=seller, actor_id="rm-1"
            )
    assert (await _reload(deal_id)).buyer_company_id is None


async def test_an_unknown_company_is_a_404_naming_it():
    deal_id, _seller = await _deal()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealCompanyNotFoundError):
            await DealService(db).set_buyer_company(
                deal_id, buyer_company_id=uuid.uuid4(), actor_id="rm-1"
            )


async def test_a_closed_deal_takes_no_buyer_company():
    deal_id, _seller = await _deal()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealTerminalError):
            await DealService(db).set_buyer_company(
                deal_id, buyer_company_id=await make_company(), actor_id="rm-1"
            )


# ── The database refuses it too (migration register §2) ───────────────────────


async def test_the_trigger_refuses_a_second_buyer_company_in_raw_sql():
    """``trg_deal_buyer_company_set_once``. Through psycopg2 so this proves the
    *database* refuses it: a service-only rule is one careless UPDATE from being
    bypassed, and the buyer migration writes this column directly."""
    deal_id, _seller = await _deal()
    first, second = await make_company(), await make_company()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=first, actor_id="rm-1"
        )

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cursor.execute(
                    "UPDATE onboarding.deal SET buyer_company_id = %s WHERE id = %s",
                    (str(second), str(deal_id)),
                )
            assert "immutable once set" in str(caught.value)
    finally:
        connection.close()
    assert (await _reload(deal_id)).buyer_company_id == first


async def test_the_trigger_allows_the_first_write_so_the_migration_can_fill_it():
    """``NULL`` → a value once, which is what lets the buyer migration (P4-6) fill a
    deal whose buyer is only a ``deal_buyer`` row today."""
    deal_id, _seller = await _deal()
    buyer = await make_company()

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE onboarding.deal SET buyer_company_id = %s WHERE id = %s",
                (str(buyer), str(deal_id)),
            )
    finally:
        connection.close()
    assert (await _reload(deal_id)).buyer_company_id == buyer


async def test_a_closed_deals_buyer_company_is_frozen_in_raw_sql():
    """``prevent_terminal_deal_change()`` gains ``buyer_company_id`` (P4-4): a
    handed-over deal's buyer is what the lending team was given.

    Note this also refuses a *first* write to a closed deal, which the set-once rule
    alone would allow — which is why both guards exist.
    """
    deal_id, _seller = await _deal()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )
    buyer = await make_company()

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cursor.execute(
                    "UPDATE onboarding.deal SET buyer_company_id = %s WHERE id = %s",
                    (str(buyer), str(deal_id)),
                )
            assert "no longer changes" in str(caught.value)
    finally:
        connection.close()


# ── The route takes either form, never both ───────────────────────────────────


async def test_the_route_records_a_buyer_company(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, _seller = await _deal()
    buyer = await make_company()

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(buyer)},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buyer_company"]["company_id"] == str(buyer)
    # The legacy row is untouched — this deal never had one.
    assert body["buyer"] is None


async def test_the_route_still_records_a_legacy_buyer(client: AsyncClient):
    """Deals written before the buyer migration have one, and it is the only place
    such a deal's sanctions and AML can be recorded (BQ-4 needs them)."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, _seller = await _deal()

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"name": "Rotterdam Trading BV", "country": "NL"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["buyer"]["name"] == "Rotterdam Trading BV"
    assert resp.json()["buyer_company"] is None


async def test_both_forms_at_once_are_refused(client: AsyncClient):
    """Refused rather than merged: the two disagree about what a buyer *is*, and
    writing both would leave a deal whose company says one thing and whose row says
    another, with no way to tell which was meant."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, _seller = await _deal()
    buyer = await make_company()

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(buyer), "name": "Rotterdam Trading BV"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert "not both" in resp.text
    assert (await _reload(deal_id)).buyer_company_id is None


async def test_neither_form_complete_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, _seller = await _deal()

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"name": "Rotterdam Trading BV"},  # no country
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_the_route_reports_a_second_company_as_a_conflict(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, _seller = await _deal()
    first, second = await make_company(), await make_company()

    await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(first)},
        headers=auth_header(token),
    )
    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(second)},
        headers=auth_header(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DEAL_BUYER_COMPANY_ALREADY_SET"


async def test_the_seller_is_refused_as_its_own_buyer_by_the_route(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id, seller = await _deal()

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(seller)},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "DEAL_BUYER_IS_THE_SELLER"


# ── "Needs a buyer" is satisfied by either ────────────────────────────────────


async def test_a_handover_needs_a_buyer_of_some_kind():
    deal_id, _seller = await _deal()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.GATHERING_PAPERWORK, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealBuyerRequiredError):
            await DealService(db).transition_stage(
                deal_id, DealStage.HANDED_OVER, actor_id="rm-1"
            )


async def test_a_buyer_company_satisfies_the_handover_buyer_rule():
    """Before this, only a ``deal_buyer`` row counted — so a deal recorded the new
    way could never be handed over. The guard reads either (contract §3.0)."""
    deal_id, _seller = await _deal()
    buyer = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.GATHERING_PAPERWORK, actor_id="rm-1"
        )

    # Not DealBuyerRequiredError: the buyer rule is satisfied. Whatever stops the
    # handover now is one of the compliance conditions, which is a different test's
    # subject — this one only proves the buyer is no longer the objection.
    async with db_services.AsyncSessionLocal() as db:
        try:
            await DealService(db).transition_stage(
                deal_id, DealStage.HANDED_OVER, actor_id="rm-1"
            )
        except DealBuyerRequiredError:  # pragma: no cover - the regression this guards
            pytest.fail("a buyer company must satisfy the handover's buyer rule")
        except Exception:
            pass


# ── The handover snapshot is built from the company ───────────────────────────


async def test_the_handover_snapshot_carries_the_buyer_company_not_a_legacy_row():
    """What the lending team is handed. The snapshot's keys are the same whichever
    era wrote it, so a reader never has to know — but the *values* must come from the
    company once a deal names one, because that is the buyer.

    `tax_id` is the company's PAN: a company has no `tax_id` column of its own, PAN
    being the Indian equivalent. The contact fields are empty on purpose — a
    company's contacts are people on its own record, and picking one here would put a
    name in the handover that nobody chose.
    """
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
        VerificationType,
    )
    from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
    from app.modules.onboarding.tests.integration._dev1_support import cleared_company
    from app.modules.onboarding.tests.integration.test_l3b_handover import (
        _add_required_document,
    )

    seller = await make_prospect()
    await cleared_company(seller)

    # The buyer, as a company with its own identity.
    pan_letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    buyer_pan = f"{pan_letters[:5]}{uuid.uuid4().int % 10**4:04d}{pan_letters[5]}"
    registration = f"REG-{uuid.uuid4().hex[:10].upper()}"
    buyer = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            buyer,
            source=ExporterSource.SALES,
            name="Rotterdam Trading BV",
            country="NL",
            pan=buyer_pan,
            registration_number=registration,
        )

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Snapshot {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    deal_id = view.id
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.GATHERING_PAPERWORK, actor_id="rm-1"
        )
    await _add_required_document(deal_id)

    # BQ-4: the buyer's sanctions and AML must both be PASSED. Recorded against the
    # buyer **company** — which is where `for_company` reads them, and the whole
    # point of a buyer being a company record.
    for verification_type in (VerificationType.SANCTIONS, VerificationType.AML):
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).trigger_verification(
                verification_type,
                VerificationEntityType.EXPORTER,
                buyer,
                provider="manual",
                payload={"status": "PASSED"},
                actor_id="tester",
                evidence=VerificationEvidence(note="Test: screened the buyer company."),
            )

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="rm-1"
        )

    snapshot = (await _reload(deal_id)).handover_snapshot
    assert snapshot is not None
    assert snapshot["buyer_company_id"] == str(buyer)
    assert snapshot["buyer"]["name"] == "Rotterdam Trading BV"
    assert snapshot["buyer"]["country"] == "NL"
    assert snapshot["buyer"]["registration_number"] == registration
    assert snapshot["buyer"]["tax_id"] == buyer_pan
    assert snapshot["buyer"]["contact_email"] is None
    assert snapshot["buyer"]["contact_phone"] is None
