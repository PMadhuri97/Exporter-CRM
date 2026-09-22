"""Shared contracts — pure, vendor-neutral data shapes that cross a boundary.

A contract lands here only when it is the data half of a port an ``integrations/``
adapter must construct, or a payload two modules exchange without either owning it.
Everything here must be dependency-free and business-free (ARCHITECTURE.md §3).
"""
from app.shared.contracts.identity import (
    ApplicantResult,
    SdkTokenResult,
    WebhookParseResult,
)
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.contracts.rails import (
    LegStatusUpdate,
    LegSubmissionRequest,
    LegSubmissionResponse,
    RailCapabilityDeclaration,
    RailHealthStatus,
)
from app.shared.contracts.signals import ApprovalSignalPayload

__all__ = [
    "ApplicantResult",
    "ApprovalSignalPayload",
    "EntityVerificationRequest",
    "KYBVendorCapabilityDeclaration",
    "KYBVerificationResult",
    "LegStatusUpdate",
    "LegSubmissionRequest",
    "LegSubmissionResponse",
    "RailCapabilityDeclaration",
    "RailHealthStatus",
    "SdkTokenResult",
    "VendorHealthStatus",
    "WebhookParseResult",
]
