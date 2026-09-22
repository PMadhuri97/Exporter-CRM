"""
Middesk vendor adapter implementation for KYB module.

Implements the unified KYBAdapter port for US entity verifications via Middesk.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.integrations.identity_providers.middesk.client import MiddeskClient
from app.integrations.identity_providers.middesk.mapper import map_to_kyb_verification_result
from app.modules.kyb.domain.ports import KYBAdapter, register_adapter
from app.platform.configuration.config import Settings
from app.platform.security.vault import VaultClient
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum
from app.shared.exceptions import (
    ProviderNotEnabledError,
    UnauthorizedError,
    UnsupportedCountryError,
)

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10)


def verify_middesk_signature(
    payload: dict[str, Any] | str | bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verify HMAC SHA256 signature header against Middesk webhook payload."""
    if not signature_header or not secret:
        return False

    timestamp = ""
    signature = ""
    for part in signature_header.split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp = part[2:]
        elif part.startswith("v1="):
            signature = part[3:]

    if not signature:
        signature = signature_header.strip()

    if isinstance(payload, dict):
        payload_str = json.dumps(payload, separators=(",", ":"))
    elif isinstance(payload, bytes):
        payload_str = payload.decode("utf-8")
    else:
        payload_str = str(payload)

    if timestamp:
        signed_payload = f"{timestamp}.{payload_str}".encode()
    else:
        signed_payload = payload_str.encode("utf-8")

    expected_sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, signature)


def _run_async(coro: Any) -> Any:
    """Helper to safely execute async coroutines from synchronous KYBAdapter port methods."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return _EXECUTOR.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class MiddeskAdapter(KYBAdapter):
    """
    US KYB Vendor Adapter using Middesk API.
    """

    def __init__(
        self,
        client: MiddeskClient | None = None,
        settings: Settings | None = None,
        vault_client: VaultClient | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.vault_client = vault_client or VaultClient()
        base_url = getattr(self.settings, "MIDDESK_BASE_URL", "https://api.middesk.com/v1")
        self.client = client or MiddeskClient(base_url=base_url, vault_client=self.vault_client)

    def _check_enabled(self) -> None:
        """Verify MIDDESK_ENABLED flag before proceeding."""
        if not getattr(self.settings, "MIDDESK_ENABLED", True):
            raise ProviderNotEnabledError("middesk")

    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        """Returns static capability declaration for Middesk vendor."""
        return KYBVendorCapabilityDeclaration(
            vendor_id="middesk",
            vendor_name="Middesk",
            supported_countries=["US"],
            supported_entity_types=["corporation", "llc", "partnership", "c_corp", "s_corp"],
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify_entity(self, entity: EntityVerificationRequest) -> KYBVerificationResult:
        """
        Submit entity for US verification via Middesk POST /v1/businesses.
        """
        self._check_enabled()
        if entity.registration_country != "US":
            raise UnsupportedCountryError(
                f"Middesk adapter only supports US entity verifications, got '{entity.registration_country}'",
                provider_name="middesk",
            )

        async def _verify() -> KYBVerificationResult:
            payload: dict[str, Any] = {
                "name": entity.legal_name,
                "registration_number": entity.registration_number,
                "registration_country": entity.registration_country,
                "address": entity.registered_address,
            }
            if entity.trading_name:
                payload["trading_name"] = entity.trading_name
            if entity.tax_identification_number:
                payload["tin"] = entity.tax_identification_number

            raw_res = await self.client.create_business(payload)
            business_id = str(raw_res.get("id") or raw_res.get("business_id") or "pending")
            return map_to_kyb_verification_result(business_id, raw_res)

        return _run_async(_verify())

    def get_verification_status(self, vendor_reference: str) -> KYBVerificationResult:
        """
        Poll verification status for previously submitted business reference.
        """
        self._check_enabled()

        async def _get_status() -> KYBVerificationResult:
            raw_res = await self.client.get_business(vendor_reference)
            return map_to_kyb_verification_result(vendor_reference, raw_res)

        return _run_async(_get_status())

    def get_vendor_health(self) -> VendorHealthStatus:
        """
        Perform health check on Middesk API integration.
        """
        async def _check_health() -> VendorHealthStatus:
            start_time = time.monotonic()
            try:
                api_key = await self.vault_client.get_middesk_credentials()
                if not api_key:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    return VendorHealthStatus(
                        status=VendorHealthStatusEnum.DOWN,
                        response_time_ms=elapsed_ms,
                        known_issues="Middesk API key missing or empty in Vault",
                    )

                async with httpx.AsyncClient(timeout=5.0) as http:
                    resp = await http.get(
                        f"{self.client.base_url}/businesses",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    if resp.status_code in (200, 404):
                        return VendorHealthStatus(
                            status=VendorHealthStatusEnum.HEALTHY,
                            response_time_ms=elapsed_ms,
                            known_issues=None,
                        )
                    if resp.status_code in (401, 403):
                        return VendorHealthStatus(
                            status=VendorHealthStatusEnum.DOWN,
                            response_time_ms=elapsed_ms,
                            known_issues="Invalid or unauthorized Middesk API key",
                        )
                    return VendorHealthStatus(
                        status=VendorHealthStatusEnum.DEGRADED,
                        response_time_ms=elapsed_ms,
                        known_issues=f"Middesk returned HTTP {resp.status_code}",
                    )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return VendorHealthStatus(
                    status=VendorHealthStatusEnum.DOWN,
                    response_time_ms=elapsed_ms,
                    known_issues=str(exc),
                )

        return _run_async(_check_health())

    def parse_webhook(
        self,
        payload: dict[str, Any],
        signature_header: str | None = None,
    ) -> KYBVerificationResult:
        """
        Parse incoming webhook payload from Middesk after HMAC signature verification.
        """
        self._check_enabled()

        secret = getattr(self.settings, "MIDDESK_WEBHOOK_SECRET", None)
        if not secret or not verify_middesk_signature(payload, signature_header, secret):
            raise UnauthorizedError("Invalid or missing Middesk webhook signature")

        data = payload.get("data") or payload
        business_obj = data.get("object") if isinstance(data, dict) and "object" in data else data
        if not isinstance(business_obj, dict):
            business_obj = payload

        business_id = str(business_obj.get("id") or business_obj.get("business_id") or "unknown")
        return map_to_kyb_verification_result(business_id, business_obj)


# Register adapter in canonical KYB registry
register_adapter("middesk", MiddeskAdapter)

