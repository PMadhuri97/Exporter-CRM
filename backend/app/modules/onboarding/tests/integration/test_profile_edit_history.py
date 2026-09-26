"""L2-07 — every edit of a company field leaves a history row.

What these prove:

* A field left out of an edit is unchanged; a field sent as null (or empty)
  is cleared. The two are different requests with different results.
* Each field whose value changes writes exactly one ``profile`` row through
  the shared ``HistoryService``; an unchanged field writes none.
* The actor is the signed-in user, never anything the body says.
* The field change and its history row commit together or not at all.
* Tax identifiers are masked in the row, because the history read route shows
  a row's details to roles that only ever see them masked.
* There is still exactly one history table and one writer.

Real Postgres, each test minting its own ids, like the rest of this package.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.exporter_profile_service import (
    HISTORY_DIMENSION_PROFILE,
    PROFILE_EDIT_EVENT,
    ExporterProfileService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.platform.database.models import Base
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
MODULE = Path(__file__).resolve().parents[2]


async def _company(**fields) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, **fields
        )
    return customer_id


async def _profile_rows(customer_id: uuid.UUID) -> list[ExporterLifecycleHistory]:
    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_PROFILE, limit=100
        )
    return list(rows)


async def _current(customer_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await ExporterProfileService(db)._require_profile(customer_id)


# ── Omitted versus cleared ────────────────────────────────────────────────────


async def test_an_omitted_field_is_unchanged_and_records_nothing():
    customer_id = await _company(industry="Textiles", website="https://acme.example")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"industry": "Leather"}, actor_id="rm-1"
        )

    profile = await _current(customer_id)
    assert profile.industry == "Leather"
    assert profile.website == "https://acme.example"  # left out, left alone
    assert [r.to_status for r in await _profile_rows(customer_id)] == ["industry"]


@pytest.mark.parametrize("cleared", [None, "", "   "])
async def test_a_field_sent_empty_is_cleared(cleared):
    customer_id = await _company(website="https://acme.example")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"website": cleared}, actor_id="rm-1"
        )

    assert (await _current(customer_id)).website is None
    [row] = await _profile_rows(customer_id)
    assert row.event_metadata["field"] == "website"
    assert row.event_metadata["from"] == "https://acme.example"
    assert row.event_metadata["to"] is None


async def test_an_empty_list_clears_a_list_field():
    customer_id = await _company(export_markets=["AE", "US"])
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"export_markets": []}, actor_id="rm-1"
        )
    assert (await _current(customer_id)).export_markets is None
    [row] = await _profile_rows(customer_id)
    assert row.event_metadata["from"] == ["AE", "US"]


async def test_setting_a_field_that_was_empty_is_recorded():
    customer_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"year_established": 1998}, actor_id="rm-1"
        )
    [row] = await _profile_rows(customer_id)
    assert (row.event_metadata["from"], row.event_metadata["to"]) == (None, 1998)


# ── Exactly the expected rows ─────────────────────────────────────────────────


async def test_one_row_per_changed_field_sharing_one_edit_id():
    customer_id = await _company(industry="Textiles", relationship_manager="Asha")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id,
            {
                "industry": "Leather",  # changes
                "relationship_manager": "Asha",  # same value: no row
                "website": "https://new.example",  # was empty: changes
            },
            actor_id="rm-7",
        )

    rows = await _profile_rows(customer_id)
    assert sorted(r.to_status for r in rows) == ["industry", "website"]
    for row in rows:
        assert row.dimension == HISTORY_DIMENSION_PROFILE
        assert row.event_type == PROFILE_EDIT_EVENT
        assert row.from_status is None
        assert row.to_status == row.event_metadata["field"]
        assert row.actor_id == "rm-7"
        assert row.event_metadata["source"] == "exporter_profile_service.update_profile"
    assert len({r.event_metadata["edit_id"] for r in rows}) == 1


async def test_an_edit_that_changes_nothing_records_nothing():
    customer_id = await _company(industry="Textiles")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"industry": "Textiles"}, actor_id="rm-1"
        )
    assert await _profile_rows(customer_id) == []


async def test_tax_identifiers_are_masked_in_the_row():
    customer_id = await _company(pan="AAAPL1234C")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            customer_id, {"pan": "BBBPL5678D"}, actor_id="rm-1"
        )

    assert (await _current(customer_id)).pan == "BBBPL5678D"  # stored in full
    [row] = await _profile_rows(customer_id)
    assert row.event_metadata["from"] == "••••••234C"
    assert row.event_metadata["to"] == "••••••678D"
    assert "AAAPL1234C" not in str(row.event_metadata)
    assert "BBBPL5678D" not in str(row.event_metadata)


# ── Refusals leave nothing behind ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "changes",
    [
        {"industry": "Leather", "lifecycle_status": "ACTIVE"},
        {"industry": "Leather", "name": "Renamed Co"},
        {"industry": "Leather", "not_a_field": 1},
    ],
)
async def test_a_refused_edit_changes_nothing(changes):
    customer_id = await _company(industry="Textiles")
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ExporterProfileService(db).update_profile(
                customer_id, changes, actor_id="rm-1"
            )
    assert (await _current(customer_id)).industry == "Textiles"
    assert await _profile_rows(customer_id) == []


async def test_state_and_history_commit_together_or_not_at_all(monkeypatch):
    """If writing the second field's history row fails, the first field's
    change and its row are rolled back with it."""
    customer_id = await _company(industry="Textiles", website="https://old.example")
    real_record = HistoryService.record
    calls = {"n": 0}

    async def failing_second_record(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("history write failed")
        return await real_record(self, *args, **kwargs)

    monkeypatch.setattr(HistoryService, "record", failing_second_record)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(RuntimeError):
            await ExporterProfileService(db).update_profile(
                customer_id,
                {"industry": "Leather", "website": "https://new.example"},
                actor_id="rm-1",
            )
    monkeypatch.undo()

    profile = await _current(customer_id)
    assert (profile.industry, profile.website) == ("Textiles", "https://old.example")
    assert await _profile_rows(customer_id) == []


# ── Through the API: the actor is the session's ───────────────────────────────


async def test_the_api_records_the_signed_in_user_as_the_actor(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _company(industry="Textiles")

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"industry": "Leather"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    [row] = await _profile_rows(customer_id)
    assert row.actor_id == str(user_id)


async def test_the_api_refuses_an_actor_in_the_body(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _company(industry="Textiles")

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"industry": "Leather", "actor_id": "someone-else"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422
    assert (await _current(customer_id)).industry == "Textiles"
    assert await _profile_rows(customer_id) == []


async def test_the_api_distinguishes_omitted_from_null(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _company(industry="Textiles", website="https://acme.example")

    omitted = await client.patch(
        f"{BASE}/exporters/{customer_id}", json={}, headers=auth_header(token)
    )
    assert omitted.status_code == 200
    assert omitted.json()["website"] == "https://acme.example"

    cleared = await client.patch(
        f"{BASE}/exporters/{customer_id}", json={"website": None}, headers=auth_header(token)
    )
    assert cleared.status_code == 200
    assert cleared.json()["website"] is None
    assert cleared.json()["industry"] == "Textiles"
    assert [r.to_status for r in await _profile_rows(customer_id)] == ["website"]


# ── One history table, one writer ─────────────────────────────────────────────


async def test_there_is_still_one_history_table():
    history_tables = {
        table.name
        for table in Base.metadata.sorted_tables
        if table.schema == "onboarding" and "history" in table.name
    }
    assert history_tables == {"exporter_lifecycle_history"}


async def test_the_profile_service_writes_history_only_through_the_shared_writer():
    tree = ast.parse(
        (MODULE / "application/exporter_profile_service.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "HistoryService" in imported
    assert "ExporterLifecycleHistory" not in imported
    assert "ExporterLifecycleHistoryRepository" not in imported


async def test_the_shared_writer_still_never_commits():
    tree = ast.parse(
        (MODULE / "application/history_service.py").read_text(encoding="utf-8")
    )
    commits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "commit"
    ]
    assert commits == []
