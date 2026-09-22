from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.integrations.kyb.trulioo.client import TruliooApiClient
from app.integrations.kyb.trulioo.exceptions import TruliooApiError, TruliooRateLimitError


class TestAC4VaultCredentials:
    def test_client_uses_settings_credentials(self) -> None:
        """Verify that the client reads credentials from Settings."""
        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="vault-secret-key-123",
                TRULIOO_MAX_RETRIES=2,
                TRULIOO_TIMEOUT_SECONDS=15,
            )
            client = TruliooApiClient()
            assert client._api_url == "https://test.trulioo.com"
            assert client._api_key == "vault-secret-key-123"

    def test_api_key_in_request_headers(self) -> None:
        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="my-vault-key",
                TRULIOO_MAX_RETRIES=1,
                TRULIOO_TIMEOUT_SECONDS=10,
            )
            client = TruliooApiClient()
            headers = client._headers()
            assert headers["x-trulioo-api-key"] == "my-vault-key"

class TestR2RetryAndRateLimit:
    def test_retry_on_server_error(self) -> None:
        """Client retries on 5xx errors."""
        responses = [
            httpx.Response(500, json={}),
            httpx.Response(200, json={"TransactionID": "txn-1", "Record": {}}),
        ]
        call_count = 0

        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="key",
                TRULIOO_MAX_RETRIES=3,
                TRULIOO_TIMEOUT_SECONDS=5,
            )
            client = TruliooApiClient()

            def fake_execute(method: str, url: str, *, json_body: Any = None) -> httpx.Response:
                nonlocal call_count
                resp = responses[min(call_count, len(responses) - 1)]
                call_count += 1
                return resp

            with patch.object(client, "_execute_request", side_effect=fake_execute):
                with patch("app.integrations.kyb.trulioo.client.time.sleep"):
                    result = client.verify("IN", {"BusinessName": "Test"})

            assert call_count == 2
            assert result["TransactionID"] == "txn-1"

    def test_rate_limit_429_with_retry_after(self) -> None:
        """Client respects Retry-After header on 429."""
        responses = [
            httpx.Response(429, headers={"Retry-After": "2"}, json={}),
            httpx.Response(200, json={"TransactionID": "txn-2", "Record": {}}),
        ]
        call_count = 0

        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="key",
                TRULIOO_MAX_RETRIES=3,
                TRULIOO_TIMEOUT_SECONDS=5,
            )
            client = TruliooApiClient()

            def fake_execute(method: str, url: str, *, json_body: Any = None) -> httpx.Response:
                nonlocal call_count
                resp = responses[min(call_count, len(responses) - 1)]
                call_count += 1
                return resp

            with patch.object(client, "_execute_request", side_effect=fake_execute):
                with patch("app.integrations.kyb.trulioo.client.time.sleep") as mock_sleep:
                    result = client.verify("IN", {"BusinessName": "Test"})

            assert call_count == 2
            assert result["TransactionID"] == "txn-2"
            mock_sleep.assert_called_once_with(2.0)

    def test_rate_limit_exhausted_raises(self) -> None:
        """All retries exhausted on 429 raises TruliooRateLimitError."""
        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="key",
                TRULIOO_MAX_RETRIES=2,
                TRULIOO_TIMEOUT_SECONDS=5,
            )
            client = TruliooApiClient()

            def fake_execute(method: str, url: str, *, json_body: Any = None) -> httpx.Response:
                return httpx.Response(429, headers={"Retry-After": "1"}, json={})

            with patch.object(client, "_execute_request", side_effect=fake_execute):
                with patch("app.integrations.kyb.trulioo.client.time.sleep"):
                    with pytest.raises(TruliooRateLimitError):
                        client.verify("IN", {"BusinessName": "Test"})

    def test_retry_on_connection_error(self) -> None:
        """Client retries on connection timeouts."""
        call_count = 0

        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="key",
                TRULIOO_MAX_RETRIES=3,
                TRULIOO_TIMEOUT_SECONDS=5,
            )
            client = TruliooApiClient()

            effects: list = [
                httpx.TimeoutException("timeout"),
                httpx.Response(200, json={"TransactionID": "txn-3", "Record": {}}),
            ]

            def fake_execute(method: str, url: str, *, json_body: Any = None) -> httpx.Response:
                nonlocal call_count
                effect = effects[min(call_count, len(effects) - 1)]
                call_count += 1
                if isinstance(effect, Exception):
                    raise effect
                return effect

            with patch.object(client, "_execute_request", side_effect=fake_execute):
                with patch("app.integrations.kyb.trulioo.client.time.sleep"):
                    result = client.verify("IN", {"BusinessName": "Test"})

            assert call_count == 2
            assert result["TransactionID"] == "txn-3"

    def test_client_error_no_retry(self) -> None:
        """Client errors (4xx except 429) are not retried."""
        with patch(
            "app.integrations.kyb.trulioo.client.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRULIOO_API_URL="https://test.trulioo.com",
                TRULIOO_API_KEY="key",
                TRULIOO_MAX_RETRIES=3,
                TRULIOO_TIMEOUT_SECONDS=5,
            )
            client = TruliooApiClient()

            def fake_execute(method: str, url: str, *, json_body: Any = None) -> httpx.Response:
                return httpx.Response(401, json={"error": "unauthorized"})

            with patch.object(client, "_execute_request", side_effect=fake_execute):
                with pytest.raises(TruliooApiError, match="401"):
                    client.verify("IN", {"BusinessName": "Test"})
