"""GST registrations as branches — tasks 3.12, 3.13, 3.14, 3.15, 3.17
(**owner: Developer 3**, plan P6-1, P6-2, P6-5, and P6-3's consequences).

The claims worth testing, as opposed to restating the schema:

* **A registration is never deleted.** Migration register §2 asks for a direct-SQL
  violation test on every new constraint, and this one matters more than most: before
  task 3.12 a company edit *did* delete rows, and once a deal records its invoicing
  branch that delete either fails on an FK or destroys the record of a branch the
  company really traded through.
* **The state is derived, never entered**, and an unknown code is recorded as unknown
  rather than guessed.
* **A flag is per branch and per company.** Flagging Maharashtra must not stop
  Karnataka, and must not touch another company that holds the same GSTIN (IQ-9).
* **The portal link follows the masking.** The URL contains the GSTIN, so serving it
  to a role that sees the value masked would hand over exactly what masking withholds.
* **The migration's state mapping and the live one agree**, for the same reason
  migration 0033's does: a code added to one and not the other must fail a test
  rather than silently leave a branch stateless.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.branch_flags import BranchFlagService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.gst_registration_service import (
    HISTORY_DIMENSION_GST,
    GstRegistrationService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterSource,
    GstRegistrationFlag,
    GstRegistrationStatus,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.gst_states import (
    GST_STATE_NAMES,
    state_code_of,
    state_name_of,
)
from app.modules.onboarding.exceptions import GstRegistrationAlreadyActiveError
from app.modules.onboarding.migrations.onboarding_0035_gst_branch import _STATE_NAMES
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str, state: str = "27") -> str:
    """A GSTIN carrying this PAN, in this state. Characters 3–12 are the PAN, which
    is the rule every write path checks."""
    return f"{state}{pan}1Z5"


async def _company_with_pan() -> tuple[uuid.UUID, str]:
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            name=f"Branch Co {uuid.uuid4().hex[:8]}",
            country="IN",
            pan=pan,
        )
    return customer_id, pan


# ── The two state mappings agree ──────────────────────────────────────────────


def test_the_migrations_state_mapping_matches_the_live_one():
    """Migration 0035 freezes the mapping as SQL; ``domain/gst_states.py`` is what
    new registrations use. They are deliberately separate — a migration that imported
    evolving application code would change meaning under us — so this is the test
    that keeps them honest."""
    assert dict(_STATE_NAMES) == GST_STATE_NAMES


def test_a_state_is_derived_from_the_gstin_and_an_unknown_code_is_not_guessed():
    assert state_code_of("27ABCDE1234F1Z5") == "27"
    assert state_name_of("27ABCDE1234F1Z5") == "Maharashtra"
    assert state_name_of("29ABCDE1234F1Z5") == "Karnataka"
    # The format check accepts any two digits, so a code we do not know can arrive.
    # It is recorded as unknown rather than guessed.
    assert state_code_of("77ABCDE1234F1Z5") == "77"
    assert state_name_of("77ABCDE1234F1Z5") is None
    assert state_code_of(None) is None
    assert state_code_of("X7ABCDE1234F1Z5") is None


# ── A registration is never deleted (task 3.12) ───────────────────────────────


async def test_raw_sql_cannot_delete_a_gst_registration():
    """``trg_exporter_gstin_no_delete``, through psycopg2 so this proves the
    *database* refuses it. Before task 3.12 the ORM deleted these rows on a company
    edit, which is exactly the behaviour a service-only rule would have left in
    place."""
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _others = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cursor.execute(
                    "DELETE FROM onboarding.exporter_gstin WHERE id = %s",
                    (str(registration_id),),
                )
            assert "deactivate it instead" in str(caught.value)
    finally:
        connection.close()

    async with db_services.AsyncSessionLocal() as db:
        assert await db.scalar(
            select(ExporterGstin).where(ExporterGstin.id == registration_id)
        ) is not None


async def test_a_company_edit_no_longer_touches_its_registrations(client: AsyncClient):
    """The behaviour change behind task 3.13: ``gstins`` is not a field a PATCH may
    send any more, so the whole-list replace — and the deletes it caused — is gone."""
    _user_id, token = await user_with_role(client, UserRole.ADMIN)
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).add(customer_id, gstin=_gstin(pan), actor_id="rm-1")

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"gstins": []},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text

    async with db_services.AsyncSessionLocal() as db:
        rows = await GstRegistrationService(db).list_for_company(customer_id)
    assert len(rows) == 1 and rows[0].active


# ── Adding, reactivating, deactivating (task 3.13) ────────────────────────────


async def test_adding_a_registration_derives_its_state_and_records_history():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, others = await GstRegistrationService(db).add(
            customer_id,
            gstin=_gstin(pan, "29"),
            address="12 Industrial Layout, Bengaluru",
            actor_id="rm-1",
        )
    assert registration.state_code == "29"
    assert registration.state_name == "Karnataka"
    assert registration.status is GstRegistrationStatus.UNVERIFIED
    assert registration.active is True
    assert others == []

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_GST, limit=10
        )
    [row] = list(rows)
    assert row.event_type == "gst_registration_added"
    assert row.to_status == "Karnataka"
    # The GSTIN is masked in the row: the history read route shows it to every CRM
    # reader, including roles that only ever see a GSTIN masked on the company.
    assert row.event_metadata["gstin"] != registration.gstin
    assert "•" in row.event_metadata["gstin"]


async def test_a_gstin_that_does_not_carry_the_companys_pan_is_refused():
    customer_id, _pan_value = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="does not contain"):
            await GstRegistrationService(db).add(
                customer_id, gstin=_gstin(_pan()), actor_id="rm-1"
            )


async def test_adding_the_same_active_gstin_twice_is_a_conflict():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).add(customer_id, gstin=_gstin(pan), actor_id="rm-1")
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(GstRegistrationAlreadyActiveError):
            await GstRegistrationService(db).add(
                customer_id, gstin=_gstin(pan), actor_id="rm-1"
            )


async def test_deactivating_keeps_the_row_and_drops_it_from_the_companys_gstins():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id

    async with db_services.AsyncSessionLocal() as db:
        deactivated = await GstRegistrationService(db).deactivate(
            registration_id, reason="Branch closed", actor_id="rm-1"
        )
    assert deactivated.active is False
    assert deactivated.deactivated_at is not None
    assert deactivated.deactivated_by == "rm-1"

    # The row stays, and stays listed — a deal handed over through it names it.
    async with db_services.AsyncSessionLocal() as db:
        rows = await GstRegistrationService(db).list_for_company(customer_id)
        active = await GstRegistrationService(db).list_for_company(
            customer_id, include_inactive=False
        )
    assert len(rows) == 1
    assert active == []

    # But it is no longer one of the company's GSTINs.
    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(customer_id)
    assert list(detail.gstins) == []


async def test_deactivating_twice_is_a_no_op():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id
    for _ in range(2):
        async with db_services.AsyncSessionLocal() as db:
            await GstRegistrationService(db).deactivate(registration_id, actor_id="rm-1")

    async with db_services.AsyncSessionLocal() as db:
        rows, _t = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_GST, limit=10
        )
    assert len([r for r in rows if r.event_type == "gst_registration_deactivated"]) == 1


async def test_re_adding_a_deactivated_gstin_reactivates_the_same_row():
    """One row per company and GSTIN forever, which is what
    ``uq_exporter_gstin_customer_gstin`` already said — and what keeps a handed-over
    deal's invoicing branch pointing at the branch it really used."""
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        first, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        first_id = first.id
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).deactivate(first_id, actor_id="rm-1")
    async with db_services.AsyncSessionLocal() as db:
        again, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
    assert again.id == first_id
    assert again.active is True
    assert again.deactivated_at is None

    async with db_services.AsyncSessionLocal() as db:
        rows = await GstRegistrationService(db).list_for_company(customer_id)
    assert len(rows) == 1


# ── Flagging a branch (task 3.14) ─────────────────────────────────────────────


async def test_flagging_a_branch_needs_a_reason_and_records_it():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="reason"):
            await GstRegistrationService(db).flag(
                registration_id, reason="   ", actor_id="compliance-1"
            )

    async with db_services.AsyncSessionLocal() as db:
        flagged, _others = await GstRegistrationService(db).flag(
            registration_id, reason="GST returns unfiled for six months", actor_id="compliance-1"
        )
    assert flagged.flag_status is GstRegistrationFlag.FLAGGED
    assert flagged.flag_reason == "GST returns unfiled for six months"

    async with db_services.AsyncSessionLocal() as db:
        rows, _t = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_GST, limit=10
        )
    [row] = [r for r in rows if r.event_type == "gst_registration_flagged"]
    assert row.reason == "GST returns unfiled for six months"


async def test_the_database_refuses_a_flag_with_no_reason_in_raw_sql():
    """``ck_exporter_gstin_flag_reason``. The reason is the whole value of the flag to
    whoever reads the handover it blocks, so the rule is in the database too."""
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE onboarding.exporter_gstin SET flag_status = 'FLAGGED' WHERE id = %s",
                    (str(registration_id),),
                )
    finally:
        connection.close()


async def test_flagging_one_branch_leaves_the_companys_others_alone():
    """Decision BQ-6: a company trading through five states may have a problem in
    one. Flagging the company would stop the other four."""
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        maharashtra, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan, "27"), actor_id="rm-1"
        )
        karnataka, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan, "29"), actor_id="rm-1"
        )
        maharashtra_id, karnataka_id = maharashtra.id, karnataka.id

    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            maharashtra_id, reason="Returns unfiled", actor_id="compliance-1"
        )

    async with db_services.AsyncSessionLocal() as db:
        reader = BranchFlagService(db)
        assert await reader.is_flagged(maharashtra_id) == (True, "Maharashtra")
        assert await reader.is_flagged(karnataka_id) == (False, "Karnataka")


async def test_the_reader_names_the_state_so_the_guard_can_quote_it():
    """The guard's message is "the invoicing branch Maharashtra is flagged", and a
    deal's invoicing branch is a row id — only this lane knows a GSTIN's state."""
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan, "33"), actor_id="rm-1"
        )
        registration_id = registration.id
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            registration_id, reason="Address unverified", actor_id="compliance-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        assert await BranchFlagService(db).is_flagged(registration_id) == (
            True,
            "Tamil Nadu",
        )


async def test_an_unknown_registration_is_not_flagged():
    """"There is no such branch" is a data error, not a compliance problem. Reporting
    it as flagged would block a handover for the wrong reason."""
    async with db_services.AsyncSessionLocal() as db:
        assert await BranchFlagService(db).is_flagged(uuid.uuid4()) == (False, None)


async def test_unflagging_needs_a_reason_and_clears_the_flag():
    customer_id, pan = await _company_with_pan()
    async with db_services.AsyncSessionLocal() as db:
        registration, _o = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan), actor_id="rm-1"
        )
        registration_id = registration.id
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            registration_id, reason="Returns unfiled", actor_id="compliance-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="reason"):
            await GstRegistrationService(db).unflag(
                registration_id, reason="", actor_id="compliance-1"
            )
    async with db_services.AsyncSessionLocal() as db:
        lifted = await GstRegistrationService(db).unflag(
            registration_id, reason="Returns now filed and verified", actor_id="compliance-1"
        )
    assert lifted.flag_status is GstRegistrationFlag.NONE
    assert lifted.flag_reason is None

    # Both reasons survive in the history, which is the point of requiring the second.
    async with db_services.AsyncSessionLocal() as db:
        rows, _t = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_GST, limit=10
        )
    reasons = {r.event_type: r.reason for r in rows}
    assert reasons["gst_registration_flagged"] == "Returns unfiled"
    assert reasons["gst_registration_unflagged"] == "Returns now filed and verified"


# ── A shared GSTIN: warn, never refuse (task 3.15, decision IQ-9) ─────────────


async def test_a_gstin_on_two_companies_is_allowed_and_reported():
    first, pan = await _company_with_pan()
    gstin = _gstin(pan)
    # The second company holds the same PAN's GSTIN. Allowed: duplicates stay
    # warn-only (IQ-9), and the PAN check is against the GSTIN, not across companies.
    second = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            second,
            source=ExporterSource.SALES,
            name=f"Shared GSTIN Co {uuid.uuid4().hex[:8]}",
            country="IN",
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).add(first, gstin=gstin, actor_id="rm-1")
    async with db_services.AsyncSessionLocal() as db:
        registration, others = await GstRegistrationService(db).add(
            second, gstin=gstin, actor_id="rm-1"
        )
    assert registration.active is True
    assert others == [first]


async def test_flagging_one_holder_warns_about_the_other_and_does_not_flag_it():
    """Plan P6-3's consequence, stated as a test: the flag belongs to one company's
    row. Whoever flags it must be told the other copy exists, or they will believe
    they have stopped trade that is still running."""
    first, pan = await _company_with_pan()
    gstin = _gstin(pan)
    second = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            second,
            source=ExporterSource.SALES,
            name=f"Other Holder {uuid.uuid4().hex[:8]}",
            country="IN",
        )
    async with db_services.AsyncSessionLocal() as db:
        mine, _o = await GstRegistrationService(db).add(first, gstin=gstin, actor_id="rm-1")
        theirs, _o = await GstRegistrationService(db).add(second, gstin=gstin, actor_id="rm-1")
        mine_id, theirs_id = mine.id, theirs.id

    async with db_services.AsyncSessionLocal() as db:
        flagged, others = await GstRegistrationService(db).flag(
            mine_id, reason="Returns unfiled", actor_id="compliance-1"
        )
    assert flagged.flag_status is GstRegistrationFlag.FLAGGED
    assert others == [second]

    # The other company's copy is untouched.
    async with db_services.AsyncSessionLocal() as db:
        assert await BranchFlagService(db).is_flagged(theirs_id) == (False, "Maharashtra")


async def test_a_deactivated_copy_is_not_reported_as_another_holder():
    """A company that deactivated its copy is no longer claiming the GSTIN, so
    warning about it would be noise."""
    first, pan = await _company_with_pan()
    gstin = _gstin(pan)
    second = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            second,
            source=ExporterSource.SALES,
            name=f"Gone Holder {uuid.uuid4().hex[:8]}",
            country="IN",
        )
    async with db_services.AsyncSessionLocal() as db:
        theirs, _o = await GstRegistrationService(db).add(second, gstin=gstin, actor_id="rm-1")
        theirs_id = theirs.id
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).deactivate(theirs_id, actor_id="rm-1")
    async with db_services.AsyncSessionLocal() as db:
        _registration, others = await GstRegistrationService(db).add(
            first, gstin=gstin, actor_id="rm-1"
        )
    assert others == []


# ── The routes, masking and the portal link (tasks 3.13, 3.14, 3.17) ──────────


async def test_the_routes_add_list_and_flag(client: AsyncClient):
    _admin, admin_token = await user_with_role(client, UserRole.ADMIN)
    customer_id, pan = await _company_with_pan()

    added = await client.post(
        f"{BASE}/exporters/{customer_id}/gst-registrations",
        json={"gstin": _gstin(pan), "address": "5 Dockyard Road, Mumbai"},
        headers=auth_header(admin_token),
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["state_name"] == "Maharashtra"
    assert body["active"] is True
    assert body["flag_status"] == "NONE"
    registration_id = body["id"]

    flagged = await client.post(
        f"{BASE}/gst-registrations/{registration_id}/flag",
        json={"reason": "Returns unfiled"},
        headers=auth_header(admin_token),
    )
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["flag_status"] == "FLAGGED"

    listed = await client.get(
        f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(admin_token)
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["flagged_count"] == 1


async def test_a_flag_without_a_reason_is_refused_by_the_route(client: AsyncClient):
    _admin, token = await user_with_role(client, UserRole.ADMIN)
    customer_id, pan = await _company_with_pan()
    added = await client.post(
        f"{BASE}/exporters/{customer_id}/gst-registrations",
        json={"gstin": _gstin(pan)},
        headers=auth_header(token),
    )
    registration_id = added.json()["id"]
    resp = await client.post(
        f"{BASE}/gst-registrations/{registration_id}/flag",
        json={"reason": ""},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_only_compliance_and_admin_may_flag(client: AsyncClient):
    """A flag stops trade through a branch, so it is a compliance decision. This is
    the one place in these routes where OPERATIONS is refused."""
    _admin, admin_token = await user_with_role(client, UserRole.ADMIN)
    customer_id, pan = await _company_with_pan()
    added = await client.post(
        f"{BASE}/exporters/{customer_id}/gst-registrations",
        json={"gstin": _gstin(pan)},
        headers=auth_header(admin_token),
    )
    registration_id = added.json()["id"]

    _ops, ops_token = await user_with_role(client, UserRole.OPERATIONS)
    refused = await client.post(
        f"{BASE}/gst-registrations/{registration_id}/flag",
        json={"reason": "Returns unfiled"},
        headers=auth_header(ops_token),
    )
    assert refused.status_code == 403, refused.text

    # But OPERATIONS may still record and deactivate a branch: which branches a
    # company trades through is a record a relationship manager keeps.
    deactivated = await client.post(
        f"{BASE}/gst-registrations/{registration_id}/deactivate",
        headers=auth_header(ops_token),
    )
    assert deactivated.status_code == 200, deactivated.text


async def test_the_portal_link_is_served_only_to_a_role_that_sees_the_gstin(
    client: AsyncClient,
):
    """Task 3.17. The URL contains the GSTIN, so serving it to a masked role would
    hand over exactly the value the masking withholds."""
    _admin, admin_token = await user_with_role(client, UserRole.ADMIN)
    customer_id, pan = await _company_with_pan()
    gstin = _gstin(pan)
    await client.post(
        f"{BASE}/exporters/{customer_id}/gst-registrations",
        json={"gstin": gstin},
        headers=auth_header(admin_token),
    )

    for role in (UserRole.ADMIN, UserRole.COMPLIANCE):
        _user, token = await user_with_role(client, role)
        resp = await client.get(
            f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(token)
        )
        [row] = resp.json()["registrations"]
        assert row["gstin"] == gstin, role
        assert row["verify_url"].endswith(gstin), role
        assert row["verify_url"].startswith("https://services.gst.gov.in/"), role

    for role in (UserRole.OPERATIONS, UserRole.DEVELOPER):
        _user, token = await user_with_role(client, role)
        resp = await client.get(
            f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(token)
        )
        [row] = resp.json()["registrations"]
        assert row["gstin"] != gstin, role
        assert "•" in row["gstin"], role
        assert row["verify_url"] is None, role
        # And the full value appears nowhere else in the body.
        assert gstin not in resp.text, role


async def test_every_path_that_creates_a_registration_derives_its_state():
    """There are two: `create_or_get_profile` (a company created with GSTINs, which is
    how CSV import, RXIL intake and the buyer-company path all arrive) and
    `GstRegistrationService.add`. A row from either must be the same kind of row.

    Worth pinning, because the consequence of a missing state is quiet and remote: the
    branch flag reader has nothing to name, so a blocked handover reads "the invoicing
    branch registration is flagged" instead of naming Maharashtra, and the company page
    shows "Unknown state" for a GSTIN that plainly carries one.
    """
    pan = _pan()

    # Path 1: created with the company.
    with_company = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            with_company,
            source=ExporterSource.SALES,
            name=f"Created With GSTIN {uuid.uuid4().hex[:8]}",
            country="IN",
            pan=pan,
            gstins=[_gstin(pan, "29")],
        )
    async with db_services.AsyncSessionLocal() as db:
        [row] = await GstRegistrationService(db).list_for_company(with_company)
    assert (row.state_code, row.state_name) == ("29", "Karnataka")

    # Path 2: added afterwards.
    async with db_services.AsyncSessionLocal() as db:
        added, _others = await GstRegistrationService(db).add(
            with_company, gstin=_gstin(pan, "33"), actor_id="rm-1"
        )
    assert (added.state_code, added.state_name) == ("33", "Tamil Nadu")

    # And the flag reader can name either of them.
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(
            row.id, reason="Returns unfiled", actor_id="compliance-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        assert await BranchFlagService(db).is_flagged(row.id) == (True, "Karnataka")


# ── R-47 (decision D-05, 4 October 2026): DEVELOPER is not served branch flags ──


async def _flagged_and_deactivated_branches() -> tuple[uuid.UUID, str]:
    """A company with a flagged branch and a deactivated one. Returns the company
    and the flag's reason, which is the text DEVELOPER must never receive."""
    customer_id, pan = await _company_with_pan()
    reason = f"Returns unfiled {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        flagged, _ = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan, "27"), actor_id="rm-1"
        )
        closed, _ = await GstRegistrationService(db).add(
            customer_id, gstin=_gstin(pan, "29"), actor_id="rm-1"
        )
        flagged_id, closed_id = flagged.id, closed.id
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).flag(flagged_id, reason=reason, actor_id="compliance-1")
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).deactivate(
            closed_id, reason="Branch closed", actor_id="rm-1"
        )
    return customer_id, reason


async def test_developer_gets_no_flag_status_reason_or_count(client: AsyncClient):
    customer_id, reason = await _flagged_and_deactivated_branches()
    _dev, dev_token = await user_with_role(client, UserRole.DEVELOPER)

    response = await client.get(
        f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(dev_token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flagged_count"] is None
    assert len(body["registrations"]) == 2
    for registration in body["registrations"]:
        assert registration["flag_status"] is None
        assert registration["flag_reason"] is None
    # The branches themselves stay readable, deactivation included.
    assert {r["active"] for r in body["registrations"]} == {True, False}
    assert reason not in response.text
    assert "FLAGGED" not in response.text


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.COMPLIANCE])
async def test_staff_still_get_the_flag(client: AsyncClient, role: UserRole):
    """OPERATIONS keeps the flag: it blocks the deals it is working on."""
    customer_id, reason = await _flagged_and_deactivated_branches()
    _user, token = await user_with_role(client, role)

    response = await client.get(
        f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flagged_count"] == 1
    flagged = [r for r in body["registrations"] if r["flag_status"] == "FLAGGED"]
    assert len(flagged) == 1 and flagged[0]["flag_reason"] == reason


async def test_developer_history_has_no_flag_rows_or_flag_details(client: AsyncClient):
    customer_id, reason = await _flagged_and_deactivated_branches()
    _dev, dev_token = await user_with_role(client, UserRole.DEVELOPER)
    _ops, ops_token = await user_with_role(client, UserRole.OPERATIONS)
    url = f"{BASE}/exporters/{customer_id}/history?dimension={HISTORY_DIMENSION_GST}"

    dev = await client.get(url, headers=auth_header(dev_token))
    ops = await client.get(url, headers=auth_header(ops_token))
    assert dev.status_code == ops.status_code == 200

    dev_events = [e["event_type"] for e in dev.json()["entries"]]
    ops_events = [e["event_type"] for e in ops.json()["entries"]]
    assert "gst_registration_flagged" in ops_events
    assert "gst_registration_flagged" not in dev_events
    # Adding and deactivating a branch stay readable, without the flag status.
    assert sorted(dev_events) == [
        "gst_registration_added",
        "gst_registration_added",
        "gst_registration_deactivated",
    ]
    assert all("flag_status" not in (e["details"] or {}) for e in dev.json()["entries"])
    # The total agrees with the page, so paging does not promise rows it withholds.
    assert dev.json()["total"] == len(dev_events)
    assert reason not in dev.text

    # The unfiltered timeline withholds them the same way.
    timeline = await client.get(
        f"{BASE}/exporters/{customer_id}/history", headers=auth_header(dev_token)
    )
    assert "gst_registration_flagged" not in timeline.text
    assert reason not in timeline.text
