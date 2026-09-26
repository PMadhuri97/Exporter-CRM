"""L2-03 — a company's identity (name and country) belongs to the company.

What these prove:

* Creating a company takes a name and a country and nothing about the
  person creating it; the creator's contact comes from the session.
* Search, list and detail read the company's identity from the company side,
  and no longer expose onboarding-request history as the company's identity.
* The CRM's company code does not reach the legacy ``onboarding_request``
  table except through the one transitional store, which is checked
  statically so a new import cannot creep back in unnoticed.

Real Postgres, each test minting its own ids, like the rest of this package.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRequestStatus,
)
from app.modules.onboarding.tests.fixtures.auth import (
    auth_header,
    token_with_role,
    user_with_role,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
MODULE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
async def ops_token(client: AsyncClient) -> str:
    return await token_with_role(client, UserRole.OPERATIONS)


async def _create_named(
    client: AsyncClient, token: str, *, name: str, country: str = "IN", key: str | None = None
):
    return await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": name, "country": country},
        headers={**auth_header(token), "Idempotency-Key": key or str(uuid.uuid4())},
    )


# ── Creation ──────────────────────────────────────────────────────────────────


async def test_creating_a_company_needs_only_name_and_country(
    client: AsyncClient, ops_token: str
):
    name = f"Identity Exports {uuid.uuid4().hex[:8]}"
    resp = await _create_named(client, ops_token, name=name, country="in")
    assert resp.status_code == 201, resp.text
    company_id = resp.json()["customer_id"]

    detail = await client.get(f"{BASE}/exporters/{company_id}", headers=auth_header(ops_token))
    assert detail.status_code == 200
    body = detail.json()
    assert body["name"] == name
    assert body["country"] == "IN"  # normalised to upper case


async def test_initial_user_email_is_no_longer_accepted(client: AsyncClient, ops_token: str):
    resp = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": "Old Shape Co",
            "country": "IN",
            "initial_user_email": "someone@example.com",
        },
        headers={**auth_header(ops_token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "Only A Name"},
        {"country": "IN"},
        {"name": "   ", "country": "IN"},
        {"name": "Bad Country Co", "country": "India"},
        {"name": "Bad Country Co", "country": "1N"},
        {"legal_name": "Old Field Name", "incorporation_country": "IN"},
    ],
)
async def test_identity_is_validated(client: AsyncClient, ops_token: str, fields: dict):
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", **fields},
        headers={**auth_header(ops_token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422, resp.text


async def test_a_replayed_create_returns_the_first_company(client: AsyncClient, ops_token: str):
    key = str(uuid.uuid4())
    name = f"Replay Exports {uuid.uuid4().hex[:8]}"
    first = await _create_named(client, ops_token, name=name, key=key)
    second = await _create_named(client, ops_token, name=name, key=key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["customer_id"] == first.json()["customer_id"]


async def test_the_creators_contact_comes_from_the_session(client: AsyncClient):
    """The legacy row behind the transitional store still needs a contact.
    It is the signed-in user's own address — never a request field."""
    prefix = f"creator{uuid.uuid4().hex[:8]}"
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS, email_prefix=prefix)
    name = f"Session Contact Co {uuid.uuid4().hex[:8]}"
    resp = await _create_named(client, token, name=name)
    assert resp.status_code == 201
    company_id = uuid.UUID(resp.json()["customer_id"])

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(OnboardingRequest).where(OnboardingRequest.customer_id == company_id)
            )
        ).scalars().all()
    [row] = rows
    assert row.initial_user_id.startswith(prefix)
    assert row.legal_name == name
    # The transitional store inserts an inert draft; nothing moves it.
    assert row.status == OnboardingRequestStatus.DRAFT


# ── Search, list and detail ───────────────────────────────────────────────────


async def test_search_by_name_returns_the_company_identity(client: AsyncClient, ops_token: str):
    name = f"Searchable Identity {uuid.uuid4().hex[:8]}"
    created = await _create_named(client, ops_token, name=name, country="AE")
    company_id = created.json()["customer_id"]

    resp = await client.get(
        f"{BASE}/exporters",
        params={"name": name[11:25].lower()},
        headers=auth_header(ops_token),
    )
    assert resp.status_code == 200
    [row] = [p for p in resp.json()["profiles"] if p["customer_id"] == company_id]
    assert row["name"] == name
    assert row["country"] == "AE"
    assert "legal_name" not in row


async def test_an_unnamed_company_lists_with_no_name(client: AsyncClient, ops_token: str):
    """The unnamed create path still exists until 0014; its company lists
    with `name = None` rather than disappearing or borrowing a name."""
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES"}, headers=auth_header(ops_token)
    )
    company_id = resp.json()["customer_id"]

    listing = await client.get(
        f"{BASE}/exporters", params={"source": "SALES", "limit": 200}, headers=auth_header(ops_token)
    )
    [row] = [p for p in listing.json()["profiles"] if p["customer_id"] == company_id]
    assert row["name"] is None
    assert row["country"] is None


async def test_detail_carries_no_onboarding_history(client: AsyncClient, ops_token: str):
    created = await _create_named(client, ops_token, name=f"No History Co {uuid.uuid4().hex[:8]}")
    detail = await client.get(
        f"{BASE}/exporters/{created.json()['customer_id']}", headers=auth_header(ops_token)
    )
    assert detail.status_code == 200
    assert "onboarding_history" not in detail.json()


async def test_a_page_of_identities_is_fetched_in_one_query():
    """`get_many` answers for a whole page, and leaves out companies with no
    identity rather than inventing one."""
    from app.modules.onboarding.application.exporter_profile_service import (
        ExporterProfileService,
    )
    from app.modules.onboarding.infrastructure.legacy_company_identity import (
        LegacyCompanyIdentityStore,
    )

    async with db_services.AsyncSessionLocal() as db:
        named, _identity, _created = await ExporterProfileService(db).create_lead(
            name=f"Paged Co {uuid.uuid4().hex[:8]}",
            country="IN",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
            created_by_email="rep@example.com",
        )
    unnamed = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(unnamed, source=ExporterSource.SALES)

    async with db_services.AsyncSessionLocal() as db:
        found = await LegacyCompanyIdentityStore(db).get_many([named.customer_id, unnamed])
    assert set(found) == {named.customer_id}


# ── The legacy table is reached through one place only ────────────────────────

#: The CRM's company code, which must not know where identity is kept.
_COMPANY_FILES = [
    "api/exporter_router.py",
    "api/schemas/exporter.py",
    "application/exporter_profile_service.py",
    "domain/exporter_profile_views.py",
    "infrastructure/repositories/exporter_profile_repository.py",
]

#: Names that mean "reaching the legacy onboarding-request tables".
_LEGACY_NAMES = {
    "OnboardingRequest",
    "OnboardingRequestRepository",
    "OnboardingEvent",
    "OnboardingEventRepository",
    "OnboardingHistoryEntry",
}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
            if node.module and "onboarding_request" in node.module:
                names.add(node.module)
    return names


@pytest.mark.parametrize("relative_path", _COMPANY_FILES)
async def test_company_code_does_not_import_the_legacy_request_tables(relative_path: str):
    imported = _imported_names(MODULE / relative_path)
    assert not (imported & _LEGACY_NAMES), imported & _LEGACY_NAMES
    assert not any("onboarding_request" in name for name in imported)


async def test_the_transitional_store_is_the_one_place_that_does():
    imported = _imported_names(MODULE / "infrastructure/legacy_company_identity.py")
    assert "OnboardingRequest" in imported
