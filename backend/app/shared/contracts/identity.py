"""
Identity-provider data contract.

These three types are the data half of the onboarding module's identity-provider
port. The interface itself is owned by the consuming module
(:mod:`app.modules.onboarding.domain.ports_legacy`, ARCHITECTURE.md §2), but its
DTOs must be constructible by the vendor adapter that implements it — and §2 also
forbids an integration from importing a module. A pure, vendor-neutral data
contract in ``shared/`` is the only shape that satisfies both rules.

Pure by construction: no imports, no dependencies, no behaviour beyond two string
comparisons. Nothing here names a vendor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApplicantResult:
    """Outcome of creating a provider-side applicant."""

    applicant_id: str
    external_user_id: str


@dataclass
class SdkTokenResult:
    """A short-lived token the client SDK uses to launch the verification flow."""

    token: str
    user_id: str


@dataclass
class WebhookParseResult:
    """Normalised view of an inbound provider webhook payload."""

    event_type: str | None
    applicant_id: str | None
    external_user_id: str | None
    review_status: str | None
    review_answer: str | None  # e.g. GREEN / RED

    @property
    def approved(self) -> bool:
        return (self.review_answer or "").upper() == "GREEN"

    @property
    def rejected(self) -> bool:
        return (self.review_answer or "").upper() == "RED"
