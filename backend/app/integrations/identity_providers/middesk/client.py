"""
Middesk HTTP API Client.

All API calls use Middesk API key credentials retrieved from Vault. No hardcoded credentials.
Handles Middesk rate limits (HTTP 429) and transient errors (5xx responses) with retry and
exponential backoff. Permanent errors (4xx) fail fast without retry.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.platform.configuration.config import get_settings
from app.platform.security.vault import VaultClient
from app.shared.exceptions import AnerBaseException

logger = structlog.get_logger(__name__)


class MiddeskClient:
    """
    HTTP client for the Middesk API.

    Reads API key dynamically from Vault, implements exponential backoff on 429 & 5xx,
    and returns raw Middesk JSON response objects.
    """

    def __init__(
        self,
        base_url: str | None = None,
        vault_client: VaultClient | None = None,
        max_retries: int = 3,
        initial_backoff_seconds: float = 0.1,
    ) -> None:
        settings = get_settings()
        configured_url = getattr(settings, "MIDDESK_BASE_URL", "https://api.middesk.com/v1")
        self.base_url = (base_url or configured_url).rstrip("/")
        self.vault_client = vault_client or VaultClient()
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds

    async def _get_auth_headers(self) -> dict[str, str]:
        """Fetch API Key from Vault and return Bearer auth headers."""
        api_key = await self.vault_client.get_middesk_credentials()
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute HTTP request with exponential backoff on HTTP 429 and HTTP 5xx.
        Permanent 4xx errors fail fast without retry.
        """
        headers = await self._get_auth_headers()
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

        attempt = 0
        backoff = self.initial_backoff_seconds

        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    response = await http.request(method, url, headers=headers, json=json_data)

                status = response.status_code

                if status == 429 or status >= 500:
                    if attempt <= self.max_retries:
                        logger.warning(
                            "middesk_transient_error_retrying",
                            status=status,
                            attempt=attempt,
                            backoff_seconds=backoff,
                        )
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        continue

                    if status == 429:
                        raise AnerBaseException(
                            detail="Middesk rate limit exceeded after retries",
                            error_code="PROVIDER_PROVIDER_UNAVAILABLE",
                            status_code=502,
                        )
                    raise AnerBaseException(
                        detail=f"Middesk server error ({status}) after retries",
                        error_code="PROVIDER_PROVIDER_UNAVAILABLE",
                        status_code=502,
                    )

                if status >= 400:
                    logger.error(
                        "middesk_permanent_client_error",
                        status=status,
                    )
                    raise AnerBaseException(
                        detail=f"Middesk request failed with HTTP {status}",
                        error_code="PROVIDER_INVALID_PAYLOAD",
                        status_code=422,
                    )

                return response.json()

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt <= self.max_retries:
                    logger.warning(
                        "middesk_network_timeout_retrying",
                        error=str(exc),
                        attempt=attempt,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise AnerBaseException(
                    detail=f"Middesk API request timed out: {exc}",
                    error_code="PROVIDER_TIMEOUT",
                    status_code=504,
                ) from exc

    async def create_business(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a business object in Middesk (POST /v1/businesses)."""
        return await self._request_with_retry("POST", "/businesses", json_data=payload)

    async def get_business(self, business_id: str) -> dict[str, Any]:
        """Fetch business details from Middesk (GET /v1/businesses/{business_id})."""
        return await self._request_with_retry("GET", f"/businesses/{business_id}")
