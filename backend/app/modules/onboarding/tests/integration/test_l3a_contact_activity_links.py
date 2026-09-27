"""Contacts and activities point at a real company (L3-02, §9.3 E16).

L3-02 reads as new work in the plan, but the constraints already exist: migration
0014 created ``fk_exporter_contact_customer_id`` and
``fk_exporter_activity_customer_id`` (its ``_LINKED`` tuple, step 4). What was
actually missing is here:

* the ORM entities documented ``customer_id`` as "a bare, indexed UUID with no
  formal FK", which was false — corrected, and asserted below against the
  database catalogue so the two cannot drift again;
* no test proved the *database* refuses a child row for a company that does not
  exist;
* the API returned a 500 for that case, because an ``IntegrityError`` escaping a
  request handler is not a domain error.

Migration 0016 deliberately adds **no** DDL for any of this. That is the point of
checking 0014 first, and this file is where the check is written down.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import inspect

from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"

#: table -> (constraint name, an INSERT of a child row taking (id, customer_id))
_CHILDREN = {
    "exporter_contact": (
        "fk_exporter_contact_customer_id",
        "INSERT INTO onboarding.exporter_contact (id, customer_id, name) "
        "VALUES (%s, %s, 'Ghost')",
    ),
    "exporter_activity": (
        "fk_exporter_activity_customer_id",
        "INSERT INTO onboarding.exporter_activity "
        "(id, customer_id, activity_type, subject, actor_id, occurred_at) "
        "VALUES (%s, %s, 'CALL', 'Ghost call', 'tester', now())",
    ),
}


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


@pytest.fixture(scope="module")
async def token(client: AsyncClient) -> str:
    return await token_with_role(client, UserRole.OPERATIONS)


# ── The ORM says what the database says ──────────────────────────────────────


@pytest.mark.parametrize(
    ("entity", "table"),
    [(ExporterContact, "exporter_contact"), (ExporterActivity, "exporter_activity")],
)
async def test_the_entity_declares_the_foreign_key_the_database_has(entity, table):
    """The specific drift L3-02 exists to close.

    Both entities' docstrings claimed there was no foreign key, on reasoning that
    stopped applying when the company record became the CRM's own table. Asserting
    the mapper against `pg_constraint` means a future edit cannot quietly restore
    the false version.
    """
    constraint_name, _ = _CHILDREN[table]
    [fk] = list(inspect(entity).local_table.c.customer_id.foreign_keys)
    assert fk.column.table.fullname == "onboarding.exporter_profile"
    assert fk.column.name == "customer_id"
    assert fk.ondelete == "RESTRICT"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT confdeltype FROM pg_constraint WHERE conname = %s "
                "AND conrelid = %s::regclass",
                (constraint_name, f"onboarding.{table}"),
            )
            row = cur.fetchone()
        assert row is not None, f"{constraint_name} is missing from the database"
        assert row[0] == "r", "ON DELETE RESTRICT"  # 'r' = RESTRICT
    finally:
        conn.close()


async def test_0016_does_not_re_add_what_0014_already_created():
    """§7.1: "Do not re-add the constraint in 0016."

    One constraint per column pair, not two. A duplicate would refuse nothing extra
    and would make 0016's downgrade drop a constraint 0014 owns.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for table, _ in _CHILDREN.items():
                cur.execute(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conrelid = %s::regclass AND contype = 'f' "
                    "AND conkey = ARRAY[(SELECT attnum FROM pg_attribute "
                    "  WHERE attrelid = %s::regclass AND attname = 'customer_id')]::smallint[]",
                    (f"onboarding.{table}", f"onboarding.{table}"),
                )
                assert cur.fetchone()[0] == 1, table
    finally:
        conn.close()


# ── Direct SQL: the database refuses a ghost company ─────────────────────────


@pytest.mark.parametrize("table", sorted(_CHILDREN))
async def test_the_database_refuses_a_child_row_for_a_company_that_does_not_exist(table):
    """The direct-SQL violation test the migration register §2 requires: it
    bypasses the ORM entirely, so it proves the *database* refuses the row and not
    just the service."""
    _, statement = _CHILDREN[table]
    conn = _connect()
    try:
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(statement, (str(uuid.uuid4()), str(uuid.uuid4())))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("table", sorted(_CHILDREN))
async def test_the_database_accepts_a_child_row_for_a_real_company(table):
    """The constraint refuses the wrong row and nothing else."""
    _, statement = _CHILDREN[table]
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(statement, (str(uuid.uuid4()), str(company_id)))
            assert cur.rowcount == 1
    finally:
        conn.rollback()
        conn.close()


# ── The service and the API return a clean error, not a 500 ──────────────────


async def test_the_service_refuses_a_contact_for_a_company_that_does_not_exist():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterContactActivityService(db).add_contact(uuid.uuid4(), name="Ghost")


async def test_the_service_refuses_an_activity_for_a_company_that_does_not_exist():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterContactActivityService(db).log_activity(
                uuid.uuid4(),
                activity_type=ExporterActivityType.CALL,
                subject="Ghost call",
                actor_id="tester",
            )


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("contacts", {"name": "Ghost"}),
        ("activities", {"activity_type": "CALL", "subject": "Ghost call"}),
    ],
)
async def test_the_api_returns_404_not_500_for_a_ghost_company(
    client: AsyncClient, token, path, body
):
    """What L3-02 actually asks for: "a service-level test that the API returns a
    clean error rather than a 500". The foreign key is the authority; this is the
    error message."""
    resp = await client.post(
        f"{BASE}/exporters/{uuid.uuid4()}/{path}",
        json=body,
        headers=auth_header(token),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "EXPORTER_PROFILE_NOT_FOUND"


async def test_a_refused_contact_does_not_demote_an_existing_primary():
    """The ordering the guard buys.

    `add_contact` demotes any existing primary before inserting the new one. If the
    company check ran after that demotion, a write refused for a company that does
    not exist would still have left that company — a different one, reached by a
    mistyped id — with no primary contact. So the check is first, and this is what
    says so.
    """
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterContactActivityService(db).add_contact(
            company_id, name="Priya Nair", is_primary=True
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterContactActivityService(db).add_contact(
                uuid.uuid4(), name="Ghost", is_primary=True
            )
    async with db_services.AsyncSessionLocal() as db:
        contacts = await ExporterContactActivityService(db).list_contacts(company_id)
    assert [c.is_primary_contact for c in contacts] == [True]


async def test_a_company_with_contacts_or_activities_cannot_be_deleted():
    """`ON DELETE RESTRICT` both ways. An activity is append-only — the record of
    what happened — so nothing may remove the company it happened to either."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            for _, statement in _CHILDREN.values():
                cur.execute(statement, (str(uuid.uuid4()), str(company_id)))
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute(
                    "DELETE FROM onboarding.exporter_profile WHERE customer_id = %s",
                    (str(company_id),),
                )
    finally:
        conn.rollback()
        conn.close()
