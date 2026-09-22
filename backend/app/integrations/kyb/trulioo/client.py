"""Trulioo GlobalGateway HTTP client — Epic 4.1 / S2T2.

Low-level HTTP wrapper around the Trulioo GlobalGateway API.  All PII is masked
before it reaches any log line, retry with exponential back-off is applied to
transient failures (5xx, timeouts), and HTTP 429 responses are handled by
respecting the ``Retry-After`` header.

Credentials are drawn from :class:`~app.platform.configuration.config.Settings`
which sources them from Vault-backed environment variables.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from app.integrations.kyb.trulioo.exceptions import (
    TruliooApiError,
    TruliooRateLimitError,
)
from app.integrations.kyb.trulioo.pii_masking import mask_value
from app.platform.configuration.config import get_settings

logger = structlog.get_logger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_BACKOFF_BASE: float = 1.0  # seconds
_DEFAULT_BACKOFF_FACTOR: float = 2.0
_MAX_BACKOFF: float = 60.0


class TruliooApiClient:
    """Synchronous HTTP client for the Trulioo GlobalGateway API.

    The KYBAdapter interface is synchronous, so this client uses
    ``httpx.Client`` (not ``AsyncClient``).

    Parameters
    ----------
    api_url:
        Override the base URL from Settings.  Useful for testing.
    api_key:
        Override the API key from Settings.  Useful for testing.
    max_retries:
        Override the max retry count from Settings.
    timeout_seconds:
        Override the request timeout from Settings.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self._api_url = (api_url or settings.TRULIOO_API_URL).rstrip("/")
        self._api_key = api_key or settings.TRULIOO_API_KEY
        self._max_retries = max_retries if max_retries is not None else settings.TRULIOO_MAX_RETRIES
        self._timeout = timeout_seconds or settings.TRULIOO_TIMEOUT_SECONDS

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "x-trulioo-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with retry and rate-limit handling.

        Retries on 5xx and connection/timeout errors using exponential back-off.
        On HTTP 429, reads ``Retry-After`` and waits before retrying.
        """
        url = f"{self._api_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._execute_request(method, url, json_body=json_body)

                # ── Rate-limit handling ──────────────────────────────────────
                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response)
                    logger.warning(
                        "trulioo_rate_limit_hit",
                        attempt=attempt,
                        retry_after_seconds=retry_after,
                    )
                    if attempt < self._max_retries:
                        time.sleep(retry_after)
                        continue
                    raise TruliooRateLimitError(
                        retry_after_seconds=retry_after,
                    )

                # ── Transient server errors ──────────────────────────────────
                if response.status_code >= 500:
                    logger.warning(
                        "trulioo_server_error",
                        attempt=attempt,
                        status_code=response.status_code,
                    )
                    if attempt < self._max_retries:
                        backoff = self._backoff_seconds(attempt)
                        time.sleep(backoff)
                        continue
                    raise TruliooApiError(
                        f"Trulioo server error ({response.status_code})",
                        status_code=response.status_code,
                    )

                # ── Client errors ────────────────────────────────────────────
                if response.status_code >= 400:
                    raise TruliooApiError(
                        f"Trulioo request failed ({response.status_code})",
                        status_code=response.status_code,
                    )

                return response.json()  # type: ignore[no-any-return]

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "trulioo_connection_error",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self._max_retries:
                    backoff = self._backoff_seconds(attempt)
                    time.sleep(backoff)
                    continue

        raise TruliooApiError(
            f"Trulioo request failed after {self._max_retries} attempts",
        ) from last_exc

    def _execute_request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute a single HTTP request (no retry)."""
        with httpx.Client(timeout=self._timeout) as client:
            return client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
            )

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        """Exponential back-off: ``base * factor^(attempt-1)``, capped."""
        delay = _DEFAULT_BACKOFF_BASE * (_DEFAULT_BACKOFF_FACTOR ** (attempt - 1))
        return min(delay, _MAX_BACKOFF)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """Extract ``Retry-After`` seconds from the response, default 60."""
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                return max(float(raw), 1.0)
            except (ValueError, TypeError):
                pass
        return 60.0

    # ── Public API ───────────────────────────────────────────────────────────

    def verify(self, country_code: str, data_fields: dict[str, Any]) -> dict[str, Any]:
        """Submit a verification request to the Trulioo ``/v1/verify`` endpoint.

        Parameters
        ----------
        country_code:
            ISO 3166-1 alpha-2 country code (e.g. ``"IN"``, ``"GB"``).
        data_fields:
            Country-specific data fields for the verification request.

        Returns
        -------
        dict
            The parsed JSON response from Trulioo.
        """
        logger.info(
            "trulioo_verify_request",
            country_code=country_code,
            field_count=len(data_fields),
        )

        body: dict[str, Any] = {
            "AcceptTruliooTermsAndConditions": True,
            "CountryCode": country_code,
            "DataFields": data_fields,
        }

        result = self._request_with_retry("POST", "/verifications/v1/verify", json_body=body)

        logger.info(
            "trulioo_verify_response",
            country_code=country_code,
            transaction_id=result.get("TransactionID", "unknown"),
            record_status=result.get("Record", {}).get("RecordStatus", "unknown"),
        )

        return result

    def test_connection(self) -> dict[str, Any]:
        """Health-check ping against the ``/connection/v1/testauthentication`` endpoint."""
        logger.debug("trulioo_health_check")
        return self._request_with_retry("GET", "/connection/v1/testauthentication")

    def get_datasources(self, country_code: str) -> dict[str, Any]:
        """Retrieve available data sources for *country_code*.

        Used to build country-specific verification requests — the adapter
        constructs the request with only the fields the country supports.
        """
        logger.debug(
            "trulioo_get_datasources",
            country_code=country_code,
        )
        return self._request_with_retry(
            "GET",
            f"/configuration/v1/datasources/Business/{country_code}",
        )

    def mask_for_log(self, value: str | None) -> str:
        """Convenience wrapper around :func:`mask_value` for ad-hoc log calls."""
        return mask_value(value)
