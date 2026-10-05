"""The identity completion list.

``GET /companies/identity-completion`` lists the companies the CRM cannot identify:
``identity_type`` is ``NULL`` because they hold neither a PAN nor a registration number.
The buyer migration's companies are the expected case — created without a number because the
rule could not be met retroactively — and the older rows with no country are the other.

What is tested is what makes it a work list rather than a filter: each entry says what
it lacks and whether a rule requires it, the required ones come first, ended companies
are not work, an edit that adds the identifier takes the company off, and the response
carries no identifier for anyone.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_identity import IdentityGap, identity_gap
from app.modules.onboarding.domain.entities.exporter_enums import ExporterMarker, ExporterSource
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.deals import make_deal
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

ROUTE = "/api/v1/onboarding/companies/identity-completion"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


async def _migrated_buyer(country: str = "NL") -> uuid.UUID:
    """What the buyer migration makes of a buyer with no identifier: a company with none."""
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=f"Migrated {uuid.uuid4().hex[:8]}",
                country=country,
                created_via_deal_id=await make_deal(),
            ),
            actor_id="migration",
        )


async def _all_entries(client: AsyncClient, token: str) -> list[dict]:
    """Every page — the shared test database holds many such companies."""
    entries, offset = [], 0
    while True:
        resp = await client.get(
            ROUTE, params={"limit": 200, "offset": offset}, headers=auth_header(token)
        )
        assert resp.status_code == 200, resp.text
        page = resp.json()
        entries += page["items"]
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            return entries


async def _token(client: AsyncClient, role: UserRole = UserRole.OPERATIONS) -> str:
    _user_id, token = await user_with_role(client, role)
    return token


async def test_what_each_kind_of_company_lacks():
    assert identity_gap("NL") is IdentityGap.REGISTRATION_NUMBER
    assert identity_gap("in") is IdentityGap.PAN
    assert identity_gap(None) is IdentityGap.COUNTRY


async def test_a_migrated_buyer_with_no_number_is_listed_as_required(client: AsyncClient):
    company_id = await _migrated_buyer("NL")
    entries = {e["company_id"]: e for e in await _all_entries(client, await _token(client))}
    entry = entries[str(company_id)]
    assert entry["missing"] == "REGISTRATION_NUMBER"
    assert entry["required"] is True
    assert entry["pipeline_status"] == "NOT_IN_PIPELINE"
    assert entry["created_via"] == "DEAL_BUYER"


async def test_an_indian_company_without_a_pan_is_listed_but_not_required(client: AsyncClient):
    company_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id,
            source=ExporterSource.SALES,
            name=f"No PAN {uuid.uuid4().hex[:6]}",
            country="IN",
        )
    entries = {e["company_id"]: e for e in await _all_entries(client, await _token(client))}
    assert entries[str(company_id)]["missing"] == "PAN"
    assert entries[str(company_id)]["required"] is False


async def test_required_gaps_come_first(client: AsyncClient):
    await _migrated_buyer("DE")
    entries = await _all_entries(client, await _token(client))
    flags = [e["required"] for e in entries]
    # Every required entry precedes every merely-useful one.
    assert flags == sorted(flags, reverse=True)


async def test_adding_the_identifier_takes_the_company_off(client: AsyncClient):
    """The point of the list: completing the company is what removes it."""
    company_id = await _migrated_buyer("NL")
    token = await _token(client)
    assert str(company_id) in {e["company_id"] for e in await _all_entries(client, token)}

    resp = await client.patch(
        f"/api/v1/onboarding/exporters/{company_id}",
        json={"registration_number": f"KVK-{uuid.uuid4().hex[:8].upper()}"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert str(company_id) not in {e["company_id"] for e in await _all_entries(client, token)}


async def test_an_ended_company_is_not_work(client: AsyncClient):
    company_id = await _migrated_buyer("NL")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).set_marker(
            company_id, ExporterMarker.ENDED, reason="No longer trading", actor_id="rm-1"
        )
    entries = await _all_entries(client, await _token(client))
    assert str(company_id) not in {e["company_id"] for e in entries}


async def test_a_company_with_an_identifier_is_never_listed(client: AsyncClient):
    company_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id,
            source=ExporterSource.SALES,
            name=f"Has PAN {uuid.uuid4().hex[:6]}",
            country="IN",
            pan=_pan(),
        )
    entries = await _all_entries(client, await _token(client))
    assert str(company_id) not in {e["company_id"] for e in entries}


@pytest.mark.parametrize(
    ("role", "status"),
    [
        (UserRole.OPERATIONS, 200),
        (UserRole.COMPLIANCE, 200),
        (UserRole.ADMIN, 200),
        (UserRole.DEVELOPER, 200),
        (UserRole.API_USER, 403),
    ],
)
async def test_who_may_read_it(client: AsyncClient, role, status):
    resp = await client.get(ROUTE, headers=auth_header(await _token(client, role)))
    assert resp.status_code == status, resp.text


async def test_it_carries_no_identifier_fields():
    """Nothing to mask for any role: the shape has no identifier in it."""
    from app.modules.onboarding.api.schemas.company_directory import IdentityCompletionItem

    fields = set(IdentityCompletionItem.model_fields)
    assert not fields & {"pan", "gstins", "gstin", "iec", "cin", "registration_number"}
