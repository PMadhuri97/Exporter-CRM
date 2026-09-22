"""
Internal provider DTOs — the only types an adapter may return.

The contract requires that "adapter returns internal DTOs only" and that "no
provider-specific payload leaks into case workflow". Every type in this module is
vendor-neutral: nothing here names Sumsub, ComplyAdvantage, or any future provider,
and nothing here carries a vendor's raw response shape.

**Versioning.** These DTOs are a published contract that both Arshad's identity
adapters and Tejasvi's screening adapters compile against. The version is
:data:`PROVIDER_CONTRACT_VERSION` and is stamped onto every DTO instance. Bump the
minor version for additive, backward-compatible fields; bump the major version for
any removal or type change, and update ``docs/provider-contract.md`` in the same
commit.

**PII.** :class:`ProfileInput` is the only DTO that carries subject PII. Its
``attributes`` field is marked ``repr=False`` so that logging or reprinting the DTO
— including inside a traceback — never emits personal data. Do not remove that.

**Raw payloads.** :meth:`normalize_result` is the one place in the system where an
adapter may look at a vendor's raw response; it is passed in as an opaque mapping
and must not be echoed into the returned :class:`NormalizedResult`. Raw bytes live
behind an :class:`EvidenceRef` pointing at object storage.
"""
from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.exceptions import ProviderFailureReason

#: Semantic version of the provider contract and its DTOs.
#:
#: ``-draft`` means the contract is **not frozen**. Escalation E1 in
#: ``docs/project-memory.md`` §10.1 is open: Tejasvi must ratify the capability
#: split before this becomes ``1.0.0``. Vendor adapters (Sumsub, ComplyAdvantage)
#: must not be written against a draft contract without accepting that it may still move.
PROVIDER_CONTRACT_VERSION = "1.0.0-draft"


class _ProviderDTO(BaseModel):
    """
    Base for every provider DTO: immutable, strict, and version-stamped.

    ``frozen=True`` makes a DTO safe to pass across an activity boundary without
    defensive copying. ``extra="forbid"`` guarantees a vendor field cannot be
    smuggled through by an adapter that sets an undeclared attribute.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = PROVIDER_CONTRACT_VERSION


# ── Enumerations ─────────────────────────────────────────────────────────────


class SubjectType(str, enum.Enum):
    """What kind of entity a case is about. Discriminates KYC from KYB."""

    INDIVIDUAL = "INDIVIDUAL"
    ENTITY = "ENTITY"


class CheckType(str, enum.Enum):
    """
    A single unit of verification work requested from a provider.

    The identity checks are exercised by identity-verification providers; the
    screening checks by screening providers. A provider declares which subset it
    honours; asking for one it does not support is an ``UNSUPPORTED_COUNTRY`` or
    ``INVALID_PAYLOAD`` failure, decided by the adapter.
    """

    IDENTITY = "IDENTITY"
    DOCUMENT = "DOCUMENT"
    LIVENESS = "LIVENESS"
    SANCTIONS = "SANCTIONS"
    PEP = "PEP"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    WATCHLIST = "WATCHLIST"


class ProviderCheckState(str, enum.Enum):
    """
    The provider's own view of a check's progress.

    Deliberately coarser than ``provider_run``'s nine states: this is
    what a vendor can tell us, not what our lifecycle records. The provider-run
    service maps this onto its own state machine.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OverallStatus(str, enum.Enum):
    """
    The normalized verdict of one provider run.

    Proposed by decision D7 (``docs/project-memory.md`` §10.2) and **ratified at
    the shared gate**, not here. ``CLEAR`` is not "approved" — the
    platform, never a provider, approves a case.
    """

    CLEAR = "CLEAR"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"


class RiskLevel(str, enum.Enum):
    """
    Normalized risk banding. Per D7, ``CRITICAL`` is the distinct top level and the
    only band that blocks approval outright; ``HIGH`` is
    escalation-worthy but not automatically blocking.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendedAction(str, enum.Enum):
    """
    What the provider's evidence *suggests*. Advisory only.

    The decision layer is free to ignore this. A ``RecommendedAction``
    of ``APPROVE`` does not approve anything.
    """

    APPROVE = "APPROVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"


class ProviderCapability(str, enum.Enum):
    """
    A coherent group of contract methods an adapter can satisfy.

    Capabilities exist because screening has no profile-submission step: forcing
    ComplyAdvantage to no-op ``create_subject`` and ``submit_profile`` would make
    the contract a lie. An adapter declares its capabilities; the registry refuses
    to hand it to a caller that needs one it lacks.
    """

    IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    SCREENING = "SCREENING"


# ── Evidence ─────────────────────────────────────────────────────────────────


class EvidenceRef(_ProviderDTO):
    """
    An opaque pointer to raw provider evidence held outside the database.

    Satisfies "raw provider payload stored separately as an evidence reference" and
    "evidence references point to raw payload/document records **without exposing
    raw data**". The ``uri`` addresses object storage (MinIO in dev, GCS/S3 in prod
    — escalation E2); ``sha256`` lets a reader prove the bytes were not altered
    without fetching them.

    The backing table does not exist yet. Until then this DTO is the contract.
    """

    uri: str = Field(description="Object-storage URI. Never a vendor API URL, never a signed URL.")
    kind: str = Field(description="What the bytes are, e.g. 'webhook_payload', 'status_response'.")
    sha256: str = Field(min_length=64, max_length=64, description="Hex digest of the stored bytes.")
    captured_at: datetime


class FailureDetails(_ProviderDTO):
    """Structured description of why a provider run failed. Never contains PII."""

    reason: ProviderFailureReason
    message: str = Field(description="Safe-to-log summary. No PII, no raw payload, no URLs.")
    retryable: bool = Field(description="Whether a bounded retry could plausibly succeed.")


# ── Inputs ───────────────────────────────────────────────────────────────────


class SubjectInput(_ProviderDTO):
    """
    Everything an adapter needs to open a subject with a provider.

    Carries no PII: the profile attributes arrive separately via
    :class:`ProfileInput`, so that ``create_subject`` can be logged and traced
    freely while ``submit_profile`` cannot.
    """

    case_id: uuid.UUID
    external_subject_id: str = Field(description="Aner's stable id for the subject. Not a vendor id.")
    subject_type: SubjectType
    country_code: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2.")


class ProfileInput(_ProviderDTO):
    """
    Subject identity attributes. **This DTO carries PII.**

    ``attributes`` is ``repr=False``: printing, logging, or capturing this object in
    a traceback will not emit its contents. Keep it that way.
    """

    subject_ref: SubjectRef
    attributes: Mapping[str, Any] = Field(
        repr=False,
        description="Subject PII. Never logged, never audited, never placed in an event payload.",
    )


class CheckRequest(_ProviderDTO):
    """A request to run one or more checks against an already-created subject."""

    case_id: uuid.UUID
    subject_ref: SubjectRef
    check_types: tuple[CheckType, ...] = Field(min_length=1)
    country_code: str = Field(min_length=2, max_length=2)


class WebhookRequest(_ProviderDTO):
    """
    A raw inbound provider webhook, before any interpretation.

    ``body`` stays as bytes because signature verification is computed over the
    exact bytes received; re-serializing parsed JSON changes the digest.
    """

    body: bytes = Field(repr=False)
    headers: Mapping[str, str]


# ── Outputs ──────────────────────────────────────────────────────────────────


class SubjectRef(_ProviderDTO):
    """
    A provider's handle on a subject, returned by ``create_subject``.

    ``provider_subject_id`` is a vendor external id (a Sumsub applicant id, a
    ComplyAdvantage entity id). Per policy it may live **only** in provider
    metadata and evidence references — never on a core case table.
    """

    provider_name: str
    provider_subject_id: str
    external_subject_id: str


class ProfileRef(_ProviderDTO):
    """Acknowledgement that a provider accepted a subject's profile."""

    provider_name: str
    provider_subject_id: str
    accepted_at: datetime


class CheckRun(_ProviderDTO):
    """
    Acknowledgement that a provider accepted a check request.

    ``provider_reference`` is the vendor's id for this unit of work; it is what a
    later webhook or ``get_status`` poll will correlate on.
    """

    provider_name: str
    provider_reference: str
    check_types: tuple[CheckType, ...]
    state: ProviderCheckState
    started_at: datetime


class ProviderStatus(_ProviderDTO):
    """The provider's current view of a check run, returned by ``get_status``."""

    provider_name: str
    provider_reference: str
    state: ProviderCheckState
    checked_at: datetime
    failure: FailureDetails | None = None


class WebhookEvent(_ProviderDTO):
    """
    A vendor webhook, parsed into vendor-neutral terms.

    Note what is absent: there is no ``approved`` or ``rejected`` property. The
    previous ``WebhookParseResult`` had both, and that is precisely how a provider's
    verdict became the platform's verdict. A webhook updates ``provider_run``; it
    can never decide a case.
    """

    provider_name: str
    event_type: str
    provider_reference: str | None
    provider_subject_id: str | None
    state: ProviderCheckState
    occurred_at: datetime
    signature_verified: bool


class CheckOutcome(_ProviderDTO):
    """
    The result of a single check inside a run.

    ``details`` is a free-form mapping so that a provider can report a check type
    this platform has never seen without a migration — satisfying "schema supports
    unknown/future check types without migration churn". It is persisted as JSONB.
    Vendor-neutral keys only; no raw response fragments.
    """

    check_type: str = Field(description="A CheckType value, or a novel type as a bare string.")
    status: OverallStatus
    risk_level: RiskLevel
    details: Mapping[str, Any] = Field(default_factory=dict)


class NormalizedResult(_ProviderDTO):
    """
    The single internal result model shared by every provider.

    **The workflow reads this and nothing else.** It never reads a raw provider
    payload, and it never reads a vendor DTO. A Sumsub fixture and a ComplyAdvantage
    fixture must both normalize into this exact structure.

    ``provider_run_id`` is optional only because the ``provider_run`` table does not
    exist yet; once it exists, every normalized result belongs to a run.

    This shape is proposed, not frozen: Tejasvi ratifies it at the shared gate.
    See decision D7.
    """

    provider_name: str
    provider_run_id: uuid.UUID | None = None
    overall_status: OverallStatus
    risk_level: RiskLevel
    recommended_action: RecommendedAction
    check_outcomes: tuple[CheckOutcome, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    failure_details: FailureDetails | None = None


# ProfileInput and CheckRequest forward-reference SubjectRef, which is declared
# after them for readability (inputs above outputs). Resolve those references now.
ProfileInput.model_rebuild()
CheckRequest.model_rebuild()
