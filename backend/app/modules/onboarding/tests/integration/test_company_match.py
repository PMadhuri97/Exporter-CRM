"""``POST /companies/match`` and the matcher behind it.

The interesting tests here are not "does it find the company" but the three things
that make this route safe to expose to a role that sees identifiers masked:

* a **full** identifier names the company, and nothing shorter is accepted;
* the response carries **no identifier at all**, for any role;
* every identifier lookup leaves an **audit row** — including one that found
  nothing, which is the lookup a probe would be making.

Plus the ordering rule: an identifier always beats a name, so a near-match on a
name can never cast doubt on an identity.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.audit import AuditService
from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_names import (
    looks_like_the_same_company,
    name_key,
    normalise_company_name,
    strip_legal_suffix,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
LOOKUP_EVENT = "company_directory.identifier_lookup"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _registration() -> str:
    return f"REG-{uuid.uuid4().hex[:10].upper()}"


async def _company(*, name: str, country: str = "IN", **fields) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name=name, country=country, **fields
        )
    return customer_id


async def _lookup_payloads(actor_id: str) -> list[dict]:
    """The identifier-lookup audit rows written by one user, oldest first.

    Read through `AuditService` rather than the audit entity: the audit module
    publishes a facade and the import linter holds other modules to it, which is
    also why this filters the actor in Python — the query API takes an actor *type*,
    not an id, and widening it for a test would be the wrong way round.

    Scoped to the actor either way, never counted globally: this database is shared
    between tests and between runs, so "how many rows are there" is not a question
    about this test.
    """
    async with db_services.AsyncSessionLocal() as db:
        page = await AuditService(db).query(event_type=LOOKUP_EVENT, limit=200)
    return [
        event.payload
        for event in page.events
        if str(event.actor_id) == str(actor_id)
    ]


async def _lookup_rows(actor_id: str) -> int:
    return len(await _lookup_payloads(actor_id))


async def _match(client: AsyncClient, token: str, **body):
    return await client.post(
        f"{BASE}/companies/match", json=body, headers=auth_header(token)
    )


# ── The name rule, without a database ─────────────────────────────────────────


def test_a_name_is_normalised_before_it_is_compared():
    assert normalise_company_name("  Acme   Exports,  Pvt. Ltd. ") == "ACME EXPORTS PVT LTD"
    assert normalise_company_name("!!!") == ""
    assert normalise_company_name(None) == ""


def test_a_trailing_legal_form_comes_off_and_only_a_trailing_one():
    assert strip_legal_suffix("Acme Exports Pvt Ltd") == "ACME EXPORTS"
    assert strip_legal_suffix("Rotterdam Trading B.V.") == "ROTTERDAM TRADING"
    # Not at the end: part of the name.
    assert strip_legal_suffix("Limited Stationers") == "LIMITED STATIONERS"
    # Nothing would be left: left alone, so a company really called this still matches
    # itself rather than becoming the empty name that matches everything.
    assert strip_legal_suffix("Ltd") == "LTD"


def test_two_names_match_only_when_they_differ_in_form_rather_than_in_words():
    assert looks_like_the_same_company("Acme Exports Pvt Ltd", "ACME EXPORTS")
    assert looks_like_the_same_company("Rotterdam Trading BV", "rotterdam-trading")
    # The case a similarity score gets wrong: one word apart, different companies.
    assert not looks_like_the_same_company("Gupta Exports", "Gupta Imports")
    assert not looks_like_the_same_company("Acme Exports", "Acme Export")
    # Two nameless rows are not evidence of anything.
    assert not looks_like_the_same_company("", "")
    assert not looks_like_the_same_company(None, "!!!")


def test_the_name_key_is_what_the_matcher_groups_by():
    assert name_key("Acme Exports Private Limited") == name_key("acme  exports")


# ── An exact identifier names the company ─────────────────────────────────────


async def test_a_full_pan_names_the_company(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    company_id = await _company(name="Mumbai Textiles", pan=pan)

    resp = await _match(client, token, name="Something Else Entirely", country="IN", pan=pan)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "MATCHED"
    assert body["company_id"] == str(company_id)
    assert body["needs_a_person"] is False
    # Named even though the name the caller typed does not resemble it: an identity
    # is an identity, and the mismatch is for the person to notice.
    assert body["candidates"][0]["name"] == "Mumbai Textiles"


async def test_a_full_registration_number_names_the_company(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    registration = _registration()
    company_id = await _company(
        name="Rotterdam Trading BV", country="NL", registration_number=registration
    )

    # Punctuation and case differ: one registration.
    resp = await _match(
        client,
        token,
        name="Rotterdam Trading BV",
        country="nl",
        registration_number=registration.lower().replace("-", " "),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_id"] == str(company_id)


async def test_the_same_number_in_another_country_is_not_the_same_company(
    client: AsyncClient,
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    registration = _registration()
    await _company(name="Dutch Co", country="NL", registration_number=registration)

    resp = await _match(
        client, token, name="Belgian Co", country="BE", registration_number=registration
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "NEW"


async def test_an_identifier_beats_a_similar_name(client: AsyncClient):
    """The ordering rule. A PAN named a company, so the near-match on the name is not
    even reported — letting it in would mean an identity could be made doubtful by
    some other company happening to be named similarly."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    shared_name = f"Twin Exports {uuid.uuid4().hex[:8]}"
    pan = _pan()
    by_pan = await _company(name=f"{shared_name} Pvt Ltd", pan=pan)
    await _company(name=shared_name)  # same normalised name, no identifier

    resp = await _match(client, token, name=shared_name, country="IN", pan=pan)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "MATCHED"
    assert body["company_id"] == str(by_pan)
    assert [c["company_id"] for c in body["candidates"]] == [str(by_pan)]


# ── Nothing shorter than a whole identifier ───────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [("pan", "ABCDE"), ("gstin", "27ABCDE"), ("registration_number", "K")],
)
async def test_a_partial_identifier_is_refused(client: AsyncClient, field: str, value: str):
    """This is the rule that keeps the route from being walked to read identifiers
    out of the CRM. A prefix search would answer "does any company's PAN start with
    ABCDE" — and ten such questions name the company."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await _match(client, token, name="Anyone", country="IN", **{field: value})
    assert resp.status_code == 422, resp.text


async def test_a_masked_value_sent_back_is_refused(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await _match(client, token, name="Anyone", country="IN", pan="••••••1234F")
    assert resp.status_code == 422, resp.text


# ── The response never carries an identifier ──────────────────────────────────


async def test_no_identifier_appears_in_the_response_for_any_role(client: AsyncClient):
    """Not even masked. A candidate is an id, a name, a country and whether it is in
    the pipeline — enough to tell two companies apart, and nothing more."""
    pan = _pan()
    registration = _registration()
    await _company(
        name="Fully Identified BV",
        country="NL",
        pan=pan,
        registration_number=registration,
        iec="1234567890",
    )

    for role in (UserRole.OPERATIONS, UserRole.COMPLIANCE):
        _user_id, token = await user_with_role(client, role)
        resp = await _match(
            client, token, name="Fully Identified BV", country="NL", pan=pan
        )
        assert resp.status_code == 200, resp.text
        [candidate] = resp.json()["candidates"]
        assert set(candidate) == {"company_id", "name", "country", "pipeline_status"}, role
        assert registration not in resp.text, role
        assert "1234567890" not in resp.text, role


async def test_a_read_only_role_may_not_ask(client: AsyncClient):
    """DEVELOPER is read-only, may never reveal an identifier, and has no buyer to
    resolve — so it does not get the disclosure exception at all."""
    _user_id, token = await user_with_role(client, UserRole.DEVELOPER)
    resp = await _match(client, token, name="Anyone", country="IN", pan=_pan())
    assert resp.status_code == 403, resp.text


# ── Every identifier lookup is audited ────────────────────────────────────────


async def test_an_identifier_lookup_writes_an_audit_row(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    company_id = await _company(name="Audited Co", pan=pan)

    assert await _lookup_rows(user_id) == 0
    resp = await _match(client, token, name="Audited Co", country="IN", pan=pan)
    assert resp.status_code == 200, resp.text

    [payload] = await _lookup_payloads(user_id)
    assert payload["identifier_kinds"] == ["PAN"]
    assert payload["matched_company_ids"] == [str(company_id)]
    assert payload["actor_role"] == UserRole.OPERATIONS.value
    # The value itself is never recorded: this table exists to watch who saw
    # identifiers, so writing one into it would defeat the purpose.
    assert pan not in str(payload)


async def test_a_lookup_that_finds_nothing_is_audited_too(client: AsyncClient):
    """The one most worth recording. "No company holds this PAN" is still an answer,
    and a caller probing for which identifiers exist would only ever see misses."""
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await _match(client, token, name="Nobody At All", country="IN", pan=_pan())
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "NEW"

    [payload] = await _lookup_payloads(user_id)
    assert payload["matched"] is False
    assert payload["matched_company_ids"] == []


async def test_a_name_only_search_writes_no_identifier_audit_row(client: AsyncClient):
    """Searching by name is not a disclosure, so it is not audited here. Auditing it
    would bury the identifier lookups the audit exists for in ordinary traffic."""
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await _match(client, token, name=f"Unaudited {uuid.uuid4().hex[:8]}", country="IN")
    assert resp.status_code == 200, resp.text
    assert await _lookup_rows(user_id) == 0


# ── POSSIBLE_DUPLICATE and CONFLICT ───────────────────────────────────────────


async def test_a_similar_name_in_the_same_country_is_a_possible_duplicate(
    client: AsyncClient,
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    base = f"Chennai Spices {uuid.uuid4().hex[:8]}"
    company_id = await _company(name=f"{base} Private Limited")

    resp = await _match(client, token, name=f"{base} Pvt. Ltd.", country="IN")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "POSSIBLE_DUPLICATE"
    # Never picks one: a person decides.
    assert body["company_id"] is None
    assert body["needs_a_person"] is True
    assert str(company_id) in [c["company_id"] for c in body["candidates"]]


async def test_a_similar_name_in_another_country_is_not_a_duplicate(client: AsyncClient):
    """Two companies may legitimately share a name in different jurisdictions, and
    nothing about that suggests they are one company."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    base = f"Global Trading {uuid.uuid4().hex[:8]}"
    await _company(name=f"{base} Pvt Ltd", country="IN")

    resp = await _match(client, token, name=f"{base} BV", country="NL")
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "NEW"


async def test_a_gstin_held_by_two_companies_returns_both(client: AsyncClient):
    """A GSTIN on two companies is allowed, so the matcher cannot
    treat it as an identity. Both are returned for the RM to choose between rather
    than one being picked."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    gstin = f"27{pan}1Z5"
    first = await _company(name="Shared GSTIN One", pan=pan, gstins=[gstin])
    second = await _company(name="Shared GSTIN Two", gstins=[gstin])

    resp = await _match(client, token, name="Shared GSTIN One", country="IN", gstin=gstin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "CONFLICT"
    assert body["company_id"] is None
    assert body["needs_a_person"] is True
    assert {c["company_id"] for c in body["candidates"]} == {str(first), str(second)}


async def test_a_pan_and_a_gstin_naming_different_companies_is_a_conflict(
    client: AsyncClient,
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan_a, pan_b = _pan(), _pan()
    by_pan = await _company(name="PAN Holder", pan=pan_a)
    by_gstin = await _company(name="GSTIN Holder", pan=pan_b, gstins=[f"27{pan_b}1Z5"])

    resp = await _match(
        client, token, name="Either", country="IN", pan=pan_a, gstin=f"27{pan_b}1Z5"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "CONFLICT"
    assert {c["company_id"] for c in body["candidates"]} == {str(by_pan), str(by_gstin)}
    assert "more than one company" in body["reason"]


async def test_nothing_at_all_is_new(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await _match(
        client, token, name=f"Brand New Co {uuid.uuid4().hex[:12]}", country="IN"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "NEW"
    assert body["candidates"] == []
    assert body["reason"] is None
    assert body["needs_a_person"] is False


# ── A buyer-only company is findable, and says so ─────────────────────────────


async def test_a_buyer_only_company_is_matched_and_marked(client: AsyncClient):
    """The common case this route exists for: the RM types a buyer's name and finds
    the company the migration already made for it. `pipeline_status` is what tells
    them this is that record rather than a different company."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    name = f"Antwerp Shipping {uuid.uuid4().hex[:8]}"
    registration = _registration()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(name=name, country="BE", registration_number=registration),
            actor_id="rm-1",
        )

    resp = await _match(
        client, token, name=name, country="BE", registration_number=registration
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company_id"] == str(company_id)
    assert body["candidates"][0]["pipeline_status"] == "NOT_IN_PIPELINE"


async def test_matching_creates_nothing(client: AsyncClient):
    """`match` classifies; it never writes a company. Worth asserting because the
    route sits next to a create path and the migration calls both."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    name = f"Not Created {uuid.uuid4().hex[:12]}"
    pan = _pan()

    resp = await _match(client, token, name=name, country="IN", pan=pan)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "NEW"

    # Asked of this name and this PAN rather than of the whole table: a count over
    # every company would also move whenever anything else on this shared database
    # created one, which says nothing about `match`.
    async with db_services.AsyncSessionLocal() as db:
        from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile

        assert (
            await db.scalar(
                select(func.count())
                .select_from(ExporterProfile)
                .where(
                    (ExporterProfile.name == name) | (ExporterProfile.pan == pan)
                )
            )
            == 0
        )
