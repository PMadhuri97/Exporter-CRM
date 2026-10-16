"""Sorting the Companies list (``domain/list_sort.py``).

The list is paged on the server, so the order is the server's: by when the company
record last changed (the default, newest first), by name, or by stage. Each test makes
its own three companies under one unique name and searches for that name, so the shared
test database's other companies never enter the comparison.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


async def _set(customer_id: uuid.UUID, **values) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile).where(ExporterProfile.customer_id == customer_id).values(**values)
        )
        await db.commit()


@pytest.fixture
async def three(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Three companies sharing a unique tag: names in mixed case, one at each stage, and
    last updated an hour apart — in an order that matches none of the other two."""
    tag = f"Sortco{uuid.uuid4().hex[:8]}"
    base = datetime.now(UTC) - timedelta(days=1)
    made: dict[str, str] = {}
    for label, name, journey, hours in [
        ("bravo", f"{tag} Bravo", ExporterJourney.LEAD, 2),
        ("alpha", f"{tag} alpha", ExporterJourney.CUSTOMER, 0),
        ("charlie", f"{tag} Charlie", ExporterJourney.PROSPECT, 1),
    ]:
        company_id = await make_company()
        await _set(company_id, name=name, journey=journey, updated_at=base + timedelta(hours=hours))
        made[label] = str(company_id)
    return tag, made


async def _listed(client: AsyncClient, tag: str, **params) -> list[str]:
    token = await token_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(BASE, params={"name": tag, **params}, headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return [row["customer_id"] for row in resp.json()["profiles"]]


async def test_the_default_is_the_most_recently_updated_first(client: AsyncClient, three):
    tag, c = three
    assert await _listed(client, tag) == [c["bravo"], c["charlie"], c["alpha"]]
    assert await _listed(client, tag, sort="updated_at", order="asc") == [
        c["alpha"], c["charlie"], c["bravo"],
    ]


async def test_by_name_ignores_case(client: AsyncClient, three):
    tag, c = three
    assert await _listed(client, tag, sort="name", order="asc") == [
        c["alpha"], c["bravo"], c["charlie"],
    ]
    assert await _listed(client, tag, sort="name", order="desc") == [
        c["charlie"], c["bravo"], c["alpha"],
    ]


async def test_by_stage_follows_the_journey_not_the_alphabet(client: AsyncClient, three):
    tag, c = three
    # Lead, Prospect, Customer — alphabetically it would be Customer, Lead, Prospect.
    assert await _listed(client, tag, sort="stage", order="asc") == [
        c["bravo"], c["charlie"], c["alpha"],
    ]
    assert await _listed(client, tag, sort="stage", order="desc") == [
        c["alpha"], c["charlie"], c["bravo"],
    ]


async def test_an_edit_brings_a_company_to_the_top(client: AsyncClient, three):
    """`updated_at` moves on every change to the record, so the company worked on today
    leads the default list."""
    tag, c = three
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == uuid.UUID(c["alpha"]))
        )
        profile.industry = "Textiles"
        await db.commit()
        await db.refresh(profile)
    assert profile.updated_at > datetime.now(UTC) - timedelta(minutes=5)
    assert (await _listed(client, tag))[0] == c["alpha"]


async def test_pages_of_one_add_up_to_the_whole_list(client: AsyncClient, three):
    """However the list is sorted, paging through it neither repeats nor skips."""
    tag, _ = three
    for sort in ("updated_at", "name", "stage"):
        whole = await _listed(client, tag, sort=sort)
        paged = [
            row
            for offset in range(len(whole))
            for row in await _listed(client, tag, sort=sort, limit=1, offset=offset)
        ]
        assert paged == whole, sort


@pytest.mark.parametrize("params", [{"sort": "created"}, {"order": "up"}])
async def test_an_unknown_sort_is_refused(client: AsyncClient, params: dict):
    token = await token_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(BASE, params=params, headers=auth_header(token))
    assert resp.status_code == 422, resp.text
