"""
HashiCorp Vault client integration for platform secret retrieval.

Retrieves credentials dynamically from HashiCorp Vault API or environment-based
Vault secrets configuration, ensuring zero hardcoded credentials in application code.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class VaultClient:
    """
    Client for retrieving secrets from HashiCorp Vault.

    If VAULT_ADDR and VAULT_TOKEN environment variables are available,
    makes an HTTP GET request to Vault KV v2 engine (`/v1/{path}`).
    Otherwise, falls back to retrieving environment secrets (e.g. MIDDESK_API_KEY).
    """

    def __init__(
        self,
        vault_addr: str | None = None,
        vault_token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        raw_addr = vault_addr or os.getenv("VAULT_ADDR") or ""
        self.vault_addr = raw_addr.rstrip("/")
        self.vault_token = vault_token or os.getenv("VAULT_TOKEN") or ""
        self.timeout = timeout
        self._enabled = bool(self.vault_addr and self.vault_token)

    async def get_secret(self, path: str) -> dict[str, Any]:
        """
        Fetch a secret dictionary from Vault KV store at `path`.

        Args:
            path: Vault KV path, e.g. "secret/data/middesk" or "middesk".

        Returns:
            Dictionary of secret key-values.
        """
        if self._enabled:
            kv_path = path if path.startswith("secret/data/") else f"secret/data/{path}"
            url = f"{self.vault_addr}/v1/{kv_path}"
            headers: dict[str, str] = {"X-Vault-Token": self.vault_token}


            try:
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    resp = await http.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    # Vault KV v2 structure: data.data.data or data.data
                    secret_data = data.get("data", {})
                    if "data" in secret_data and isinstance(secret_data["data"], dict):
                        return secret_data["data"]
                    if isinstance(secret_data, dict):
                        return secret_data
            except Exception as exc:
                logger.error("vault_secret_fetch_failed", path=path, error=str(exc))
                from app.shared.exceptions import AnerBaseException

                raise AnerBaseException(
                    detail=f"Failed to retrieve secret from Vault at path '{path}': {exc}",
                    error_code="VAULT_FETCH_FAILED",
                    status_code=502,
                ) from exc

        # Fallback path for local dev/testing where Vault container is not running:
        # Resolve from environment variables (e.g. MIDDESK_API_KEY)
        env_key = os.getenv("MIDDESK_API_KEY", "")
        return {"api_key": env_key}

    async def get_middesk_credentials(self) -> str:
        """
        Convenience method to retrieve the Middesk API key from Vault.
        """
        secret = await self.get_secret("middesk")
        api_key = secret.get("api_key") or secret.get("MIDDESK_API_KEY") or secret.get("key") or ""
        return str(api_key)


def get_vault_client() -> VaultClient:
    return VaultClient()
