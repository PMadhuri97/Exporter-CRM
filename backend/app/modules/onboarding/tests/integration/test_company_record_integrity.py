"""The company record's integrity rules (contract ``company-record.md``).

* **Masked history** — a registration number is masked in history, for every reader,
  including rows written before the fix (served masked; history is never rewritten).
* **Identity after edits** — ``identity_type`` follows the PAN and the registration
  number through edits, and the foreign-identity rule holds on the company as it will
  be after an edit.
* **Exact comparison** — registration numbers compare exactly as the database's unique
  index does, so "no company holds this" is never followed by an ``IntegrityError``.
* **No buyer-sourced leads** — ``POST /exporters`` does not create a lead sourced as a
  deal's buyer.
* **Audit actor type** — the ``/companies/match`` audit row's actor type follows the audit module's
  own definitions; the caller's role is recorded beside it.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.application.company_directory import (
    CompanyDirectoryService,
    actor_type_for_role,
)
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_identity import (
    normalise_registration_number,
    registration_key,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import DuplicateRegistrationNumberError
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.deals import make_deal
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _registration() -> str:
    return f"REG-{uuid.uuid4().hex[:10].upper()}"


async def _company(country: str, **fields) -> uuid.UUID:
    company_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id,
            source=ExporterSource.SALES,
            name=f"Integrity {uuid.uuid4().hex[:8]}",
            country=country,
            **fields,
        )
    return company_id


async def _edit(company_id: uuid.UUID, **changes) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await ExporterProfileService(db).update_profile(company_id, changes, actor_id="rm-1")


async def _profile(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


# ── History never serves a registration number in full ────────────────────────


async def test_an_edited_registration_number_is_written_to_history_masked():
    old, new = _registration(), _registration()
    company_id = await _company("NL", registration_number=old)
    await _edit(company_id, registration_number=new)

    async with db_services.AsyncSessionLocal() as db:
        [row] = list(
            await db.scalars(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == company_id,
                    ExporterLifecycleHistory.dimension == "profile",
                )
            )
        )
    stored = row.event_metadata
    assert stored["field"] == "registration_number"
    assert old not in str(stored) and new not in str(stored)
    assert stored["to"].endswith(new[-4:])


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER, UserRole.COMPLIANCE])
async def test_a_row_written_before_the_fix_is_served_masked(client: AsyncClient, role):
    """A row the old writer left with the raw values. It stays as written — history is
    append-only — and is masked when served, to every reader, as new rows are."""
    old, new = _registration(), _registration()
    company_id = await _company("NL", registration_number=new)
    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id,
            dimension="profile",
            to_value="registration_number",
            actor_id="rm-1",
            source="exporter_profile_service.update_profile",
            event_type="profile_transition",
            details={"field": "registration_number", "from": old, "to": new, "edit_id": "x"},
        )
        await db.commit()

    _user_id, token = await user_with_role(client, role)
    resp = await client.get(f"{BASE}/exporters/{company_id}/history", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    assert old not in resp.text and new not in resp.text
    [edit] = [e for e in resp.json()["entries"] if e["dimension"] == "profile"]
    assert edit["details"]["from"].endswith(old[-4:])
    assert edit["details"]["to"].endswith(new[-4:])


# ── identity_type and the foreign-identity rule after an edit ─────────────────


async def test_adding_a_pan_makes_the_company_in_pan():
    company_id = await _company("IN")
    assert (await _profile(company_id)).identity_type is None
    profile = await _edit(company_id, pan=_pan())
    assert profile.identity_type is CompanyIdentityType.IN_PAN


async def test_removing_the_pan_of_an_indian_company_leaves_it_unidentified():
    company_id = await _company("IN", pan=_pan())
    profile = await _edit(company_id, pan=None)
    assert profile.identity_type is None


async def test_moving_a_company_abroad_needs_a_registration_number():
    company_id = await _company("IN")
    with pytest.raises(ValidationError, match="Registration number is required"):
        await _edit(company_id, country="NL")
    assert (await _profile(company_id)).country == "IN"

    profile = await _edit(company_id, country="NL", registration_number=_registration())
    assert profile.identity_type is CompanyIdentityType.FOREIGN_REG


async def test_a_company_with_a_pan_may_move_abroad_and_stays_in_pan():
    """A company holding a PAN is Indian whatever its country column says."""
    company_id = await _company("IN", pan=_pan())
    profile = await _edit(company_id, country="AE")
    assert profile.identity_type is CompanyIdentityType.IN_PAN


async def test_bringing_a_foreign_company_home_keeps_what_identifies_it():
    company_id = await _company("NL", registration_number=_registration())
    profile = await _edit(company_id, country="IN")
    assert profile.identity_type is CompanyIdentityType.FOREIGN_REG
    profile = await _edit(company_id, pan=_pan())
    assert profile.identity_type is CompanyIdentityType.IN_PAN


async def test_clearing_a_foreign_companys_registration_number_is_refused():
    registration = _registration()
    company_id = await _company("NL", registration_number=registration)
    with pytest.raises(ValidationError, match="Registration number is required"):
        await _edit(company_id, registration_number=None)
    stored = await _profile(company_id)
    assert stored.registration_number == registration
    assert stored.identity_type is CompanyIdentityType.FOREIGN_REG


async def test_clearing_it_through_the_route_is_a_422(client: AsyncClient):
    company_id = await _company("NL", registration_number=_registration())
    _user_id, token = await user_with_role(client, UserRole.COMPLIANCE)
    resp = await client.patch(
        f"{BASE}/exporters/{company_id}",
        json={"registration_number": None},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_migrated_buyer_without_a_number_keeps_its_exception():
    """The rule's one exception: a buyer the buyer migration created with no number. An
    edit cannot meet the rule retroactively either, so it is not refused for lacking
    one — until a number is added, after which clearing it is refused like any other."""
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=f"Migrated {uuid.uuid4().hex[:8]}",
                country="NL",
                created_via_deal_id=await make_deal(),
            ),
            actor_id="migration",
        )
    profile = await _edit(company_id, country="BE")
    assert profile.identity_type is None

    profile = await _edit(company_id, registration_number=_registration())
    assert profile.identity_type is CompanyIdentityType.FOREIGN_REG
    with pytest.raises(ValidationError):
        await _edit(company_id, registration_number=None)


# ── Compared exactly as the index compares ────────────────────────────────────


async def test_the_key_is_the_indexes_expression():
    """`upper(regexp_replace(n, '[^A-Za-z0-9]', '', 'g'))`: ASCII letters and digits."""
    assert registration_key("KVK 12.345") == registration_key("kvk-12345") == "KVK12345"
    assert registration_key("HRB 1234 B") == "HRB1234B"
    assert registration_key("ÄB-12") == "B12"
    assert registration_key("١٢٣-77") == "77"  # Arabic-Indic digits dropped


async def test_a_number_with_no_ascii_letter_or_digit_is_refused():
    with pytest.raises(ValidationError, match="A-Z, 0-9"):
        normalise_registration_number("株式会社")
    assert normalise_registration_number("  ÄB-12 ") == "ÄB-12"


async def test_a_number_written_partly_in_another_script_finds_its_holder():
    """The confirmed defect: the Python key kept `Ä`, the index dropped it, so the
    lookup said "no company" and the insert then failed with an IntegrityError."""
    suffix = uuid.uuid4().hex[:6].upper()
    holder = await _company("DE", registration_number=f"HRB-{suffix}")

    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            name="Anything", country="DE", registration_number=f"hrb Ä{suffix}"
        )
    assert result.company_id == holder

    with pytest.raises(DuplicateRegistrationNumberError):
        await _company("DE", registration_number=f"hrb Ä{suffix}")


async def test_the_route_reports_the_collision_as_a_duplicate(client: AsyncClient):
    suffix = uuid.uuid4().hex[:6].upper()
    await _company("DE", registration_number=f"HRB-{suffix}")
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": f"Collides {suffix}",
            "country": "DE",
            "registration_number": f"HRB Ä{suffix}",
        },
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DUPLICATE_REGISTRATION_NUMBER"


# ── Not a lead sourced as a deal's buyer ──────────────────────────────────────


async def test_post_exporters_refuses_the_deal_buyer_source(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    body = {"name": f"Not A Buyer {uuid.uuid4().hex[:6]}", "country": "IN"}
    headers = {**auth_header(token), "Idempotency-Key": str(uuid.uuid4())}

    refused = await client.post(
        f"{BASE}/exporters", json={**body, "source": "DEAL_BUYER"}, headers=headers
    )
    assert refused.status_code == 422, refused.text
    assert "DEAL_BUYER" in refused.text

    created = await client.post(
        f"{BASE}/exporters",
        json={**body, "source": "SALES"},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text


async def test_the_buyer_company_path_still_creates_deal_buyer_companies():
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=f"Real Buyer {uuid.uuid4().hex[:6]}",
                country="NL",
                registration_number=_registration(),
                created_via_deal_id=await make_deal(),
            ),
            actor_id="rm-1",
        )
    assert (await _profile(company_id)).source is ExporterSource.DEAL_BUYER


# ── The audit row's actor type ────────────────────────────────────────────────


async def test_actor_types_follow_the_audit_modules_definitions():
    for role in (UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN):
        assert actor_type_for_role(role.value) is ActorType.COMPLIANCE_OFFICER
    assert actor_type_for_role(UserRole.API_USER.value) is ActorType.API_CLIENT
    assert actor_type_for_role(UserRole.DEVELOPER.value) is ActorType.API_CLIENT
    assert actor_type_for_role(None) is ActorType.SYSTEM


async def _lookup_events(actor_id: str) -> list:
    async with db_services.AsyncSessionLocal() as db:
        page = await AuditService(db).query(
            event_type="company_directory.identifier_lookup", limit=200
        )
    return [e for e in page.events if str(e.actor_id) == str(actor_id)]


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.COMPLIANCE])
async def test_each_staff_role_is_audited_as_staff_with_its_role(client: AsyncClient, role):
    user_id, token = await user_with_role(client, role)
    pan = _pan()
    await _company("IN", pan=pan)
    resp = await client.post(
        f"{BASE}/companies/match",
        json={"name": "Anything", "country": "IN", "pan": pan},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text

    [event] = await _lookup_events(user_id)
    assert getattr(event.actor_type, "value", event.actor_type) == "COMPLIANCE_OFFICER"
    assert event.payload["actor_role"] == role.value
    assert pan not in str(event.payload)


async def test_developer_is_refused_and_nothing_is_audited(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.DEVELOPER)
    resp = await client.post(
        f"{BASE}/companies/match",
        json={"name": "Anything", "country": "IN", "pan": _pan()},
        headers=auth_header(token),
    )
    assert resp.status_code == 403
    assert await _lookup_events(user_id) == []


async def test_a_lookup_with_no_caller_is_audited_as_the_platform():
    pan = _pan()
    company_id = await _company("IN", pan=pan)
    async with db_services.AsyncSessionLocal() as db:
        await CompanyDirectoryService(db).match(name="Anything", country="IN", pan=pan)
        await db.commit()
    async with db_services.AsyncSessionLocal() as db:
        page = await AuditService(db).query(
            event_type="company_directory.identifier_lookup", limit=200
        )
    [event] = [e for e in page.events if str(company_id) in e.payload["matched_company_ids"]]
    assert getattr(event.actor_type, "value", event.actor_type) == "SYSTEM"
    assert event.actor_id is None
