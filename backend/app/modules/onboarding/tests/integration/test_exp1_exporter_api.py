"""API-level tests for the Exporter CRM routes (EXP-1), mounted at
`/api/v1/onboarding/exporters...`.

Follows `test_case_model.py`'s auth-token helper and `client` fixture
conventions.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _api_token(client: AsyncClient) -> str:
    email = f"exp1-{uuid.uuid4().hex[:8]}@aner-test.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password1", "role": "API_USER"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password1"}
    )
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_create_exporter_profile_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/onboarding/exporters", json={"source": "SALES"}
    )
    assert resp.status_code == 401


async def test_get_exporter_profile_requires_auth(client: AsyncClient):
    resp = await client.get(f"/api/v1/onboarding/exporters/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_search_exporter_profiles_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/onboarding/exporters")
    assert resp.status_code == 401


async def test_add_contact_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/onboarding/exporters/{uuid.uuid4()}/contacts", json={"name": "Jane"}
    )
    assert resp.status_code == 401


async def test_log_activity_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/onboarding/exporters/{uuid.uuid4()}/activities",
        json={"activity_type": "CALL", "subject": "x"},
    )
    assert resp.status_code == 401


# ── End-to-end flow ────────────────────────────────────────────────────────────


async def test_full_exporter_profile_flow(client: AsyncClient):
    token = await _api_token(client)

    create_resp = await client.post(
        "/api/v1/onboarding/exporters",
        json={"source": "SALES", "industry": "Textiles"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    customer_id = body["customer_id"]
    assert body["source"] == "SALES"
    assert body["lifecycle_status"] == "LEAD"

    # Repeat create for the same customer_id (no Idempotency-Key) returns the
    # existing profile rather than erroring.
    replay_resp = await client.post(
        "/api/v1/onboarding/exporters",
        json={"customer_id": customer_id, "source": "MANUAL"},
        headers=_auth(token),
    )
    assert replay_resp.status_code == 201  # service returns created=False; router doesn't remap status
    assert replay_resp.json()["source"] == "SALES"

    # Add a primary contact.
    contact_resp = await client.post(
        f"/api/v1/onboarding/exporters/{customer_id}/contacts",
        json={"name": "Jane Doe", "role": "CFO", "is_primary": True},
        headers=_auth(token),
    )
    assert contact_resp.status_code == 201
    assert contact_resp.json()["is_primary_contact"] is True

    # A second primary demotes the first.
    contact2_resp = await client.post(
        f"/api/v1/onboarding/exporters/{customer_id}/contacts",
        json={"name": "John Smith", "is_primary": True},
        headers=_auth(token),
    )
    assert contact2_resp.status_code == 201

    contacts_resp = await client.get(
        f"/api/v1/onboarding/exporters/{customer_id}/contacts", headers=_auth(token)
    )
    contacts = contacts_resp.json()["contacts"]
    primaries = [c for c in contacts if c["is_primary_contact"]]
    assert len(primaries) == 1
    assert primaries[0]["name"] == "John Smith"

    # Log an activity.
    activity_resp = await client.post(
        f"/api/v1/onboarding/exporters/{customer_id}/activities",
        json={"activity_type": "CALL", "subject": "Intro call"},
        headers=_auth(token),
    )
    assert activity_resp.status_code == 201

    activities_resp = await client.get(
        f"/api/v1/onboarding/exporters/{customer_id}/activities", headers=_auth(token)
    )
    assert len(activities_resp.json()["activities"]) == 1

    # Update a mutable field.
    update_resp = await client.patch(
        f"/api/v1/onboarding/exporters/{customer_id}",
        json={"industry": "Agriculture"},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["industry"] == "Agriculture"

    # Detail view aggregates everything.
    detail_resp = await client.get(
        f"/api/v1/onboarding/exporters/{customer_id}", headers=_auth(token)
    )
    detail = detail_resp.json()
    assert detail["customer_id"] == customer_id
    assert len(detail["contacts"]) == 2
    assert len(detail["recent_activities"]) == 1

    # Valid lifecycle transition.
    transition_resp = await client.post(
        f"/api/v1/onboarding/exporters/{customer_id}/transition",
        json={"to_status": "CONTACTED"},
        headers=_auth(token),
    )
    assert transition_resp.status_code == 200
    assert transition_resp.json()["lifecycle_status"] == "CONTACTED"

    # Invalid lifecycle transition (skipping straight to ACTIVE) is rejected.
    invalid_transition_resp = await client.post(
        f"/api/v1/onboarding/exporters/{customer_id}/transition",
        json={"to_status": "ACTIVE"},
        headers=_auth(token),
    )
    assert invalid_transition_resp.status_code == 409

    # source is not updatable via PATCH — rejected at the schema boundary.
    reject_source_resp = await client.patch(
        f"/api/v1/onboarding/exporters/{customer_id}",
        json={"source": "MANUAL"},
        headers=_auth(token),
    )
    assert reject_source_resp.status_code == 422

    # Search by gstin after setting one via update.
    await client.patch(
        f"/api/v1/onboarding/exporters/{customer_id}",
        json={"gstin": "27AAAPL9999C1ZV"},
        headers=_auth(token),
    )
    search_resp = await client.get(
        "/api/v1/onboarding/exporters",
        params={"gstin": "27AAAPL9999C1ZV"},
        headers=_auth(token),
    )
    assert search_resp.status_code == 200
    profiles = search_resp.json()["profiles"]
    assert any(p["customer_id"] == customer_id for p in profiles)


async def test_get_exporter_profile_not_found_returns_404(client: AsyncClient):
    token = await _api_token(client)
    resp = await client.get(
        f"/api/v1/onboarding/exporters/{uuid.uuid4()}", headers=_auth(token)
    )
    assert resp.status_code == 404
