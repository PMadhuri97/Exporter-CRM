"""Create and read back onboarding requests in the shared test database.

The test database is never reset, so every request gets fresh ids and callers
assert only on the request they created. Sessions come from
``database.AsyncSessionLocal`` at call time, so the test engine the root conftest
installs is the one used.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_event_repository import (
    OnboardingEventRepository,
)
from app.platform.database import services as database

#: Values seeded on every request. Tests that check nothing sensitive leaks out of
#: the workflow look for these.
SEEDED_LEGAL_NAME = "Fixture Onboarding Holdings Ltd"
SEEDED_REGISTRATION_NUMBER = "FIXTURE-REG-448812"
SEEDED_TAX_IDENTIFICATION_NUMBER = "FIXTURE-TIN-907733"


async def create_onboarding_request(
    status: OnboardingRequestStatus = OnboardingRequestStatus.DRAFT,
) -> uuid.UUID:
    async with database.AsyncSessionLocal() as session:
        request = OnboardingRequest(
            tenant_id=uuid.uuid4(),
            idempotency_key=f"fixture-{uuid.uuid4().hex}",
            customer_id=uuid.uuid4(),
            status=status,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name=SEEDED_LEGAL_NAME,
            registration_number=SEEDED_REGISTRATION_NUMBER,
            tax_identification_number=SEEDED_TAX_IDENTIFICATION_NUMBER,
            incorporation_country="US",
            registered_address={"line1": "1 Fixture Street", "country": "US"},
            initial_user_id="fixture-initial-user",
        )
        session.add(request)
        await session.commit()
        return request.id


async def read_onboarding_request(onboarding_request_id: uuid.UUID) -> OnboardingRequest:
    async with database.AsyncSessionLocal() as session:
        request = await session.get(OnboardingRequest, onboarding_request_id)
        assert request is not None
        return request


async def read_onboarding_events(onboarding_request_id: uuid.UUID) -> Sequence[OnboardingEvent]:
    async with database.AsyncSessionLocal() as session:
        return list(
            await OnboardingEventRepository(session).list_by_request(onboarding_request_id)
        )
