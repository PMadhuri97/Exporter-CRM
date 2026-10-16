"""A seller's deals have different references (migration ``onboarding_0059_deal_reference``).

The reference is how people tell a company's deals apart, so a second deal of one
seller with the same reference is refused — by the service with 409
``DEAL_REFERENCE_TAKEN``, and by ``uq_deal_company_reference`` for anything that goes
around it. Another seller may use the same words.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.exceptions import DealReferenceTakenError
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.modules.onboarding.tests.integration._verification_support import BASE, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


async def _open(company_id: uuid.UUID, reference: str):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).open_deal(company_id, reference=reference, actor_id="t")


async def test_a_seller_cannot_open_two_deals_with_one_reference():
    company_id = await make_prospect()
    await _open(company_id, "Rotterdam shipment")

    with pytest.raises(DealReferenceTakenError) as refused:
        await _open(company_id, "  Rotterdam shipment ")
    assert refused.value.status_code == 409

    async with db_services.AsyncSessionLocal() as db:
        _deals, total = await DealService(db).list_for_company(company_id)
    assert total == 1


async def test_another_seller_may_use_the_same_reference():
    first, second = await make_prospect(), await make_prospect()
    await _open(first, "Hamburg order")
    assert (await _open(second, "Hamburg order")).reference == "Hamburg order"


async def test_the_api_answers_409_with_its_code(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await make_prospect()
    body = {"reference": "Dubai seafood order"}
    first = await client.post(
        f"{BASE}/exporters/{company_id}/deals", json=body, headers=auth_header(token)
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"{BASE}/exporters/{company_id}/deals", json=body, headers=auth_header(token)
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "DEAL_REFERENCE_TAKEN"


async def test_the_database_refuses_a_duplicate_reference():
    company_id = await make_prospect()
    await _open(company_id, "Direct SQL order")
    with pg() as cur, pytest.raises(
        psycopg2.errors.UniqueViolation, match="uq_deal_company_reference"
    ):
        cur.execute(
            "INSERT INTO onboarding.deal (company_id, reference, stage) "
            "VALUES (%s, 'Direct SQL order', 'OPEN')",
            (str(company_id),),
        )
