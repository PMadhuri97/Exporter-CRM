"""
In-process mock identity provider.

The default when SUMSUB_ENABLED is false, so CI and the test suite run with no
network calls and no real credentials. It returns deterministic identifiers and
parses Sumsub-shaped webhook payloads exactly as the live provider does — so the
webhook-processing path (signature check, parse, verification record, status
transition) is exercised faithfully in tests.
"""
from __future__ import annotations

import uuid

from app.modules.onboarding.domain.ports_legacy import (
    ApplicantResult,
    BaseIdentityProvider,
    SdkTokenResult,
    WebhookParseResult,
)


class MockIdentityProvider(BaseIdentityProvider):
    name = "mock"

    async def create_applicant(self, external_user_id: str, level_name: str) -> ApplicantResult:
        return ApplicantResult(
            applicant_id=f"mock-applicant-{external_user_id}",
            external_user_id=external_user_id,
        )

    async def generate_sdk_token(self, external_user_id: str, level_name: str) -> SdkTokenResult:
        return SdkTokenResult(token=f"mock-token-{uuid.uuid4().hex}", user_id=external_user_id)

    def parse_webhook(self, payload: dict) -> WebhookParseResult:
        review_result = payload.get("reviewResult") or {}
        return WebhookParseResult(
            event_type=payload.get("type"),
            applicant_id=payload.get("applicantId"),
            external_user_id=payload.get("externalUserId"),
            review_status=payload.get("reviewStatus"),
            review_answer=review_result.get("reviewAnswer"),
        )
