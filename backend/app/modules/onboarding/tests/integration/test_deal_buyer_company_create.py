"""Creating a deal's buyer as a company.

The third form of ``PUT /deals/{id}/buyer``: ``{create: {...}}`` creates the buyer as a
company **outside the pipeline** and names it, in one step. What matters:

* it is a buyer, not a lead — ``NOT_IN_PIPELINE``, no journey row, no change to the
  pipeline's counts;
* it matches first: an identifier a company on file holds is refused, naming it, and
  the lookup is audited; a name that only resembles one is not;
* a foreign buyer needs its registration number — the migration's exemption is
  not for buyers entered now;
* staff only, and the response is masked per role like any buyer company.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.audit import AuditService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.trade_history_service import TradeHistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.modules.onboarding.tests.fixtures.deals import make_deal
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _registration() -> str:
    return f"KVK-{uuid.uuid4().hex[:8].upper()}"


def _name(prefix: str = "Created Buyer") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8].upper()}"


async def _put(client: AsyncClient, token: str, deal_id: uuid.UUID, **create):
    return await client.put(
        f"{BASE}/deals/{deal_id}/buyer", json={"create": create}, headers=auth_header(token)
    )


async def _token(client: AsyncClient, role: UserRole = UserRole.OPERATIONS) -> str:
    _user_id, token = await user_with_role(client, role)
    return token


async def _company(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


async def _in_pipeline_leads() -> int:
    async with db_services.AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ExporterProfile)
                .where(ExporterProfile.pipeline_status == CompanyPipelineStatus.IN_PIPELINE)
            )
        )


# ── A buyer, not a lead ───────────────────────────────────────────────────────


async def test_a_foreign_buyer_is_created_outside_the_pipeline_and_named(client: AsyncClient):
    seller = await make_prospect()
    deal_id = await make_deal(seller)
    leads_before = await _in_pipeline_leads()
    name, registration = _name(), _registration()

    resp = await _put(
        client,
        await _token(client),
        deal_id,
        name=name,
        country="nl",
        registration_number=registration,
    )
    assert resp.status_code == 200, resp.text
    buyer = resp.json()["buyer_company"]
    assert buyer["name"] == name and buyer["country"] == "NL"
    company_id = uuid.UUID(buyer["company_id"])

    company = await _company(company_id)
    assert company.pipeline_status is CompanyPipelineStatus.NOT_IN_PIPELINE
    assert company.source is ExporterSource.DEAL_BUYER
    assert company.created_via == "DEAL_BUYER"
    assert company.created_via_deal_id == deal_id
    assert company.identity_type is CompanyIdentityType.FOREIGN_REG
    # Not a lead: the pipeline's count does not move, and there is no journey row.
    assert await _in_pipeline_leads() == leads_before
    async with db_services.AsyncSessionLocal() as db:
        journey, _ = await HistoryService(db).list_for_company(
            company_id, dimension=history_dimensions.JOURNEY, limit=10
        )
        relationship = await TradeHistoryService(db).relationship_for_pair(
            seller_company_id=seller, buyer_company_id=company_id
        )
        deal = await db.scalar(select(Deal).where(Deal.id == deal_id))
    assert list(journey) == []
    assert relationship is not None, "naming the buyer company creates the pair's relationship"
    assert deal.buyer_company_id == company_id


async def test_an_indian_buyer_with_a_pan_is_in_pan(client: AsyncClient):
    deal_id = await make_deal()
    pan = _pan()
    resp = await _put(
        client,
        await _token(client, UserRole.COMPLIANCE),
        deal_id,
        name=_name(),
        country="IN",
        pan=pan,
        gstin=f"27{pan}1Z5",
    )
    assert resp.status_code == 200, resp.text
    company = await _company(uuid.UUID(resp.json()["buyer_company"]["company_id"]))
    assert company.identity_type is CompanyIdentityType.IN_PAN
    assert company.pan == pan
    assert company.gstins == [f"27{pan}1Z5"]


async def test_a_foreign_buyer_without_a_registration_number_is_refused(client: AsyncClient):
    """The foreign-identity rule. The buyer migration's exemption covers rows that predate it."""
    deal_id = await make_deal()
    name = _name()
    resp = await _put(client, await _token(client), deal_id, name=name, country="DE")
    assert resp.status_code == 422, resp.text
    assert "Registration number is required" in resp.text
    async with db_services.AsyncSessionLocal() as db:
        assert await db.scalar(select(ExporterProfile).where(ExporterProfile.name == name)) is None
        assert (await db.scalar(select(Deal).where(Deal.id == deal_id))).buyer_company_id is None


# ── Match first ───────────────────────────────────────────────────────────────


async def test_an_identifier_a_company_holds_is_refused_naming_that_company(client: AsyncClient):
    registration = _registration()
    existing = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            existing,
            source=ExporterSource.SALES,
            name=_name("Already On File"),
            country="NL",
            registration_number=registration,
        )
    deal_id = await make_deal()
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    resp = await _put(
        client,
        token,
        deal_id,
        name=_name("Typed Differently"),
        country="NL",
        registration_number=registration.lower().replace("-", " "),
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "BUYER_COMPANY_ALREADY_KNOWN"
    assert body["error_context"]["match_kind"] == "MATCHED"
    assert body["error_context"]["company_ids"] == [str(existing)]
    # Nothing echoed back, and the lookup is on the audit trail.
    assert registration not in resp.text
    async with db_services.AsyncSessionLocal() as db:
        page = await AuditService(db).query(
            event_type="company_directory.identifier_lookup", limit=200
        )
    assert any(str(e.actor_id) == str(user_id) for e in page.events)

    # Choosing the existing company is the way forward.
    chosen = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={"buyer_company_id": str(existing)},
        headers=auth_header(token),
    )
    assert chosen.status_code == 200, chosen.text


async def test_identifiers_naming_two_companies_are_a_conflict(client: AsyncClient):
    pan, other_pan = _pan(), _pan()
    for company_pan in (pan, other_pan):
        async with db_services.AsyncSessionLocal() as db:
            await ExporterProfileService(db).create_or_get_profile(
                uuid.uuid4(),
                source=ExporterSource.SALES,
                name=_name("Holder"),
                country="IN",
                pan=company_pan,
                gstins=[f"27{company_pan}1Z5"],
            )
    deal_id = await make_deal()
    resp = await _put(
        client,
        await _token(client),
        deal_id,
        name=_name(),
        country="IN",
        pan=pan,
        gstin=f"27{other_pan}1Z5",
    )
    # The PAN and GSTIN disagree anyway; whichever check answers, nothing is created.
    assert resp.status_code in (409, 422), resp.text
    async with db_services.AsyncSessionLocal() as db:
        assert (await db.scalar(select(Deal).where(Deal.id == deal_id))).buyer_company_id is None


async def test_a_name_that_only_resembles_a_company_is_not_an_identity(client: AsyncClient):
    """A name never merges. The picker has already shown the look-alikes."""
    name = _name("Lookalike Trading")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(),
            source=ExporterSource.SALES,
            name=f"{name} BV",
            country="NL",
            registration_number=_registration(),
        )
    deal_id = await make_deal()
    resp = await _put(
        client,
        await _token(client),
        deal_id,
        name=f"{name.lower()} b.v.",
        country="NL",
        registration_number=_registration(),
    )
    assert resp.status_code == 200, resp.text


# ── The deal must be able to take it ──────────────────────────────────────────


async def test_a_deal_that_already_names_a_buyer_company_is_refused(client: AsyncClient):
    deal_id = await make_deal()
    token = await _token(client)
    first = await _put(
        client, token, deal_id, name=_name(), country="NL", registration_number=_registration()
    )
    assert first.status_code == 200, first.text
    second = await _put(
        client, token, deal_id, name=_name(), country="NL", registration_number=_registration()
    )
    assert second.status_code == 409, second.text


async def test_a_closed_deal_is_refused(client: AsyncClient):
    deal_id = await make_deal()
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )
    resp = await _put(
        client,
        await _token(client),
        deal_id,
        name=_name(),
        country="NL",
        registration_number=_registration(),
    )
    assert resp.status_code == 409, resp.text


async def test_create_is_its_own_form(client: AsyncClient):
    deal_id = await make_deal()
    resp = await client.put(
        f"{BASE}/deals/{deal_id}/buyer",
        json={
            "create": {"name": _name(), "country": "NL", "registration_number": _registration()},
            "buyer_company_id": str(uuid.uuid4()),
        },
        headers=auth_header(await _token(client)),
    )
    assert resp.status_code == 422, resp.text


# ── Who may, and what they see ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("role", "status"),
    [
        (UserRole.OPERATIONS, 200),
        (UserRole.COMPLIANCE, 200),
        (UserRole.ADMIN, 200),
        (UserRole.DEVELOPER, 403),
        (UserRole.API_USER, 403),
    ],
)
async def test_only_staff_may_create_a_buyer_company(client: AsyncClient, role, status):
    deal_id = await make_deal()
    name = _name()
    resp = await _put(
        client,
        await _token(client, role),
        deal_id,
        name=name,
        country="NL",
        registration_number=_registration(),
    )
    assert resp.status_code == status, resp.text
    if status == 403:
        async with db_services.AsyncSessionLocal() as db:
            assert (
                await db.scalar(select(ExporterProfile).where(ExporterProfile.name == name)) is None
            )


@pytest.mark.parametrize(
    ("role", "revealed"),
    [(UserRole.OPERATIONS, False), (UserRole.COMPLIANCE, True), (UserRole.ADMIN, True)],
)
async def test_the_response_is_masked_per_role(client: AsyncClient, role, revealed):
    deal_id = await make_deal()
    pan = _pan()
    resp = await _put(
        client, await _token(client, role), deal_id, name=_name(), country="IN", pan=pan
    )
    assert resp.status_code == 200, resp.text
    served = resp.json()["buyer_company"]["pan"]
    assert (served == pan) is revealed
    assert served.endswith(pan[-4:])
    if not revealed:
        assert pan not in resp.text

    # And DEVELOPER, reading the deal afterwards, sees it masked too.
    seen = await client.get(
        f"{BASE}/deals/{deal_id}", headers=auth_header(await _token(client, UserRole.DEVELOPER))
    )
    assert seen.status_code == 200, seen.text
    assert pan not in seen.text
