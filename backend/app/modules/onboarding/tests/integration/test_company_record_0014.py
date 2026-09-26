"""Migration 0014 — real links, PAN and GSTIN rules, the marker, sample data
(L2-05, L2-06, L2-08).

The database-level cases go straight through ``psycopg2`` so they prove the
*database* refuses the bad row, not just the service (migration register §2:
every new constraint gets a direct-SQL violation test). The rest go through
the API as a person would.

Real Postgres, each test minting its own ids and identifiers, like the rest of
this package.
"""

from __future__ import annotations

import pathlib
import uuid

import psycopg2
import psycopg2.errors
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.onboarding.application.exporter_profile_service import (
    HISTORY_DIMENSION_MARKER,
    ExporterProfileService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.exceptions import DuplicatePanError, InvalidMarkerTransitionError
from app.modules.onboarding.sample_data import COMPANIES, SAMPLE_NAMESPACE, load_sample_data
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
BACKEND = pathlib.Path(__file__).resolve().parents[5]
REVISION = "onboarding_0014_company_record"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _new_pan() -> str:
    """A well-formed PAN no other company holds."""
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str, state: str = "27") -> str:
    return f"{state}{pan}1Z5"


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {
        role: await token_with_role(client, role)
        for role in (UserRole.OPERATIONS, UserRole.COMPLIANCE)
    }


async def _create(client: AsyncClient, token: str, **fields):
    return await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Co {uuid.uuid4().hex[:8]}", "country": "IN", **fields},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )


# ── The migration ─────────────────────────────────────────────────────────────


async def test_0014_follows_0013_and_the_chain_has_one_head():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == "onboarding_0013_shared_history"
    assert len(REVISION) <= 32


async def test_the_database_is_at_0014():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            assert REVISION in {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


# ── Real links ────────────────────────────────────────────────────────────────

_CHILD_INSERTS = {
    "exporter_contact": (
        "INSERT INTO onboarding.exporter_contact (id, customer_id, name, is_primary_contact) "
        "VALUES (%s, %s, 'Ghost', false)"
    ),
    "exporter_activity": (
        "INSERT INTO onboarding.exporter_activity "
        "(id, customer_id, activity_type, subject, actor_id, occurred_at) "
        "VALUES (%s, %s, 'CALL', 'ghost', 'tester', now())"
    ),
    "screening_review_item": (
        "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
        "VALUES (%s, %s, 'website_reviewed', 'NEEDS_REVIEW')"
    ),
    "exporter_lifecycle_history": (
        "INSERT INTO onboarding.exporter_lifecycle_history "
        "(id, customer_id, dimension, event_type, to_status) "
        "VALUES (%s, %s, 'journey', 'test', 'LEAD')"
    ),
    "exporter_gstin": (
        "INSERT INTO onboarding.exporter_gstin (id, customer_id, gstin) "
        "VALUES (%s, %s, '27AAAPL1234C1Z5')"
    ),
}


@pytest.mark.parametrize("table", sorted(_CHILD_INSERTS))
async def test_a_child_row_for_a_company_that_does_not_exist_is_refused(table: str):
    conn = _connect()
    try:
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(_CHILD_INSERTS[table], (str(uuid.uuid4()), str(uuid.uuid4())))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("table", sorted(_CHILD_INSERTS))
async def test_a_child_row_for_a_real_company_is_accepted(table: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(_CHILD_INSERTS[table], (str(uuid.uuid4()), str(company_id)))
    finally:
        conn.rollback()
        conn.close()


async def test_a_company_with_children_cannot_be_deleted():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(
                _CHILD_INSERTS["exporter_contact"], (str(uuid.uuid4()), str(company_id))
            )
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute(
                    "DELETE FROM onboarding.exporter_profile WHERE customer_id = %s",
                    (str(company_id),),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_verification_results_deliberately_have_no_company_link():
    """`entity_reference` names several kinds of subject (company, person,
    buyer), so it cannot point at one table."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = 'onboarding.verification_result'::regclass AND contype = 'f'"
            )
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()


async def test_history_is_still_append_only_after_0014():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            row_id = str(uuid.uuid4())
            cur.execute(_CHILD_INSERTS["exporter_lifecycle_history"], (row_id, str(company_id)))
            conn.commit()
            for statement in (
                "UPDATE onboarding.exporter_lifecycle_history SET to_status = 'X' WHERE id = %s",
                "DELETE FROM onboarding.exporter_lifecycle_history WHERE id = %s",
            ):
                with pytest.raises(psycopg2.errors.RaiseException):
                    cur.execute(statement, (row_id,))
                conn.rollback()
    finally:
        conn.close()


# ── PAN ───────────────────────────────────────────────────────────────────────


async def test_the_database_refuses_a_second_company_with_the_same_pan():
    pan = _new_pan()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            first = insert_company(cur)
            cur.execute(
                "UPDATE onboarding.exporter_profile SET pan = %s WHERE customer_id = %s",
                (pan, str(first)),
            )
            second = insert_company(cur)
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "UPDATE onboarding.exporter_profile SET pan = %s WHERE customer_id = %s",
                    (pan, str(second)),
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize(
    "column, value",
    [
        ("pan", "abcde1234f"),  # not normalised
        ("pan", "ABCDE12345"),
        ("cin", "X12345MH2001PLC123456"),
        ("country", "India"[:2].lower()),
        ("name", "   "),
    ],
)
async def test_the_database_refuses_a_malformed_identity_value(column: str, value: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    f"UPDATE onboarding.exporter_profile SET {column} = %s WHERE customer_id = %s",
                    (value, str(company_id)),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_a_duplicate_pan_is_refused_by_the_api_and_names_the_holder(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.OPERATIONS]
    pan = _new_pan()
    first = await _create(client, token, pan=pan)
    assert first.status_code == 201, first.text

    second = await _create(client, token, pan=pan.lower())  # normalised before the check
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["error_code"] == "DUPLICATE_PAN"
    assert body["error_context"]["existing_customer_id"] == first.json()["customer_id"]
    assert pan not in second.text  # the refusal never repeats the PAN


async def test_a_pan_is_normalised_before_it_is_stored(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    pan = _new_pan()
    resp = await _create(client, tokens[UserRole.COMPLIANCE], pan=f"  {pan.lower()} ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["pan"] == pan


@pytest.mark.parametrize("pan", ["ABCDE12345", "ABC1234567", "ABCDE1234"])
async def test_a_malformed_pan_is_refused(
    client: AsyncClient, tokens: dict[UserRole, str], pan: str
):
    resp = await _create(client, tokens[UserRole.OPERATIONS], pan=pan)
    assert resp.status_code == 422, resp.text


async def test_changing_to_a_pan_another_company_holds_is_refused():
    taken = _new_pan()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, pan=taken
        )
    other = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(other, source=ExporterSource.SALES)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(DuplicatePanError):
            await ExporterProfileService(db).update_profile(
                other, {"pan": taken}, actor_id="rm-1"
            )


# ── GSTIN ─────────────────────────────────────────────────────────────────────


async def test_a_company_holds_several_gstins(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    pan = _new_pan()
    gstins = [_gstin(pan, "27"), _gstin(pan, "29")]
    resp = await _create(client, tokens[UserRole.COMPLIANCE], pan=pan, gstins=gstins)
    assert resp.status_code == 201, resp.text
    assert resp.json()["gstins"] == gstins

    found = await client.get(
        f"{BASE}/exporters",
        params={"gstin": gstins[1]},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert [p["customer_id"] for p in found.json()["profiles"]] == [resp.json()["customer_id"]]


async def test_a_gstin_held_by_another_company_is_a_warning_not_a_refusal(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.COMPLIANCE]
    pan = _new_pan()
    gstin = _gstin(pan)
    first = await _create(client, token, pan=pan, gstins=[gstin])
    assert first.json()["gstin_warnings"] == []

    # A second record with no PAN of its own may hold the same GSTIN.
    second = await _create(client, token, gstins=[gstin])
    assert second.status_code == 201, second.text
    [warning] = second.json()["gstin_warnings"]
    assert warning["gstin"] == gstin
    assert warning["other_customer_ids"] == [first.json()["customer_id"]]

    detail = await client.get(
        f"{BASE}/exporters/{first.json()['customer_id']}", headers=auth_header(token)
    )
    assert detail.json()["gstin_warnings"][0]["other_customer_ids"] == [
        second.json()["customer_id"]
    ]


async def test_a_gstin_warning_is_masked_for_a_role_that_sees_identifiers_masked(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    pan = _new_pan()
    gstin = _gstin(pan)
    await _create(client, tokens[UserRole.COMPLIANCE], pan=pan, gstins=[gstin])
    resp = await _create(client, tokens[UserRole.OPERATIONS], gstins=[gstin])
    [warning] = resp.json()["gstin_warnings"]
    assert warning["gstin"] == "•" * 11 + gstin[-4:]


async def test_a_gstin_must_carry_the_companys_pan(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    resp = await _create(
        client, tokens[UserRole.OPERATIONS], pan=_new_pan(), gstins=[_gstin(_new_pan())]
    )
    assert resp.status_code == 422, resp.text
    assert "does not contain this company's PAN" in resp.text


async def test_the_same_gstin_twice_on_one_company_is_refused(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    pan = _new_pan()
    resp = await _create(
        client, tokens[UserRole.OPERATIONS], pan=pan, gstins=[_gstin(pan), _gstin(pan).lower()]
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("gstin", ["27ABCDE1234F1Z", "2XABCDE1234F1Z5", "27ABCDE1234F1Y5"])
async def test_a_malformed_gstin_is_refused(
    client: AsyncClient, tokens: dict[UserRole, str], gstin: str
):
    resp = await _create(client, tokens[UserRole.OPERATIONS], gstins=[gstin])
    assert resp.status_code == 422, resp.text


async def test_a_new_pan_must_fit_the_gstins_being_kept():
    pan = _new_pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, pan=pan, gstins=[_gstin(pan)]
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ExporterProfileService(db).update_profile(
                customer_id, {"pan": _new_pan()}, actor_id="rm-1"
            )


async def test_replacing_the_gstin_list_keeps_the_ones_that_stay():
    pan = _new_pan()
    kept, dropped, added = _gstin(pan, "27"), _gstin(pan, "29"), _gstin(pan, "33")
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, pan=pan, gstins=[kept, dropped]
        )
    async with db_services.AsyncSessionLocal() as db:
        profile = await ExporterProfileService(db).update_profile(
            customer_id, {"gstins": [kept, added]}, actor_id="rm-1"
        )
    assert sorted(profile.gstins) == sorted([kept, added])

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(customer_id, dimension="profile")
    [row] = rows
    assert row.event_metadata["field"] == "gstins"  # masked values, as for every identifier
    assert all(value.startswith("•") for value in row.event_metadata["to"])


# ── The marker ────────────────────────────────────────────────────────────────


async def _company_at(status: ExporterLifecycleStatus = ExporterLifecycleStatus.LEAD) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            lifecycle_status=status,
            compliance_authorized=True,
        )
    return customer_id


@pytest.mark.parametrize("marker", ["PAUSED", "ENDED"])
@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_pausing_or_ending_needs_a_reason(
    client: AsyncClient, tokens: dict[UserRole, str], marker: str, reason
):
    customer_id = await _company_at()
    body = {"marker": marker} if reason is None else {"marker": marker, "reason": reason}
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/marker",
        json=body,
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 422, resp.text


async def test_the_database_refuses_a_marker_without_a_reason():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE onboarding.exporter_profile SET marker = 'PAUSED' "
                    "WHERE customer_id = %s",
                    (str(company_id),),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_a_marker_change_is_recorded_and_leaves_the_journey_alone(
    client: AsyncClient,
):
    from app.modules.onboarding.tests.fixtures.auth import user_with_role

    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _company_at(ExporterLifecycleStatus.CONTACTED)

    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/marker",
        json={"marker": "PAUSED", "reason": "  Seasonal shutdown  "},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["marker"], body["marker_reason"]) == ("PAUSED", "Seasonal shutdown")
    assert body["lifecycle_status"] == "CONTACTED"  # the journey did not move

    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_MARKER
        )
        journey, _ = await HistoryService(db).list_for_company(customer_id, dimension="journey")
    [row] = rows
    assert (row.from_status, row.to_status) == ("NONE", "PAUSED")
    assert row.reason == "Seasonal shutdown"
    assert row.actor_id == str(user_id)
    assert row.event_type == "marker_transition"
    assert len(journey) == 1  # only the creation row


async def test_a_journey_move_leaves_the_marker_alone():
    customer_id = await _company_at()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).set_marker(
            customer_id, ExporterMarker.PAUSED, reason="On hold", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        profile = await ExporterProfileService(db).transition_lifecycle_status(
            customer_id, ExporterLifecycleStatus.CONTACTED, actor_id="rm-1"
        )
    assert profile.marker is ExporterMarker.PAUSED
    assert profile.marker_reason == "On hold"


async def test_the_marker_is_not_a_journey_stage():
    assert not {m.value for m in ExporterMarker} & {s.value for s in ExporterLifecycleStatus}


@pytest.mark.parametrize(
    "path, refused",
    [
        ([(ExporterMarker.ENDED, "Closed")], (ExporterMarker.PAUSED, "Reopen")),  # clear first
        ([(ExporterMarker.PAUSED, "Hold")], (ExporterMarker.PAUSED, "Hold again")),  # no-op
        ([], (ExporterMarker.NONE, None)),  # already NONE
    ],
)
async def test_marker_moves_the_contract_does_not_allow_are_refused(path, refused):
    customer_id = await _company_at()
    for marker, reason in path:
        async with db_services.AsyncSessionLocal() as db:
            await ExporterProfileService(db).set_marker(
                customer_id, marker, reason=reason, actor_id="rm-1"
            )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(InvalidMarkerTransitionError):
            await ExporterProfileService(db).set_marker(
                customer_id, refused[0], reason=refused[1], actor_id="rm-1"
            )


async def test_a_paused_company_can_end_and_an_ended_one_can_be_cleared():
    customer_id = await _company_at()
    for marker, reason in (
        (ExporterMarker.PAUSED, "Seasonal"),
        (ExporterMarker.ENDED, "Closed down"),
        (ExporterMarker.NONE, None),
    ):
        async with db_services.AsyncSessionLocal() as db:
            profile = await ExporterProfileService(db).set_marker(
                customer_id, marker, reason=reason, actor_id="rm-1"
            )
    assert profile.marker is ExporterMarker.NONE
    assert profile.marker_reason is None


async def test_the_marker_cannot_be_set_through_the_edit_route(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _company_at()
    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"marker": "ENDED"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 422


# ── ENDED companies and the working list ──────────────────────────────────────


async def test_ended_companies_leave_the_default_list_but_stay_searchable(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.COMPLIANCE]
    name = f"Ended Co {uuid.uuid4().hex[:8]}"
    pan = _new_pan()
    created = await _create(client, token, name=name, pan=pan)
    company_id = created.json()["customer_id"]
    await client.post(
        f"{BASE}/exporters/{company_id}/marker",
        json={"marker": "ENDED", "reason": "Closed down"},
        headers=auth_header(token),
    )

    async def ids(**params) -> set[str]:
        resp = await client.get(
            f"{BASE}/exporters", params={"limit": 200, **params}, headers=auth_header(token)
        )
        assert resp.status_code == 200, resp.text
        return {p["customer_id"] for p in resp.json()["profiles"]}

    assert company_id not in await ids()  # default working list
    assert company_id not in await ids(source="SALES")  # a list filter is not a search
    assert company_id in await ids(name=name)  # a search finds it
    assert company_id in await ids(pan=pan)
    assert company_id in await ids(marker="ENDED")  # so does asking for ENDED
    assert company_id not in await ids(marker="NONE")


async def test_paused_companies_stay_in_the_default_list(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.OPERATIONS]
    created = await _create(client, token)
    company_id = created.json()["customer_id"]
    await client.post(
        f"{BASE}/exporters/{company_id}/marker",
        json={"marker": "PAUSED", "reason": "Seasonal"},
        headers=auth_header(token),
    )
    resp = await client.get(f"{BASE}/exporters", params={"limit": 50}, headers=auth_header(token))
    assert company_id in {p["customer_id"] for p in resp.json()["profiles"]}


# ── Sample data ───────────────────────────────────────────────────────────────


async def test_sample_data_is_deterministic_and_safe_to_run_again():
    await load_sample_data()
    second = await load_sample_data()

    assert all(
        changes == {
            "created": False,
            "moves": 0,
            "marker_set": False,
            "contacts_added": 0,
            "activities_added": 0,
        }
        for changes in second.values()
    ), second
    assert all(c.customer_id == uuid.uuid5(SAMPLE_NAMESPACE, c.slug) for c in COMPANIES)


async def test_sample_data_covers_the_states_this_phase_introduces():
    await load_sample_data()
    by_slug = {}
    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        for company in COMPANIES:
            by_slug[company.slug] = await service.get_profile_detail(company.customer_id)
        legacy_rows = await db.scalar(
            select(func.count())
            .select_from(OnboardingRequest)
            .where(OnboardingRequest.customer_id.in_([c.customer_id for c in COMPANIES]))
        )

    assert {d.marker for d in by_slug.values()} == set(ExporterMarker)
    assert len(by_slug["company-b"].gstins) == 2
    assert by_slug["company-f-new-lead"].pan is None
    assert by_slug["company-g-possible-duplicate"].gstin_warnings  # shares B's GSTIN
    assert by_slug["company-b"].lifecycle_status is ExporterLifecycleStatus.ACTIVE
    assert all(d.name for d in by_slug.values())
    assert legacy_rows == 0  # nothing fake written to the legacy onboarding tables
