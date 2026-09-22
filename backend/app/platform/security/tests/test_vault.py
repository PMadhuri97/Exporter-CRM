"""
Unit tests for VaultClient security credential provider.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.platform.security.vault import VaultClient
from app.shared.exceptions import AnerBaseException


@pytest.mark.asyncio
async def test_vault_client_disabled_fallback(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("MIDDESK_API_KEY", "env_secret_key_999")

    client = VaultClient()
    assert not client._enabled

    key = await client.get_middesk_credentials()
    assert key == "env_secret_key_999"


@pytest.mark.asyncio
async def test_vault_client_kv_v2_success():
    client = VaultClient(vault_addr="http://vault.internal:8200", vault_token="test-token")
    assert client._enabled

    mock_resp_data = {
        "data": {
            "data": {
                "api_key": "vault_secret_key_123"
            }
        }
    }

    dummy_request = httpx.Request("GET", "http://vault.internal:8200/v1/secret/data/middesk")
    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_resp_data, request=dummy_request)

        secret = await client.get_secret("middesk")
        assert secret == {"api_key": "vault_secret_key_123"}

        key = await client.get_middesk_credentials()
        assert key == "vault_secret_key_123"


@pytest.mark.asyncio
async def test_vault_client_error_raises_when_enabled():
    """When Vault is enabled, fetch failures fail fast with AnerBaseException instead of degrading silently."""
    client = VaultClient(vault_addr="http://vault.internal:8200", vault_token="bad-token")

    dummy_request = httpx.Request("GET", "http://vault.internal:8200/v1/secret/data/middesk")
    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPStatusError("403 Forbidden", request=dummy_request, response=httpx.Response(403, request=dummy_request))

        with pytest.raises(AnerBaseException):
            await client.get_middesk_credentials()

