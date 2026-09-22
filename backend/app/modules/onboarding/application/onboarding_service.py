"""
OnboardingService — customer registration and SDK-token issuance.

Registration:
  1. Persist an onboarding Customer (status PENDING).
  2. Create the provider applicant (Sumsub / mock) and persist the mapping.
  3. Record an immutable audit event.
  4. Publish `customer.registered` to the event bus.

All DB writes happen on the request-scoped session; the `get_db` dependency
commits on success. Provider and event-bus calls are the only non-DB effects.
"""
from __future__ import annotations

import uuid

import structlog

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.api.schemas.onboarding import (
    OnboardingStatusResponse,
    RegisterRequest,
    RegisterResponse,
    SdkTokenResponse,
)
from app.modules.onboarding.domain.entities.applicant_mapping import ApplicantMapping
from app.modules.onboarding.domain.entities.customer import Customer
from app.modules.onboarding.domain.entities.enums import OnboardingStatus
from app.modules.onboarding.domain.ports_legacy import BaseIdentityProvider
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.infrastructure.registry import resolve_identity_provider
from app.modules.onboarding.infrastructure.repositories import (
    ApplicantMappingRepository,
    OnboardingCustomerRepository,
    VerificationRepository,
)
from app.platform.configuration.config import get_settings
from app.shared.exceptions import AnerBaseException, NotFoundError

logger = structlog.get_logger(__name__)


class OnboardingService:
    def __init__(self, db, provider: BaseIdentityProvider | None = None) -> None:
        self._db = db
        self._provider = provider or resolve_identity_provider()
        self._customers = OnboardingCustomerRepository(db)
        self._mappings = ApplicantMappingRepository(db)
        self._verifications = VerificationRepository(db)
        self._audit = AuditService(db)
        self._events = OnboardingEventPublisher()

    async def register(self, request: RegisterRequest, actor_id: uuid.UUID | None) -> RegisterResponse:
        existing = await self._customers.get_by_email(request.email)
        if existing is not None:
            raise AnerBaseException(
                detail=f"A customer with email {request.email} is already onboarding",
                error_code="CUSTOMER_ALREADY_EXISTS",
                status_code=409,
            )

        level_name = request.level_name or get_settings().SUMSUB_LEVEL_NAME
        external_user_id = f"aner-{uuid.uuid4().hex}"

        customer = await self._customers.create(
            Customer(
                email=request.email,
                full_name=request.full_name,
                company_name=request.company_name,
                country=request.country,
                external_user_id=external_user_id,
                level_name=level_name,
                status=OnboardingStatus.PENDING,
            )
        )

        # Create the provider-side applicant and persist the mapping.
        applicant = await self._provider.create_applicant(external_user_id, level_name)
        await self._mappings.create(
            ApplicantMapping(
                customer_id=customer.id,
                provider=self._provider.name,
                external_user_id=external_user_id,
                applicant_id=applicant.applicant_id,
                level_name=level_name,
            )
        )

        await self._audit.record(
            "onboarding.customer.registered",
            actor_id=actor_id,
            actor_type=ActorType.API_CLIENT,
            payload={
                "customer_id": str(customer.id),
                "external_user_id": external_user_id,
                "provider": self._provider.name,
                "applicant_id": applicant.applicant_id,
            },
        )
        await self._events.customer_registered(
            customer_id=customer.id,
            email=request.email,
            external_user_id=external_user_id,
            provider=self._provider.name,
        )

        logger.info(
            "onboarding_customer_registered",
            customer_id=str(customer.id),
            provider=self._provider.name,
            applicant_id=applicant.applicant_id,
        )
        return RegisterResponse(
            customer_id=customer.id,
            external_user_id=external_user_id,
            applicant_id=applicant.applicant_id,
            provider=self._provider.name,
            status=customer.status,
        )

    async def generate_sdk_token(self, customer_id: uuid.UUID) -> SdkTokenResponse:
        customer = await self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"Onboarding customer {customer_id} not found")

        token = await self._provider.generate_sdk_token(customer.external_user_id, customer.level_name)
        logger.info("onboarding_sdk_token_issued", customer_id=str(customer_id), provider=self._provider.name)
        return SdkTokenResponse(
            customer_id=customer.id,
            token=token.token,
            user_id=token.user_id,
            level_name=customer.level_name,
        )

    async def get_status(self, customer_id: uuid.UUID) -> OnboardingStatusResponse:
        """
        Read-only status projection for polling — no writes, no provider calls.

        Combines the customer's onboarding status with the latest immutable
        verification record (the one the webhook writes). `list_by_customer`
        returns records newest-first, so element 0 is the most recent outcome.
        """
        customer = await self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"Onboarding customer {customer_id} not found")

        verifications = await self._verifications.list_by_customer(customer_id)
        latest = verifications[0] if verifications else None

        return OnboardingStatusResponse(
            customer_id=customer.id,
            customer_status=customer.status,
            verification_status=latest.status if latest else None,
            review_status=latest.review_status if latest else None,
            review_answer=latest.review_answer if latest else None,
            last_updated_at=latest.created_at if latest else customer.updated_at,
        )
