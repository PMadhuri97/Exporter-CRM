import enum


class OnboardingRequestStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ENTITY_VERIFICATION_IN_PROGRESS = "ENTITY_VERIFICATION_IN_PROGRESS"
    ENTITY_VERIFIED = "ENTITY_VERIFIED"
    UBO_MAPPING_IN_PROGRESS = "UBO_MAPPING_IN_PROGRESS"
    UBO_MAPPING_COMPLETE = "UBO_MAPPING_COMPLETE"
    DOCUMENT_COLLECTION_IN_PROGRESS = "DOCUMENT_COLLECTION_IN_PROGRESS"
    DOCUMENT_COLLECTION_COMPLETE = "DOCUMENT_COLLECTION_COMPLETE"
    SCREENING_IN_PROGRESS = "SCREENING_IN_PROGRESS"
    SCREENING_COMPLETE = "SCREENING_COMPLETE"
    RISK_RATING_IN_PROGRESS = "RISK_RATING_IN_PROGRESS"
    RISK_RATED = "RISK_RATED"
    PENDING_COMPLIANCE_APPROVAL = "PENDING_COMPLIANCE_APPROVAL"
    APPROVED = "APPROVED"
    ACCOUNT_CREATION_IN_PROGRESS = "ACCOUNT_CREATION_IN_PROGRESS"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"
    UNDER_REVIEW = "UNDER_REVIEW"

class OnboardingEntityType(str, enum.Enum):
    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    SOLE_TRADER = "SOLE_TRADER"
    TRUST = "TRUST"
    FUND = "FUND"

class OnboardingRiskRating(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class OnboardingScreeningResult(str, enum.Enum):
    CLEAR = "CLEAR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HARD_BLOCK = "HARD_BLOCK"

class OnboardingComplianceDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class OnboardingRejectionCategory(str, enum.Enum):
    KYB_FAILURE = "KYB_FAILURE"
    SCREENING_BLOCK = "SCREENING_BLOCK"
    COMPLIANCE_REJECTION = "COMPLIANCE_REJECTION"
    DOCUMENT_FRAUD = "DOCUMENT_FRAUD"
    TIMEOUT = "TIMEOUT"

class UboControlType(str, enum.Enum):
    DIRECT_OWNERSHIP = "DIRECT_OWNERSHIP"
    INDIRECT_OWNERSHIP = "INDIRECT_OWNERSHIP"
    VOTING_RIGHTS = "VOTING_RIGHTS"
    OTHER_CONTROL = "OTHER_CONTROL"

class UboIdentificationType(str, enum.Enum):
    PASSPORT = "PASSPORT"
    NATIONAL_ID = "NATIONAL_ID"
    DRIVING_LICENCE = "DRIVING_LICENCE"

class UboKycResult(str, enum.Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    NOT_STARTED = "NOT_STARTED"

class UboPepStatus(str, enum.Enum):
    NOT_PEP = "NOT_PEP"
    PEP = "PEP"
    PEP_ASSOCIATE = "PEP_ASSOCIATE"

class OnboardingDocumentType(str, enum.Enum):
    CERTIFICATE_OF_INCORPORATION = "CERTIFICATE_OF_INCORPORATION"
    MEMORANDUM_OF_ASSOCIATION = "MEMORANDUM_OF_ASSOCIATION"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"
    BANK_STATEMENT = "BANK_STATEMENT"
    AUDITED_ACCOUNTS = "AUDITED_ACCOUNTS"
    LICENCE = "LICENCE"
    UBO_DECLARATION = "UBO_DECLARATION"
    OTHER = "OTHER"

class OnboardingValidationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"

class KybNormalisedResult(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    REJECTED = "REJECTED"
    REQUIRES_MANUAL_REVIEW = "REQUIRES_MANUAL_REVIEW"
    PENDING = "PENDING"
    NOT_SUPPORTED = "NOT_SUPPORTED"


# ── EXP-2: generalized VerificationAdapter / VerificationResult vocabulary ────
#
# Named with a `Verification` prefix throughout, even where the PRD's own name
# would collide: `entities.enums.VerificationStatus` (the legacy single-record
# KYC verification outcome: PENDING/APPROVED/REJECTED) and
# `domain.dto.RiskLevel` (the provider-contract risk banding: LOW/MEDIUM/HIGH/
# CRITICAL) already exist with different value sets for different concepts.
# Reusing either here would either be wrong (different members) or would make
# an unqualified import silently ambiguous. See VerificationResultStatus and
# VerificationRiskLevel below.

class VerificationType(str, enum.Enum):
    """Every kind of check `VerificationResult` can record.

    Deliberately a closed, plain enum (not a free string) so Postgres and
    Alembic constrain it — but designed be extended additively (new member,
    new migration) as new check types show up, never a schema redesign.
    """

    KYC = "KYC"
    KYB = "KYB"
    AML = "AML"
    CFT = "CFT"
    SANCTIONS = "SANCTIONS"
    PEP = "PEP"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    COMPANY_REGISTRY = "COMPANY_REGISTRY"
    UBO = "UBO"
    GST = "GST"
    IEC = "IEC"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    BUYER = "BUYER"
    INVOICE = "INVOICE"
    INVOICE_DUPLICATION = "INVOICE_DUPLICATION"
    SHIPMENT = "SHIPMENT"
    VESSEL = "VESSEL"
    INSURANCE = "INSURANCE"


class VerificationEntityType(str, enum.Enum):
    """What kind of thing a `VerificationResult` is checking.

    Named `VerificationEntityType` rather than the PRD's bare `EntityType` to
    avoid reading as a synonym for `OnboardingEntityType` above (legal-entity
    structure — CORPORATION/PARTNERSHIP/...) — an entirely different axis.
    """

    EXPORTER = "EXPORTER"
    BUYER = "BUYER"
    DIRECTOR = "DIRECTOR"
    INVOICE = "INVOICE"
    VESSEL = "VESSEL"
    SHIPMENT = "SHIPMENT"


class VerificationResultStatus(str, enum.Enum):
    """The outcome of one verification check.

    Named `VerificationResultStatus` rather than the PRD's bare
    `VerificationStatus`: `entities.enums.VerificationStatus` already exists
    (PENDING/APPROVED/REJECTED, for the legacy single-record `Verification`
    entity) with a different member set for a different concept.
    """

    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REVIEW = "REVIEW"


class VerificationRiskLevel(str, enum.Enum):
    """Risk banding a verification check may produce. Not every check type does
    (e.g. GST/IEC lookups don't), hence nullable on `VerificationResult`.

    Named `VerificationRiskLevel` rather than the PRD's bare `RiskLevel`:
    `domain.dto.RiskLevel` already exists (LOW/MEDIUM/HIGH/CRITICAL, for
    provider-contract risk banding) with a different member set.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VerificationReviewStatus(str, enum.Enum):
    """A compliance reviewer's decision on a `VerificationResult`."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
