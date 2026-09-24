"""API-level tests for the document requirements route (B2), mounted at
`/api/v1/onboarding/document-requirements`.

Follows `test_exp1_exporter_api.py`'s auth-token helper and `client` fixture
conventions.

These assert against the real GitOps policy file rather than a fixture, on
purpose: the endpoint's whole job is to expose *that* file, and a test that
substituted its own config would pass while the deployed policy was unreachable
or malformed.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import token_with_role
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

_PATH = "/api/v1/onboarding/document-requirements"

#: The combination the policy's `IN_CORP_DNFBP_US_IN` profile matches, plus a
#: volume over the `HIGH_VOLUME_BANK_STATEMENT` rule's threshold.
_INDIAN_DNFBP_CORP = {
    "entity_type": "CORPORATION",
    "registration_country": "IN",
    "sector_code": "DNFBP",
    "corridor_intent": "US-IN",
    "declared_monthly_volume_usd": 750000,
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──────────────────────────────────────────────────────────────────────


async def test_requires_auth(client: AsyncClient):
    resp = await client.get(
        _PATH, params={"entity_type": "CORPORATION", "registration_country": "IN"}
    )
    assert resp.status_code == 401


async def test_api_user_is_refused(client: AsyncClient):
    """This is an internal surface. External callers get the `gateway`, which is
    deliberately paused — they must not reach compliance policy through here."""
    token = await token_with_role(client, UserRole.API_USER)
    resp = await client.get(
        _PATH,
        params={"entity_type": "CORPORATION", "registration_country": "IN"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "role",
    [UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER],
)
async def test_every_internal_staff_role_may_read(client: AsyncClient, role: UserRole):
    """Including DEVELOPER, which is masked out of PII elsewhere in this module.
    A list of document *type names* is version-controlled configuration, not
    customer data, so the PII gate would be gating the wrong thing."""
    token = await token_with_role(client, role)
    resp = await client.get(
        _PATH,
        params={"entity_type": "CORPORATION", "registration_country": "IN"},
        headers=_auth(token),
    )
    assert resp.status_code == 200


# ── The policy answer ─────────────────────────────────────────────────────────


async def test_returns_the_profile_documents_and_the_conditional_ones(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(_PATH, params=_INDIAN_DNFBP_CORP, headers=_auth(token))
    assert resp.status_code == 200

    body = resp.json()
    types = [d["document_type"] for d in body["required_documents"]]

    # From the matched profile.
    assert "certificate_of_incorporation" in types
    assert "ubo_declaration" in types
    # From the two conditional rules this input fires.
    assert "bank_statement" in types  # volume over threshold
    assert "source_of_funds_declaration" in types  # DNFBP sector
    assert body["total"] == len(types)
    assert body["policy_version"]


async def test_reports_each_document_validity_window(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(_PATH, params=_INDIAN_DNFBP_CORP, headers=_auth(token))

    by_type = {d["document_type"]: d for d in resp.json()["required_documents"]}
    # `null` means accepted regardless of age — the same reading
    # `validate_document_age` takes for a type with no configured rule.
    assert by_type["certificate_of_incorporation"]["max_age_days"] is None
    assert by_type["proof_of_registered_address"]["max_age_days"] == 90
    assert by_type["latest_audited_accounts"]["max_age_days"] == 365


async def test_a_lower_volume_drops_the_conditional_bank_statement(
    client: AsyncClient,
):
    """Proves the answer is the policy's, not a fixed list."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(
        _PATH,
        params={**_INDIAN_DNFBP_CORP, "declared_monthly_volume_usd": 1000},
        headers=_auth(token),
    )

    types = [d["document_type"] for d in resp.json()["required_documents"]]
    assert "bank_statement" not in types
    assert "certificate_of_incorporation" in types


async def test_an_unmatched_profile_returns_an_empty_list_not_an_error(
    client: AsyncClient,
):
    """No matching profile is a configuration answer, not a failure."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(
        _PATH,
        params={"entity_type": "TRUST", "registration_country": "SG"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["required_documents"] == []
    assert resp.json()["total"] == 0


async def test_registration_country_must_be_alpha_2(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(
        _PATH,
        params={"entity_type": "CORPORATION", "registration_country": "INDIA"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_the_route_is_read_only(client: AsyncClient):
    """No document storage exists yet, so nothing here may accept one."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    for method in ("post", "put", "patch", "delete"):
        resp = await getattr(client, method)(_PATH, headers=_auth(token))
        # 404 or 405 both mean "not routed" — which of the two Starlette picks
        # depends on how the path resolves under the router prefix, and is not
        # the thing being asserted. What matters is that no write reaches a
        # handler.
        assert resp.status_code in (404, 405), (
            f"{method.upper()} returned {resp.status_code}; it should not be routed"
        )
