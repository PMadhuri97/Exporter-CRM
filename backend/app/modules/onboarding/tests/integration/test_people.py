"""A company's directors and beneficial owners, recorded as people, over HTTP and in SQL.

Migration ``onboarding_0057_people``: a person is one ``exporter_contact`` row with roles
(contact, director, beneficial owner). Only the name and a role are required; the
director-only and owner-only fields need that role; date of birth, DIN and the
identification number are masked unless the viewer holds
``exporters:view_full_tax_id``; the identification number is stored encrypted; and a
person is never deleted. Adding a director or owner, or changing those roles, writes a
``contact`` history row.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.modules.onboarding.tests.integration._verification_support import pg
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"
MASKED_DATE = "••••-••-••"
DIRECTOR = {
    "name": "Ravi Kumar",
    "is_contact": False,
    "is_director": True,
    "din": "01234567",
    "date_of_birth": "1970-04-12",
    "nationality": "IN",
    "identification_type": "PASSPORT",
    "identification_number": "Z1234321",
}


async def _add(client: AsyncClient, token: str, customer_id, **body):
    return await client.post(f"{BASE}/{customer_id}/contacts", headers=auth_header(token), json=body)


async def _list(client: AsyncClient, token: str, customer_id, role: str | None = None) -> list[dict]:
    params = {"role": role} if role else {}
    resp = await client.get(
        f"{BASE}/{customer_id}/contacts", headers=auth_header(token), params=params
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["contacts"]


async def _contact_history(client: AsyncClient, token: str, customer_id) -> list[dict]:
    resp = await client.get(
        f"{BASE}/{customer_id}/history", headers=auth_header(token), params={"dimension": "contact"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["entries"]


# ── Over HTTP ────────────────────────────────────────────────────────────────


async def test_a_director_is_recorded_with_only_a_name_and_a_role(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    resp = await _add(client, token, customer_id, name="Meera Shah", is_contact=False, is_director=True)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["is_contact"], body["is_director"], body["is_ubo"]) == (False, True, False)
    assert body["din"] is None and body["identification_number"] is None


async def test_directors_are_listed_apart_from_contacts(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    await _add(client, token, customer_id, name="Front Desk")
    await _add(client, token, customer_id, name="Board Only", is_contact=False, is_director=True)
    await _add(client, token, customer_id, name="Both", is_director=True)

    assert {c["name"] for c in await _list(client, token, customer_id)} == {"Front Desk", "Both"}
    assert {c["name"] for c in await _list(client, token, customer_id, "DIRECTOR")} == {
        "Board Only",
        "Both",
    }
    assert len(await _list(client, token, customer_id, "ALL")) == 3

    detail = await client.get(f"{BASE}/{customer_id}", headers=auth_header(token))
    assert {c["name"] for c in detail.json()["contacts"]} == {"Front Desk", "Both"}


async def test_a_compliance_officer_sees_a_directors_details_in_full(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()

    resp = await _add(client, token, customer_id, **DIRECTOR)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["din"] == "01234567"
    assert body["date_of_birth"] == "1970-04-12"
    assert body["identification_number"] == "Z1234321"
    assert body["identification_type"] == "PASSPORT"
    assert "identification_encrypted" not in body and "identification_last4" not in body


async def test_sales_sees_a_directors_details_masked(client: AsyncClient):
    officer = await token_with_role(client, UserRole.COMPLIANCE)
    sales = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    assert (await _add(client, officer, customer_id, **DIRECTOR)).status_code == 201

    [person] = await _list(client, sales, customer_id, "DIRECTOR")

    assert person["din"] == "••••4567"
    assert person["date_of_birth"] == MASKED_DATE
    assert person["identification_number"] == "••••4321"
    assert person["nationality"] == "IN"


async def test_the_identification_number_is_stored_encrypted(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    person_id = (await _add(client, token, customer_id, **DIRECTOR)).json()["id"]

    with pg() as cur:
        cur.execute(
            "SELECT identification_encrypted, identification_last4 "
            "FROM onboarding.exporter_contact WHERE id = %s",
            (person_id,),
        )
        sealed, last4 = cur.fetchone()

    assert "Z1234321" not in sealed
    assert last4 == "4321"


async def test_a_masked_value_sent_back_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    resp = await _add(
        client, token, customer_id, name="Echo", is_ubo=True,
        identification_type="PASSPORT", identification_number="••••4321",
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "body",
    [
        {"is_contact": False},
        {"is_contact": False, "is_director": True, "is_primary": True},
        {"din": "01234567"},
        {"ownership_pct": 25},
        {"control_type": "VOTING_RIGHTS"},
        {"is_ubo": True, "identification_number": "Z1234321"},
        {"is_ubo": True, "identification_type": "PASSPORT"},
    ],
    ids=[
        "no-role",
        "primary-not-a-contact",
        "din-without-director",
        "share-without-owner",
        "control-without-owner",
        "number-without-type",
        "type-without-number",
    ],
)
async def test_a_person_breaking_a_role_rule_is_refused(client: AsyncClient, body):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    resp = await _add(client, token, customer_id, name="Rule Breaker", **body)

    assert resp.status_code == 422, resp.text
    assert await _list(client, token, customer_id, "ALL") == []


@pytest.mark.parametrize(
    "body",
    [
        {"din": "01234567"},
        {"ownership_pct": 25},
        {"control_type": "VOTING_RIGHTS"},
        {"din": "01234567", "is_primary": True},
        {"is_contact": False, "is_director": True, "is_primary": True},
    ],
    ids=[
        "din-without-director",
        "share-without-owner",
        "control-without-owner",
        "din-while-promoting",
        "primary-not-a-contact",
    ],
)
async def test_an_edit_breaking_a_role_rule_is_refused_and_changes_nothing(
    client: AsyncClient, body
):
    # Refused as the same person is when added, never silently dropped (200 with the
    # field empty) and never reaching the database's CHECK as a 500.
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    first_id = (await _add(client, token, customer_id, name="First Primary", is_primary=True)).json()["id"]
    person_id = (await _add(client, token, customer_id, name="Plain Contact")).json()["id"]
    target = first_id if body.get("is_contact") is False else person_id

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{target}", headers=auth_header(token), json=body
    )

    assert resp.status_code == 422, resp.text
    people = {p["id"]: p for p in await _list(client, token, customer_id, "ALL")}
    assert people[first_id]["is_primary_contact"] is True
    assert people[first_id]["is_contact"] is True
    assert people[person_id]["is_primary_contact"] is False
    assert people[person_id]["din"] is None and people[person_id]["ownership_pct"] is None


async def test_promoting_a_person_demotes_the_previous_primary(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    first_id = (await _add(client, token, customer_id, name="First Primary", is_primary=True)).json()["id"]
    person_id = (await _add(client, token, customer_id, name="Director And Contact", is_director=True)).json()["id"]

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{person_id}",
        headers=auth_header(token),
        json={"is_primary": True, "din": "01234567"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_primary_contact"] is True
    people = {p["id"]: p for p in await _list(client, token, customer_id, "ALL")}
    assert people[first_id]["is_primary_contact"] is False


async def test_adding_an_owner_writes_a_history_row(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    resp = await _add(
        client, token, customer_id, name="Anita Rao", is_contact=False, is_ubo=True,
        ownership_pct=40, control_type="DIRECT_OWNERSHIP",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["ownership_pct"] in ("40.00", 40, "40")

    [entry] = await _contact_history(client, token, customer_id)
    assert entry["event_type"] == "person_added"
    assert entry["to_value"] == "UBO"
    assert entry["details"]["contact_name"] == "Anita Rao"


async def test_a_plain_contact_writes_no_person_history(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    assert (await _add(client, token, customer_id, name="Just A Contact")).status_code == 201

    assert await _contact_history(client, token, customer_id) == []


async def test_taking_the_director_role_away_clears_the_din(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    person_id = (
        await _add(client, token, customer_id, name="Former Director", is_director=True, din="76543210")
    ).json()["id"]

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{person_id}",
        headers=auth_header(token),
        json={"is_director": False},
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["is_director"], resp.json()["din"]) == (False, None)
    latest = (await _contact_history(client, token, customer_id))[0]
    assert latest["event_type"] == "person_roles_changed"
    assert (latest["from_value"], latest["to_value"]) == ("CONTACT,DIRECTOR", "CONTACT")


async def test_a_primary_contact_who_stops_being_a_contact_stops_being_primary(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    person_id = (
        await _add(client, token, customer_id, name="Owner And Contact", is_ubo=True, is_primary=True)
    ).json()["id"]

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{person_id}",
        headers=auth_header(token),
        json={"is_contact": False},
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["is_contact"], resp.json()["is_primary_contact"]) == (False, False)


async def test_clearing_the_identification_number_clears_its_type(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    person_id = (await _add(client, token, customer_id, **DIRECTOR)).json()["id"]

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{person_id}",
        headers=auth_header(token),
        json={"identification_number": None},
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["identification_number"], resp.json()["identification_type"]) == (None, None)


# ── Direct SQL ───────────────────────────────────────────────────────────────


def _person(cur, customer_id, **columns) -> uuid.UUID:
    person_id = uuid.uuid4()
    values = {"name": "SQL Person", **columns}
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    cur.execute(
        f"INSERT INTO onboarding.exporter_contact (id, customer_id, {names}) "
        f"VALUES (%s, %s, {marks})",
        (str(person_id), str(customer_id), *values.values()),
    )
    return person_id


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"is_contact": False}, "ck_exporter_contact_has_role"),
        ({"is_contact": False, "is_ubo": True, "is_primary_contact": True},
         "ck_exporter_contact_primary_is_contact"),
        ({"din": "01234567"}, "ck_exporter_contact_din"),
        ({"is_director": True, "din": "1234"}, "ck_exporter_contact_din"),
        ({"ownership_pct": 10}, "ck_exporter_contact_ownership"),
        ({"is_ubo": True, "ownership_pct": 101}, "ck_exporter_contact_ownership"),
        ({"is_ubo": True, "control_type": "FRIENDSHIP"}, "ck_exporter_contact_control_type"),
        ({"nationality": "in"}, "ck_exporter_contact_nationality"),
        ({"residence_country": "in"}, "ck_exporter_contact_residence"),
        ({"identification_type": "PASSPORT"}, "ck_exporter_contact_identification"),
        ({"identification_type": "PASSPORT", "identification_encrypted": "x",
          "identification_last4": "1234"}, None),
    ],
)
async def test_the_database_holds_the_people_rules(columns, constraint):
    with pg() as cur:
        customer_id = insert_company(cur)
        if constraint is None:
            _person(cur, customer_id, **columns)
            return
        with pytest.raises(psycopg2.errors.CheckViolation, match=constraint):
            _person(cur, customer_id, **columns)


async def test_a_person_is_never_deleted():
    with pg() as cur:
        customer_id = insert_company(cur)
        person_id = _person(cur, customer_id, is_director=True)
        with pytest.raises(psycopg2.errors.RaiseException, match="never deleted"):
            cur.execute("DELETE FROM onboarding.exporter_contact WHERE id = %s", (str(person_id),))


async def test_a_screening_run_names_a_person_of_its_own_company():
    with pg() as cur:
        company_id, other_company = insert_company(cur), insert_company(cur)
        stranger = _person(cur, other_company, is_ubo=True)
        with pytest.raises(
            psycopg2.errors.ForeignKeyViolation, match="fk_sanctions_run_subject_person"
        ):
            cur.execute(
                "INSERT INTO onboarding.sanctions_run (id, company_id, subject_type, "
                "subject_name, subject_reference, performed_by, performed_at, provider) "
                "VALUES (%s, %s, 'UBO', 'Stranger', %s, 'tester', now(), 'MANUAL')",
                (str(uuid.uuid4()), str(company_id), str(stranger)),
            )
