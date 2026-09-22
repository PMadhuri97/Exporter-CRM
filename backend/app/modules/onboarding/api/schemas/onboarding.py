from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.modules.onboarding.domain.entities.enums import OnboardingStatus, VerificationStatus


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    # Optional override of the provider verification level (defaults to config).
    level_name: str | None = Field(default=None, max_length=100)


class RegisterResponse(BaseModel):
    customer_id: uuid.UUID
    external_user_id: str
    applicant_id: str | None
    provider: str
    status: OnboardingStatus


class SdkTokenResponse(BaseModel):
    customer_id: uuid.UUID
    token: str
    user_id: str
    level_name: str


class WebhookAck(BaseModel):
    status: str  # "ok" | "duplicate"


class OnboardingStatusResponse(BaseModel):
    """
    Read-only projection of a customer's current onboarding/verification state.

    Serves the polling test harness (and any read-only status UI): it exposes the
    customer's onboarding status alongside the fields from the *latest* immutable
    verification record (written by the webhook). Purely a read model — it never
    mutates anything.
    """

    customer_id: uuid.UUID
    # Onboarding lifecycle status on the customer row (PENDING/IN_REVIEW/APPROVED/REJECTED).
    customer_status: OnboardingStatus
    # Fields from the most recent verification record, or None if none exists yet.
    verification_status: VerificationStatus | None = None
    review_status: str | None = None   # raw provider reviewStatus (e.g. "completed")
    review_answer: str | None = None   # raw provider reviewAnswer (e.g. "GREEN"/"RED")
    # created_at of the latest verification, else the customer's updated_at.
    last_updated_at: datetime | None = None
