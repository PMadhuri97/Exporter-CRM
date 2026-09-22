"""
WebhookService — inbound Sumsub webhook handling.

Pipeline for POST /onboarding/webhooks/sumsub:
  1. Verify the HMAC signature over the raw body (401 on failure).
  2. Idempotency: insert a WebhookEvent keyed on SHA-256(raw body). A redelivered
     identical webhook hits the UNIQUE constraint and is acknowledged as a no-op.
  3. Persist + process: write an immutable Verification record, transition the
     customer's onboarding status, record an audit event, and publish
     `customer.verification.updated`.

The webhook is always acknowledged quickly (200) once the signature is valid and
the event is recorded, so the provider does not retry unnecessarily.
"""
from __future__ import annotations

import hashlib
import json

import structlog
from sqlalchemy.exc import IntegrityError

from app.integrations.webhooks.security import verify_signature
from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.api.schemas.onboarding import WebhookAck
from app.modules.onboarding.domain.entities.customer import Customer
from app.modules.onboarding.domain.entities.enums import OnboardingStatus, VerificationStatus
from app.modules.onboarding.domain.entities.verification import Verification
from app.modules.onboarding.domain.entities.webhook_event import WebhookEvent
from app.modules.onboarding.domain.ports_legacy import BaseIdentityProvider
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.infrastructure.registry import resolve_identity_provider
from app.modules.onboarding.infrastructure.repositories import (
    ApplicantMappingRepository,
    OnboardingCustomerRepository,
    VerificationRepository,
    WebhookEventRepository,
)
from app.platform.configuration.config import get_settings
from app.shared.exceptions import AnerBaseException

logger = structlog.get_logger(__name__)


class WebhookService:
    def __init__(self, db, provider: BaseIdentityProvider | None = None) -> None:
        self._db = db
        self._provider = provider or resolve_identity_provider()
        self._webhooks = WebhookEventRepository(db)
        self._customers = OnboardingCustomerRepository(db)
        self._mappings = ApplicantMappingRepository(db)
        self._verifications = VerificationRepository(db)
        self._audit = AuditService(db)
        self._events = OnboardingEventPublisher()

    async def process_sumsub_webhook(
        self, raw_body: bytes, signature: str | None, alg: str | None
    ) -> WebhookAck:
        secret = get_settings().SUMSUB_WEBHOOK_SECRET

        # 1. Signature validation.
        if not verify_signature(raw_body, signature, secret, alg):
            logger.warning("onboarding_webhook_invalid_signature")
            raise AnerBaseException(
                detail="Invalid webhook signature",
                error_code="INVALID_WEBHOOK_SIGNATURE",
                status_code=401,
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AnerBaseException(
                detail="Webhook body is not valid JSON",
                error_code="INVALID_WEBHOOK_BODY",
                status_code=400,
            )

        parsed = self._provider.parse_webhook(payload)
        dedup_key = hashlib.sha256(raw_body).hexdigest()

        # 2. Idempotency — insert the webhook record; duplicate raw body → no-op.
        event = WebhookEvent(
            provider=self._provider.name,
            event_type=parsed.event_type,
            applicant_id=parsed.applicant_id,
            dedup_key=dedup_key,
            signature_verified=True,
            processed=False,
            raw_payload=payload,
        )
        try:
            await self._webhooks.create(event)
        except IntegrityError:
            await self._db.rollback()
            logger.info("onboarding_webhook_duplicate", dedup_key=dedup_key)
            return WebhookAck(status="duplicate")

        # 3. Persist + process.
        customer = await self._resolve_customer(parsed.applicant_id, parsed.external_user_id)
        if customer is None:
            # Unknown applicant — keep the (verified) webhook for audit, no state change.
            event.processed = True
            logger.warning(
                "onboarding_webhook_unknown_applicant",
                applicant_id=parsed.applicant_id,
                external_user_id=parsed.external_user_id,
            )
            return WebhookAck(status="ok")

        verification_status, onboarding_status = self._map_result(parsed)
        await self._verifications.create(
            Verification(
                customer_id=customer.id,
                provider=self._provider.name,
                provider_ref=parsed.applicant_id,
                review_status=parsed.review_status,
                review_answer=parsed.review_answer,
                status=verification_status,
                raw_payload=payload,
            )
        )
        if onboarding_status is not None:
            customer.status = onboarding_status
        event.processed = True

        await self._audit.record(
            "onboarding.verification.updated",
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            payload={
                "customer_id": str(customer.id),
                "provider": self._provider.name,
                "applicant_id": parsed.applicant_id,
                "review_status": parsed.review_status,
                "review_answer": parsed.review_answer,
                "verification_status": verification_status.value,
            },
        )
        await self._events.customer_verification_updated(
            customer_id=customer.id,
            status=customer.status.value,
            provider_ref=parsed.applicant_id,
            review_answer=parsed.review_answer,
        )

        logger.info(
            "onboarding_webhook_processed",
            customer_id=str(customer.id),
            verification_status=verification_status.value,
            onboarding_status=customer.status.value,
        )
        return WebhookAck(status="ok")

    async def _resolve_customer(
        self, applicant_id: str | None, external_user_id: str | None
    ) -> Customer | None:
        if applicant_id:
            mapping = await self._mappings.get_by_applicant_id(applicant_id)
            if mapping is not None:
                return await self._customers.get_by_id(mapping.customer_id)
        if external_user_id:
            return await self._customers.get_by_external_user_id(external_user_id)
        return None

    @staticmethod
    def _map_result(parsed) -> tuple[VerificationStatus, OnboardingStatus | None]:
        if parsed.approved:
            return VerificationStatus.APPROVED, OnboardingStatus.APPROVED
        if parsed.rejected:
            return VerificationStatus.REJECTED, OnboardingStatus.REJECTED
        # No terminal answer yet (e.g. reviewStatus=pending) — reflect as in-review.
        return VerificationStatus.PENDING, OnboardingStatus.IN_REVIEW
