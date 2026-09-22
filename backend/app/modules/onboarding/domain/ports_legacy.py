"""
Identity-provider abstraction for customer onboarding.

`BaseIdentityProvider` is the interface every KYC/KYB provider must implement.
`SumsubProvider` is the live implementation; `MockIdentityProvider` is the
in-process default used by CI/tests. This mirrors the FX / USDC-bridge / INR-payout
/ notification / bank-confirmation provider pattern already used across the
platform: swap the implementation without touching the service layer.

**Why ``Protocol`` and not ``ABC``.** Structural typing means an adapter satisfies
this port without importing it, which keeps the dependency arrow pointing one way:
the vendor depends on nothing in ``modules/``, the module depends on the contract.
A nominal ABC forced ``integrations/`` to import this module in order to subclass —
the §2 violation recorded as F9. The port's DTOs live in
:mod:`app.shared.contracts.identity` for the same reason: an adapter must be able to
construct them. They are re-exported here so this module stays the single import
surface for the port.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.shared.contracts.identity import (
    ApplicantResult,
    SdkTokenResult,
    WebhookParseResult,
)

__all__ = [
    "ApplicantResult",
    "BaseIdentityProvider",
    "SdkTokenResult",
    "WebhookParseResult",
]


@runtime_checkable
class BaseIdentityProvider(Protocol):
    """Contract for a KYC/KYB identity-verification provider."""

    name: str

    async def create_applicant(self, external_user_id: str, level_name: str) -> ApplicantResult:
        """Create (or return) the provider applicant for this external user id."""
        ...

    async def generate_sdk_token(self, external_user_id: str, level_name: str) -> SdkTokenResult:
        """Mint a client SDK access token for the applicant's verification flow."""
        ...

    def parse_webhook(self, payload: dict) -> WebhookParseResult:
        """Normalise a raw inbound webhook payload into a WebhookParseResult."""
        ...
