"""
Live Sumsub identity provider.

Implements the Sumsub REST contract:
  • Applicant creation:  POST /resources/applicants?levelName={level}
  • SDK access token:    POST /resources/accessTokens?userId={ext}&levelName={level}

Every request is signed with the app-token scheme: an HMAC-SHA256 over
(timestamp + method + path + body) using SUMSUB_SECRET_KEY, sent in the
X-App-Access-Sig / X-App-Access-Ts headers alongside X-App-Token.

Only reached when SUMSUB_ENABLED=true; the test suite uses MockIdentityProvider.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import httpx
import structlog

from app.platform.configuration.config import get_settings
from app.shared.contracts.identity import (
    ApplicantResult,
    SdkTokenResult,
    WebhookParseResult,
)
from app.shared.exceptions import AnerBaseException

logger = structlog.get_logger(__name__)


class SumsubProvider:
    """Satisfies onboarding's BaseIdentityProvider port structurally (ARCHITECTURE.md §2).

    No inheritance, and no import of the module: the port is a Protocol and its DTOs
    are a shared contract, so the dependency arrow points one way.
    """

    name = "sumsub"

    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.SUMSUB_BASE_URL.rstrip("/")
        self._app_token = s.SUMSUB_APP_TOKEN
        self._secret_key = s.SUMSUB_SECRET_KEY

    # ── Request signing ───────────────────────────────────────────────────────
    def _signed_headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        ts = str(int(time.time()))
        message = ts.encode() + method.upper().encode() + path.encode() + body
        signature = hmac.new(self._secret_key.encode(), message, hashlib.sha256).hexdigest()
        return {
            "X-App-Token": self._app_token,
            "X-App-Access-Ts": ts,
            "X-App-Access-Sig": signature,
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, body: bytes) -> dict:
        headers = self._signed_headers("POST", path, body)
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
            resp = await http.post(path, content=body, headers=headers)
        if resp.status_code >= 400:
            logger.warning("sumsub_request_failed", path=path, status=resp.status_code, body=resp.text)
            raise AnerBaseException(
                detail=f"Sumsub request failed ({resp.status_code})",
                error_code="IDENTITY_PROVIDER_ERROR",
                status_code=502,
            )
        return resp.json()

    # ── Provider interface ────────────────────────────────────────────────────
    async def create_applicant(self, external_user_id: str, level_name: str) -> ApplicantResult:
        import json

        path = f"/resources/applicants?levelName={level_name}"
        body = json.dumps({"externalUserId": external_user_id}).encode()
        data = await self._post(path, body)
        return ApplicantResult(applicant_id=data["id"], external_user_id=external_user_id)

    async def generate_sdk_token(self, external_user_id: str, level_name: str) -> SdkTokenResult:
        path = f"/resources/accessTokens?userId={external_user_id}&levelName={level_name}"
        data = await self._post(path, b"")
        return SdkTokenResult(token=data["token"], user_id=data.get("userId", external_user_id))

    def parse_webhook(self, payload: dict) -> WebhookParseResult:
        review_result = payload.get("reviewResult") or {}
        return WebhookParseResult(
            event_type=payload.get("type"),
            applicant_id=payload.get("applicantId"),
            external_user_id=payload.get("externalUserId"),
            review_status=payload.get("reviewStatus"),
            review_answer=review_result.get("reviewAnswer"),
        )
