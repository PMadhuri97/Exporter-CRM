"""
Unit tests for MiddeskClient.

Verifies Vault API key retrieval, API calls, rate limit (HTTP 429) and 5xx retries
with exponential backoff, and 4xx fast-fail behavior.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.integrations.identity_providers.middesk.client import MiddeskClient
from app.platform.security.vault import VaultClient
from app.shared.exceptions import AnerBaseException


@pytest.fixture
def mock_vault_client():
    vault = AsyncMock(spec=VaultClient)
    vault.get_middesk_credentials.return_value = "secret_middesk_key_from_vault"
    return vault


@pytest.mark.asyncio
async def test_middesk_client_fetches_vault_credentials(mock_vault_client):
    client = MiddeskClient(
        base_url="https://api.middesk.mock",
        vault_client=mock_vault_client,
    )
    headers = await client._get_auth_headers()

    mock_vault_client.get_middesk_credentials.assert_called_once()
    assert headers["Authorization"] == "Bearer secret_middesk_key_from_vault"


@pytest.mark.asyncio
async def test_create_business_creates_business_object(mock_vault_client):
    client = MiddeskClient(
        base_url="https://api.middesk.mock",
        vault_client=mock_vault_client,
    )

    fake_response = httpx.Response(
        200,
        json={
            "id": "bus_12345",
            "name": "Acme Corp",
            "status": "pending",
            "tin": "12-3456789",
        },
    )

    with patch("httpx.AsyncClient.request", return_value=fake_response):
        data = await client.create_business({"name": "Acme Corp", "tin": "12-3456789"})
        assert data["id"] == "bus_12345"
        mock_vault_client.get_middesk_credentials.assert_called()


@pytest.mark.asyncio
async def test_rate_limit_429_retries_with_backoff(mock_vault_client):
    """AC: Rate limit handling is verified - calls exceeding the rate limit are retried with backoff."""
    client = MiddeskClient(
        base_url="https://api.middesk.mock",
        vault_client=mock_vault_client,
        max_retries=2,
        initial_backoff_seconds=0.01,
    )

    response_429 = httpx.Response(429, text="Rate limit exceeded")

    with patch("httpx.AsyncClient.request", return_value=response_429) as mock_http, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        with pytest.raises(AnerBaseException, match="rate limit exceeded"):
            await client.create_business({"name": "RateLimited LLC"})

        assert mock_http.call_count == 3  # Initial + 2 retries
        assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_5xx_transient_error_retries_with_backoff(mock_vault_client):
    client = MiddeskClient(
        base_url="https://api.middesk.mock",
        vault_client=mock_vault_client,
        max_retries=2,
        initial_backoff_seconds=0.01,
    )

    response_503 = httpx.Response(503, text="Service Unavailable")
    response_200 = httpx.Response(200, json={"id": "bus_recovered", "status": "pending"})

    with patch("httpx.AsyncClient.request", side_effect=[response_503, response_200]) as mock_http, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        data = await client.create_business({"name": "Transient Inc"})

        assert data["id"] == "bus_recovered"
        assert mock_http.call_count == 2
        assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_4xx_permanent_error_fails_fast_without_retry(mock_vault_client):
    """Permanent errors (4xx) fail fast without retry."""
    client = MiddeskClient(
        base_url="https://api.middesk.mock",
        vault_client=mock_vault_client,
        max_retries=3,
    )

    response_400 = httpx.Response(400, text="Bad Request - Invalid EIN format")

    with patch("httpx.AsyncClient.request", return_value=response_400) as mock_http, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        with pytest.raises(AnerBaseException, match="HTTP 400"):
            await client.create_business({"name": "Invalid Corp"})

        assert mock_http.call_count == 1  # Fails fast, no retry
        assert mock_sleep.call_count == 0
