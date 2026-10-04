"""A deal's invoicing branch, and the two handover rules that read it — tasks 2.8
and 2.9 (**owner: Developer 2**, plan P6-6, P6-7, decisions BQ-6, IQ-20).

What is worth testing:

* **The branch must be the seller's.** A deal invoiced through a stranger's branch
  would put their GSTIN on the invoice, and the guard would be asking about a branch
  whose flag belongs to a different company. The composite FK is exercised with raw
  SQL, because that is the half a service check cannot be trusted to cover.
* **It may change before handover and not after** (IQ-20) — the opposite of
  ``buyer_company_id``, and worth pinning so the two are not "simplified" into one
  rule later.
* **A flagged branch blocks only the deals invoiced through it** (BQ-6). The whole
  point of flagging a branch rather than a company.
* **"Record the branch" is asked only of a seller that has one.** A seller with no
  active registration is not blocked on a field it cannot fill.
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
from app.modules.onboarding.application.gst_registration_service import (
    GstRegistrationService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.exceptions import (
    DealHandoverBlockedError,
    DealTerminalError,
    GstRegistrationInactiveError,
    GstRegistrationNotFoundError,
    GstRegistrationNotThisCompanysError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str, state: str = "27") -> str:
    return f"{state}{pan}1Z5"


async def _seller_with_branches(*states: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A PROSPECT (so a deal may be opened on it) with one branch per state."""
    pan = _pan()
    customer_id = await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id,
            {"name": f"Branch Seller {uuid.uuid4().hex[:8]}", "country": "IN", "pan": pan},
            actor_id="test",
        )
    ids: list[uuid.UUID] = []
    for state in states:
        async with db_services.AsyncSessionLocal() as db:
            registration, _o = await GstRegistrationService(db).add(
                customer_id, gstin=_gstin(pan, state), actor_id="rm-1"
            )
            ids.append(registration.id)
    return customer_id, ids


async def _deal(seller: uuid.UUID) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Branch deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    return view.id


async def _reload(deal_id: uuid.UUID) -> Deal:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(select(Deal).where(Deal.id == deal_id))


# ── 2.8: recording the branch ─────────────────────────────────────────────────


async def test_recording_the_branch_stores_it_and_records_the_state_not_the_gstin():
    seller, [maharashtra] = await _seller_with_branches("27")
    deal_id = await _deal(seller)

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=maharashtra, actor_id="rm-1"
        )
    assert view.seller_gst_registration_id == maharashtra
    assert (await _reload(deal_id)).seller_gst_registration_id == maharashtra

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_deal(deal_id, limit=20)
    [row] = [r for r in rows if r.event_type == "deal_invoicing_branch_set"]
    assert row.event_metadata["state_name"] == "Maharashtra"
    # The state identifies the branch to a reader; the GSTIN would be an unmasked
    # identifier in a log every CRM role can see.
    assert "gstin" not in row.event_metadata


async def test_another_companys_branch_is_refused():
    seller, _ = await _seller_with_branches("27")
    other, [theirs] = await _seller_with_branches("29")
    deal_id = await _deal(seller)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(GstRegistrationNotThisCompanysError):
            await DealService(db).set_invoicing_branch(
                deal_id, gst_registration_id=theirs, actor_id="rm-1"
            )
    assert (await _reload(deal_id)).seller_gst_registration_id is None


async def test_the_composite_fk_refuses_another_companys_branch_in_raw_sql():
    """``fk_deal_seller_gst_registration_id`` is composite since migration 0036. The
    service check names the problem; this proves the database would refuse it even if
    something wrote the column directly — which the buyer migration and any future
    backfill do."""
    seller, _ = await _seller_with_branches("27")
    _other, [theirs] = await _seller_with_branches("29")
    deal_id = await _deal(seller)

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cursor.execute(
                    "UPDATE onboarding.deal SET seller_gst_registration_id = %s WHERE id = %s",
                    (str(theirs), str(deal_id)),
                )
    finally:
        connection.close()


async def test_a_deactivated_branch_cannot_be_the_invoicing_branch():
    """The row is a real row of the right company, so only the service can refuse
    this — and it refuses at the point of choosing rather than at handover, so the
    person picking sees the problem while they are picking."""
    seller, [branch] = await _seller_with_branches("27")
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).deactivate(branch, actor_id="rm-1")
    deal_id = await _deal(seller)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(GstRegistrationInactiveError):
            await DealService(db).set_invoicing_branch(
                deal_id, gst_registration_id=branch, actor_id="rm-1"
            )


async def test_an_unknown_registration_is_a_404():
    seller, _ = await _seller_with_branches("27")
    deal_id = await _deal(seller)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(GstRegistrationNotFoundError):
            await DealService(db).set_invoicing_branch(
                deal_id, gst_registration_id=uuid.uuid4(), actor_id="rm-1"
            )


async def test_the_branch_may_change_before_handover_and_be_cleared():
    """Decision IQ-20, and deliberately the **opposite** of `buyer_company_id`'s
    set-once rule: choosing the wrong branch has no consequence until the handover
    reads it, while a buyer company accumulates compliance results under it."""
    seller, [first, second] = await _seller_with_branches("27", "29")
    deal_id = await _deal(seller)

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=first, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=second, actor_id="rm-1"
        )
    assert (await _reload(deal_id)).seller_gst_registration_id == second

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=None, actor_id="rm-1"
        )
    assert (await _reload(deal_id)).seller_gst_registration_id is None


async def test_setting_the_same_branch_again_records_nothing():
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _deal(seller)
    for _ in range(2):
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).set_invoicing_branch(
                deal_id, gst_registration_id=branch, actor_id="rm-1"
            )
    async with db_services.AsyncSessionLocal() as db:
        rows, _t = await HistoryService(db).list_for_deal(deal_id, limit=20)
    assert len([r for r in rows if r.event_type == "deal_invoicing_branch_set"]) == 1


async def test_a_closed_deals_branch_cannot_be_changed():
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _deal(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealTerminalError):
            await DealService(db).set_invoicing_branch(
                deal_id, gst_registration_id=branch, actor_id="rm-1"
            )


async def test_the_trigger_freezes_a_closed_deals_branch_in_raw_sql():
    """``prevent_terminal_deal_change()`` gained the column in migration 0036."""
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _deal(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cursor.execute(
                    "UPDATE onboarding.deal SET seller_gst_registration_id = %s WHERE id = %s",
                    (str(branch), str(deal_id)),
                )
            assert "no longer changes" in str(caught.value)
    finally:
        connection.close()


async def test_the_route_records_the_branch(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _deal(seller)

    resp = await client.put(
        f"{BASE}/deals/{deal_id}/invoicing-branch",
        json={"gst_registration_id": str(branch)},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["seller_gst_registration_id"] == str(branch)


# ── 2.9: the two handover rules (plan P6-7) ───────────────────────────────────


async def _ready_to_hand_over(seller: uuid.UUID) -> uuid.UUID:
    """A deal at GATHERING_PAPERWORK with everything but the branch rules satisfied."""
    from app.modules.onboarding.tests.integration._dev1_support import cleared_company
    from app.modules.onboarding.tests.integration.test_l3b_handover import (
        _add_required_document,
        record_legacy_buyer_checks,
    )

    await cleared_company(seller)
    deal_id = await _deal(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            deal_id, name="Rotterdam Trading BV", country="NL", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.GATHERING_PAPERWORK, actor_id="rm-1"
        )
    await _add_required_document(deal_id)
    await record_legacy_buyer_checks(deal_id)
    return deal_id


async def test_a_seller_with_a_branch_must_say_which_one(client: AsyncClient):
    """P6-7's second rule. The deal is otherwise ready; the only objection is that it
    does not say where it is invoiced from."""
    seller, [_branch] = await _seller_with_branches("27")
    deal_id = await _ready_to_hand_over(seller)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DealHandoverBlockedError) as caught:
            await DealService(db).transition_stage(
                deal_id, DealStage.HANDED_OVER, actor_id="rm-1"
            )
    assert "invoicing branch is not recorded" in caught.value.detail


async def test_a_seller_with_no_registration_is_not_asked_for_one():
    """The difference between a rule and a nuisance: some sellers legitimately have no
    GST registration, and blocking them on a field they cannot fill would be wrong."""
    seller = await make_prospect()
    deal_id = await _ready_to_hand_over(seller)

    async with db_services.AsyncSessionLocal() as db:
        blocked = await DealService(db)._handover_blocked_reason(await _reload(deal_id))
    assert blocked is None or "invoicing branch" not in blocked


async def test_recording_the_branch_satisfies_the_rule():
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _ready_to_hand_over(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=branch, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        blocked = await DealService(db)._handover_blocked_reason(await _reload(deal_id))
    assert blocked is None, blocked


async def test_a_flagged_branch_blocks_the_deals_invoiced_through_it():
    seller, [maharashtra] = await _seller_with_branches("27")
    deal_id = await _ready_to_hand_over(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=maharashtra, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            maharashtra, reason="Returns unfiled", actor_id="compliance-1"
        )

    async with db_services.AsyncSessionLocal() as db:
        blocked = await DealService(db)._handover_blocked_reason(await _reload(deal_id))
    assert blocked is not None
    # The state is named, which is why the reader returns it.
    assert "invoicing branch Maharashtra is flagged" in blocked


async def test_a_deal_from_another_branch_is_unaffected():
    """Decision BQ-6, and the whole point of flagging a branch rather than a company:
    a company trading through five states may have a problem in one of them."""
    seller, [maharashtra, karnataka] = await _seller_with_branches("27", "29")
    flagged_deal = await _ready_to_hand_over(seller)
    clean_deal = await _deal(seller)

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            flagged_deal, gst_registration_id=maharashtra, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            clean_deal, gst_registration_id=karnataka, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            maharashtra, reason="Returns unfiled", actor_id="compliance-1"
        )

    async with db_services.AsyncSessionLocal() as db:
        service = DealService(db)
        flagged_reason = await service._handover_blocked_reason(await _reload(flagged_deal))
        clean_reason = await service._handover_blocked_reason(await _reload(clean_deal))
    assert flagged_reason is not None and "flagged" in flagged_reason
    # The clean deal has its own unmet conditions (it never gathered paperwork), but
    # the branch must not be among them.
    assert clean_reason is None or "flagged" not in clean_reason


async def test_lifting_the_flag_unblocks_the_handover():
    seller, [branch] = await _seller_with_branches("27")
    deal_id = await _ready_to_hand_over(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=branch, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            branch, reason="Returns unfiled", actor_id="compliance-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).unflag(
            branch, reason="Returns filed and verified", actor_id="compliance-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        blocked = await DealService(db)._handover_blocked_reason(await _reload(deal_id))
    assert blocked is None, blocked
