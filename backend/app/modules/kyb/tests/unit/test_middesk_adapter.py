"""
Unit tests for Middesk vendor adapter implementing canonical KYBAdapter interface.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.identity_providers.middesk.client import MiddeskClient
from app.modules.kyb.domain.ports import KYBAdapter, get_adapter
from app.modules.kyb.infrastructure.adapters.middesk_adapter import (
    MiddeskAdapter,
)
from app.platform.configuration.config import Settings
from app.platform.security.vault import VaultClient
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import (
    KYBVendorProcessingMode,
    NormalisedResult,
    VendorHealthStatusEnum,
)
from app.shared.exceptions import (
    AnerBaseException,
    ProviderNotEnabledError,
    UnauthorizedError,
    UnsupportedCountryError,
)


@pytest.fixture
def mock_vault_client():
    vault = MagicMock(spec=VaultClient)
    vault.get_middesk_credentials = AsyncMock(
        return_value="test_middesk_secret_key_123"
    )
    return vault


@pytest.fixture
def settings():
    return Settings(
        MIDDESK_ENABLED=True,
        MIDDESK_BASE_URL="https://api.middesk.com/v1",
        MIDDESK_WEBHOOK_SECRET="test_webhook_secret_key",
    )


@pytest.fixture
def adapter(settings, mock_vault_client):
    client = MiddeskClient(base_url=settings.MIDDESK_BASE_URL, vault_client=mock_vault_client)
    return MiddeskAdapter(client=client, settings=settings, vault_client=mock_vault_client)


# ── Acceptance Criterion 1 & Capabilities ───────────────────────────────────

def test_ac1_capabilities_declaration(adapter):
    """
    AC1 & KYBAdapter port: Adapter declares US support and supported entity types.
    """
    caps = adapter.declare_capabilities()
    assert isinstance(caps, KYBVendorCapabilityDeclaration)
    assert caps.vendor_id == "middesk"
    assert caps.vendor_name == "Middesk"
    assert "US" in caps.supported_countries
    assert "llc" in caps.supported_entity_types
    assert caps.processing_mode == KYBVendorProcessingMode.ASYNCHRONOUS


def test_ac1_verify_entity_us_corporation(adapter):
    """
    AC1: verify_entity submits entity for verification to Middesk API.
    """
    req = EntityVerificationRequest(
        legal_name="Acme Technologies Inc",
        trading_name="Acme Tech",
        registration_country="US",
        registration_number="C1234567",
        registered_address="100 Market St, San Francisco, CA 94105",
        tax_identification_number="12-3456789",
    )

    mock_response = {
        "id": "busi_us_corp_123",
        "name": "Acme Technologies Inc",
        "status": "in_review",
        "registration_status": "active",
        "findings": [],
    }

    with patch.object(adapter.client, "create_business", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = adapter.verify_entity(req)

        assert isinstance(result, KYBVerificationResult)
        assert result.vendor_id == "middesk"
        assert result.vendor_reference == "busi_us_corp_123"
        assert result.normalised_result == NormalisedResult.PENDING
        assert result.verified_legal_name == "Acme Technologies Inc"

        mock_create.assert_called_once_with(
            {
                "name": "Acme Technologies Inc",
                "registration_number": "C1234567",
                "registration_country": "US",
                "address": "100 Market St, San Francisco, CA 94105",
                "trading_name": "Acme Tech",
                "tin": "12-3456789",
            }
        )


def test_verify_entity_unsupported_country(adapter):
    """
    verify_entity rejects non-US registration country with UnsupportedCountryError.
    """
    req = EntityVerificationRequest(
        legal_name="London Global Ltd",
        registration_country="GB",
        registration_number="UK9999",
        registered_address="10 Downing St, London",
    )
    with pytest.raises(UnsupportedCountryError):
        adapter.verify_entity(req)


# ── Acceptance Criterion 2 ───────────────────────────────────────────────────

def test_ac2_async_get_verification_status(adapter):
    """
    AC2: get_verification_status polls for previously submitted verification and maps verified details.
    """
    mock_response = {
        "id": "busi_us_corp_123",
        "name": "Acme Technologies Inc",
        "status": "completed",
        "registration_status": "active",
        "registration_number": "C1234567",
        "address": {"line1": "100 Market St", "city": "San Francisco", "state": "CA", "postal_code": "94105"},
        "findings": [],
    }

    with patch.object(adapter.client, "get_business", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = adapter.get_verification_status("busi_us_corp_123")

        assert result.vendor_reference == "busi_us_corp_123"
        assert result.normalised_result == NormalisedResult.VERIFIED
        assert result.verified_legal_name == "Acme Technologies Inc"
        assert result.verified_registration_number == "C1234567"
        assert result.verified_address == "100 Market St, San Francisco, CA, 94105"
        mock_get.assert_called_once_with("busi_us_corp_123")


# ── Acceptance Criterion 3 ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status,reg_status,findings,expected",
    [
        ("completed", "active", [], NormalisedResult.VERIFIED),
        ("completed", "good_standing", [], NormalisedResult.VERIFIED),
        ("in_review", "active", [], NormalisedResult.PENDING),
        ("not_found", "not_found", [], NormalisedResult.NOT_FOUND),
        ("dissolved", "dissolved", [], NormalisedResult.REJECTED),
        ("completed", "inactive", [], NormalisedResult.REQUIRES_MANUAL_REVIEW),
        ("completed", "active", [{"type": "tax_lien", "description": "Tax lien found"}], NormalisedResult.REQUIRES_MANUAL_REVIEW),
    ],
)
def test_ac3_status_translation_table(adapter, status, reg_status, findings, expected):
    """
    AC3: Status and finding translation table accurately maps to canonical NormalisedResult.
    """
    mock_response = {
        "id": "busi_test_status",
        "name": "Status Test LLC",
        "status": status,
        "registration_status": reg_status,
        "findings": findings,
    }

    with patch.object(adapter.client, "get_business", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = adapter.get_verification_status("busi_test_status")
        assert result.normalised_result == expected


# ── Acceptance Criterion 4 & Webhook Signature Verification ─────────────────

def test_ac4_parse_webhook(adapter):
    """
    AC4: Webhook processing verifies HMAC signature and parses verified legal name, reg number, address.
    """
    payload = {
        "event": "business.updated",
        "data": {
            "object": {
                "id": "busi_webhook_789",
                "name": "Webhook Corp",
                "status": "completed",
                "registration_status": "active",
                "registration_number": "C999888",
                "address": "500 Howard St, San Francisco, CA 94105",
            }
        },
    }

    payload_str = json.dumps(payload, separators=(",", ":"))
    timestamp = "1600000000"
    sig_hash = hmac.new(
        b"test_webhook_secret_key",
        f"{timestamp}.{payload_str}".encode(),
        hashlib.sha256,
    ).hexdigest()
    signature_header = f"t={timestamp},v1={sig_hash}"

    result = adapter.parse_webhook(payload, signature_header)
    assert result.vendor_reference == "busi_webhook_789"
    assert result.normalised_result == NormalisedResult.VERIFIED
    assert result.verified_legal_name == "Webhook Corp"
    assert result.verified_registration_number == "C999888"
    assert result.verified_address == "500 Howard St, San Francisco, CA 94105"


def test_parse_webhook_invalid_signature(adapter):
    """
    parse_webhook raises UnauthorizedError when signature is missing or invalid.
    """
    payload = {"event": "business.updated", "id": "busi_fake"}

    with pytest.raises(UnauthorizedError):
        adapter.parse_webhook(payload, "t=1600000000,v1=bad_sig")

    with pytest.raises(UnauthorizedError):
        adapter.parse_webhook(payload, None)


# ── Acceptance Criterion 5 ───────────────────────────────────────────────────

def test_ac5_vault_credential_integration(adapter, mock_vault_client):
    """
    AC5: Vault integration — API credentials retrieved dynamically from Vault.
    """
    mock_response = {"id": "busi_vault_1", "status": "in_review", "registration_status": "active"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, json=mock_response)

        req = EntityVerificationRequest(
            legal_name="Vault LLC",
            registration_country="US",
            registration_number="V123",
            registered_address="Address 1",
        )
        adapter.verify_entity(req)

        mock_vault_client.get_middesk_credentials.assert_called()


# ── Acceptance Criterion 6 ───────────────────────────────────────────────────

def test_ac6_rate_limit_handling_retries_with_backoff(adapter):
    """
    AC6: Rate limit handling retries with backoff on HTTP 429.
    """
    response_429 = httpx.Response(429, text="Rate limit exceeded")

    with patch("httpx.AsyncClient.request", return_value=response_429), \
          patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        with pytest.raises(AnerBaseException):
            req = EntityVerificationRequest(
                legal_name="RateLimited LLC",
                registration_country="US",
                registration_number="RL123",
                registered_address="Address 1",
            )
            adapter.verify_entity(req)

        assert mock_sleep.call_count >= 1


# ── MIDDESK_ENABLED Flag ───────────────────────────────────────────────────

def test_middesk_disabled_flag(mock_vault_client):
    """
    When MIDDESK_ENABLED is False, adapter operations raise ProviderNotEnabledError.
    """
    disabled_settings = Settings(MIDDESK_ENABLED=False)
    client = MiddeskClient(base_url="https://api.middesk.com/v1", vault_client=mock_vault_client)
    adapter = MiddeskAdapter(client=client, settings=disabled_settings, vault_client=mock_vault_client)

    req = EntityVerificationRequest(
        legal_name="Disabled LLC",
        registration_country="US",
        registration_number="D123",
        registered_address="Address 1",
    )
    with pytest.raises(ProviderNotEnabledError):
        adapter.verify_entity(req)


# ── Health Check & Registry Conformance ─────────────────────────────────────

def test_get_vendor_health_healthy(adapter):
    """
    KYBAdapter port requirement: get_vendor_health performs health check and reports HEALTHY on 200.
    """
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json={})

        health = adapter.get_vendor_health()
        assert isinstance(health, VendorHealthStatus)
        assert health.status == VendorHealthStatusEnum.HEALTHY
        assert health.response_time_ms >= 0


def test_get_vendor_health_down_on_missing_key(adapter, mock_vault_client):
    """
    get_vendor_health reports DOWN when Vault returns empty API key.
    """
    mock_vault_client.get_middesk_credentials.return_value = ""

    health = adapter.get_vendor_health()
    assert health.status == VendorHealthStatusEnum.DOWN
    assert "missing" in (health.known_issues or "").lower()


def test_get_vendor_health_down_on_auth_failure(adapter):
    """
    get_vendor_health reports DOWN on 401 Unauthorized from Middesk API.
    """
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(401, text="Unauthorized")

        health = adapter.get_vendor_health()
        assert health.status == VendorHealthStatusEnum.DOWN
        assert "unauthorized" in (health.known_issues or "").lower()


def test_middesk_adapter_conforms_to_kyb_adapter_registry():
    """
    KYBAdapter port requirement: MiddeskAdapter satisfies KYBAdapter interface and registers under 'middesk'.
    """
    adapter = MiddeskAdapter()
    assert isinstance(adapter, KYBAdapter)

    registered_cls = get_adapter("middesk")
    assert registered_cls is MiddeskAdapter

