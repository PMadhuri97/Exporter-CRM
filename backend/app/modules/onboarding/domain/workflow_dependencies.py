"""
The dependencies the onboarding workflow orchestrates, as narrow contracts.

The onboarding workflow does not verify entities, screen, rate risk, decide
compliance, open accounts, create users or send notifications. It asks the
components that own those capabilities to do so, and moves the onboarding request
through its lifecycle on the answers. This module is the whole of what it needs to
know about them: one ``Protocol`` per capability, and the plain result data each
returns.

Why a separate module
---------------------
``domain/ports.py`` is the vendor provider contract for KYC cases (subject, profile,
check runs), and ``app.modules.kyb.KYBAdapter`` is the vendor adapter interface for
entity verification. Both describe how to talk to a *vendor*. The workflow needs
something smaller: "do this for onboarding request X and tell me the outcome". A
real implementation of a contract here is expected to be built *on* those
abstractions (entity verification over the KYB facade, for instance), not to
replace them.

Rules every contract follows
----------------------------
* **Keyed by the onboarding request.** Every call takes ``onboarding_request_id``
  as a string and nothing else. An implementation loads what it needs itself, so no
  ORM entity and no personal data crosses into workflow state or history.
* **Idempotent per request.** Activities are retried. Calling a contract again for
  the same request (and, where one applies, the same owner reference) must return
  the same references rather than start a second piece of work.
* **Business outcomes are data; faults are exceptions.** A rejection, a hard block
  or a declined approval is a normal return value. An exception means the call
  itself failed and says nothing about the request.
* **Temporal-safe data.** Results are frozen dataclasses of strings, booleans and
  tuples. Enumerated values are held as the *value string* and validated against
  the existing enum on construction: Temporal's default converter does not
  round-trip ``str``-based enums inside dataclasses. Each result exposes the enum
  through a property.

Asynchronous answers
--------------------
Entity verification and compliance approval may answer later, and documents
arrive whenever the customer uploads them. :class:`KybResultReceived`,
:class:`ComplianceDecisionReceived` and :class:`DocumentSubmitted` are the payloads
those answers arrive in. Each carries the onboarding request id plus the stable
reference the workflow already holds — the vendor reference, the approval request
id, or the document id — so the workflow can ignore an answer that is not for the
work it is waiting on.

EXP-2: :class:`VerificationAdapter`
------------------------------------
The one exception to "keyed by the onboarding request" above.
:class:`VerificationAdapter` and its dataclasses (:class:`VerificationRequest`,
:class:`VerificationOutcome`, :class:`VerificationCapabilityDeclaration`) are not
one of the onboarding workflow's own dependencies — nothing here is added to
:class:`OnboardingWorkflowDependencies` or its ``_DEPENDENCY_PROTOCOLS`` table.
They live in this file because the ticket that introduced them
(``docs/exporter-crm-tickets.md``, EXP-2) is explicit: "same file, same
one-Protocol-per-capability convention as the existing 9 ... do not create a new
``ports.py`` for this." The methods are plain ``def``, not ``async def``, and the
dataclass fields hold real enum members rather than validated value-strings: unlike
the 9 protocols above, :class:`VerificationAdapter` is called from the plain async
``application/verification_service.py``, never from inside a Temporal workflow, so
none of this module's Temporal-payload-safety rules (see "Rules every contract
follows" above) apply to it. It mirrors ``app.modules.kyb.domain.ports``'s
``KYBAdapter`` ABC + ``register_adapter``/``get_adapter`` module-dict registry
instead — a *generalization* of that exact mechanism across every verification
type (KYC, bank-account, shipment, ...) rather than a KYB-specific one.
"""
from __future__ import annotations

import enum
import importlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRiskRating,
    OnboardingScreeningResult,
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, NormalisedResult

_E = TypeVar("_E", bound=enum.Enum)


def _require_value(enum_type: type[_E], value: str, field_name: str) -> None:
    valid = {member.value for member in enum_type}
    if value not in valid:
        raise ValueError(f"{field_name} must be one of {sorted(valid)}, got {value!r}")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


# ── Entity verification ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntityVerificationSubmission:
    """What submitting the entity for verification produced.

    ``outcome`` is a :class:`~app.shared.enums.kyb.NormalisedResult` value — the
    vocabulary the KYB vendor adapters already normalise to. ``PENDING`` means the
    answer will arrive later as a :class:`KybResultReceived` naming the same
    ``vendor_reference``.
    """

    vendor_id: str
    vendor_reference: str
    outcome: str

    def __post_init__(self) -> None:
        _require_text(self.vendor_id, "vendor_id")
        _require_text(self.vendor_reference, "vendor_reference")
        _require_value(NormalisedResult, self.outcome, "outcome")

    @property
    def normalised_result(self) -> NormalisedResult:
        return NormalisedResult(self.outcome)


@dataclass(frozen=True)
class KybResultReceived:
    """An entity verification answer arriving after submission."""

    onboarding_request_id: str
    vendor_id: str
    vendor_reference: str
    outcome: str

    def __post_init__(self) -> None:
        _require_text(self.onboarding_request_id, "onboarding_request_id")
        _require_text(self.vendor_id, "vendor_id")
        _require_text(self.vendor_reference, "vendor_reference")
        _require_value(NormalisedResult, self.outcome, "outcome")

    @property
    def normalised_result(self) -> NormalisedResult:
        return NormalisedResult(self.outcome)

    def answers(
        self, onboarding_request_id: str, submission: EntityVerificationSubmission
    ) -> bool:
        """True when this result is for ``submission`` of this request."""
        return (
            self.onboarding_request_id == onboarding_request_id
            and self.vendor_id == submission.vendor_id
            and self.vendor_reference == submission.vendor_reference
        )


@runtime_checkable
class EntityVerifier(Protocol):
    async def submit(self, onboarding_request_id: str) -> EntityVerificationSubmission:
        """Submit the request's entity for verification.

        Idempotent: a repeat for the same request returns the original submission.
        """
        ...


# ── Beneficial ownership ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class UboOwnersIdentified:
    """The beneficial owners to map, as stable owner references, in mapping order."""

    owner_references: tuple[str, ...]

    def __post_init__(self) -> None:
        for reference in self.owner_references:
            _require_text(reference, "owner_reference")
        if len(set(self.owner_references)) != len(self.owner_references):
            raise ValueError("owner_references must be unique")


@dataclass(frozen=True)
class UboOwnerMapped:
    owner_reference: str

    def __post_init__(self) -> None:
        _require_text(self.owner_reference, "owner_reference")


@runtime_checkable
class UboMapper(Protocol):
    async def identify_owners(self, onboarding_request_id: str) -> UboOwnersIdentified:
        """The beneficial owners of the request's entity. Idempotent."""
        ...

    async def map_owner(
        self, onboarding_request_id: str, owner_reference: str
    ) -> UboOwnerMapped:
        """Map one owner. Idempotent per ``(request, owner_reference)``."""
        ...


# ── Document collection ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class DocumentSubmitted:
    """A customer document has been stored against the request.

    ``document_id`` is the stored document's id; a repeat delivery carries the same
    id and is the same submission.
    """

    onboarding_request_id: str
    document_id: str
    document_type: str

    def __post_init__(self) -> None:
        _require_text(self.onboarding_request_id, "onboarding_request_id")
        _require_text(self.document_id, "document_id")
        _require_value(OnboardingDocumentType, self.document_type, "document_type")

    @property
    def onboarding_document_type(self) -> OnboardingDocumentType:
        return OnboardingDocumentType(self.document_type)

    def is_for(self, onboarding_request_id: str) -> bool:
        return self.onboarding_request_id == onboarding_request_id


@dataclass(frozen=True)
class DocumentCompleteness:
    """Whether the request now holds every document it requires."""

    complete: bool
    missing_document_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in self.missing_document_types:
            _require_value(OnboardingDocumentType, value, "missing_document_types")
        if self.complete and self.missing_document_types:
            raise ValueError("a complete document set cannot have missing documents")
        if not self.complete and not self.missing_document_types:
            raise ValueError("an incomplete document set must name what is missing")

    @property
    def missing(self) -> tuple[OnboardingDocumentType, ...]:
        return tuple(OnboardingDocumentType(v) for v in self.missing_document_types)


@runtime_checkable
class DocumentChecklist(Protocol):
    async def check(self, onboarding_request_id: str) -> DocumentCompleteness:
        """Whether the request's required documents are all present. Read-only."""
        ...


# ── Screening ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScreeningOutcome:
    screening_reference: str
    result: str

    def __post_init__(self) -> None:
        _require_text(self.screening_reference, "screening_reference")
        _require_value(OnboardingScreeningResult, self.result, "result")

    @property
    def screening_result(self) -> OnboardingScreeningResult:
        return OnboardingScreeningResult(self.result)


@runtime_checkable
class Screener(Protocol):
    async def screen(self, onboarding_request_id: str) -> ScreeningOutcome:
        """Screen the request's entity and owners. Idempotent."""
        ...


# ── Risk rating ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskRatingOutcome:
    rating_reference: str
    rating: str

    def __post_init__(self) -> None:
        _require_text(self.rating_reference, "rating_reference")
        _require_value(OnboardingRiskRating, self.rating, "rating")

    @property
    def risk_rating(self) -> OnboardingRiskRating:
        return OnboardingRiskRating(self.rating)


@runtime_checkable
class RiskRater(Protocol):
    async def rate(self, onboarding_request_id: str) -> RiskRatingOutcome:
        """Rate the request's risk. Idempotent."""
        ...


# ── Compliance approval ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ComplianceApprovalRequested:
    """An approval request has been raised.

    ``decision`` is set when the decision was made immediately; ``None`` means it
    will arrive later as a :class:`ComplianceDecisionReceived` naming the same
    ``approval_request_id``.

    ``reason`` is the compliance function's own account of its decision. It stays
    with compliance: the onboarding workflow's activity drops it before the result
    enters workflow history, and orchestration never depends on it.
    """

    approval_request_id: str
    decision: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.approval_request_id, "approval_request_id")
        if self.decision is not None:
            _require_value(OnboardingComplianceDecision, self.decision, "decision")
        elif self.reason is not None:
            raise ValueError("a reason is only given with a decision")

    @property
    def compliance_decision(self) -> OnboardingComplianceDecision | None:
        return None if self.decision is None else OnboardingComplianceDecision(self.decision)


@dataclass(frozen=True)
class ComplianceDecisionReceived:
    """A compliance decision arriving after the approval request was raised.

    Carries only what orchestration needs: which approval request it decides, and
    the decision. There is deliberately no free-text reason — a signal payload is
    recorded in workflow history verbatim, and the detailed reason belongs to
    compliance, which can be asked for it by ``approval_request_id``.
    """

    onboarding_request_id: str
    approval_request_id: str
    decision: str

    def __post_init__(self) -> None:
        _require_text(self.onboarding_request_id, "onboarding_request_id")
        _require_text(self.approval_request_id, "approval_request_id")
        _require_value(OnboardingComplianceDecision, self.decision, "decision")

    @property
    def compliance_decision(self) -> OnboardingComplianceDecision:
        return OnboardingComplianceDecision(self.decision)

    def answers(
        self, onboarding_request_id: str, requested: ComplianceApprovalRequested
    ) -> bool:
        """True when this decision is for ``requested`` of this request."""
        return (
            self.onboarding_request_id == onboarding_request_id
            and self.approval_request_id == requested.approval_request_id
        )


@runtime_checkable
class ComplianceApprover(Protocol):
    async def request_approval(
        self, onboarding_request_id: str
    ) -> ComplianceApprovalRequested:
        """Raise the approval request. Idempotent: a repeat returns the same one."""
        ...


# ── Account creation ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountsCreated:
    account_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.account_ids:
            raise ValueError("at least one account id is required")
        for account_id in self.account_ids:
            _require_text(account_id, "account_id")


@runtime_checkable
class AccountCreator(Protocol):
    async def create_accounts(self, onboarding_request_id: str) -> AccountsCreated:
        """Open the request's accounts. Idempotent: a repeat returns the same ids."""
        ...


# ── Customer user provisioning ────────────────────────────────────────────────


@dataclass(frozen=True)
class CustomerUserProvisioned:
    user_reference: str

    def __post_init__(self) -> None:
        _require_text(self.user_reference, "user_reference")


@runtime_checkable
class CustomerUserProvisioner(Protocol):
    async def provision_initial_user(
        self, onboarding_request_id: str
    ) -> CustomerUserProvisioned:
        """Provision the request's initial customer user. Idempotent."""
        ...


# ── Completion notification ───────────────────────────────────────────────────


@dataclass(frozen=True)
class CompletionNotificationSent:
    notification_reference: str

    def __post_init__(self) -> None:
        _require_text(self.notification_reference, "notification_reference")


@runtime_checkable
class CompletionNotifier(Protocol):
    async def notify_completed(
        self, onboarding_request_id: str
    ) -> CompletionNotificationSent:
        """Announce that onboarding completed. Idempotent: at most one notification."""
        ...


# ── EXP-2: generalized verification adapter ────────────────────────────────────


@dataclass(frozen=True)
class VerificationRequest:
    """One ask: run ``verification_type`` against ``entity_type`` /
    ``entity_reference``.

    ``payload`` is deliberately opaque here — a bank-account check's payload
    (account number, IFSC) has nothing in common with a director KYC check's
    (name, date of birth, id document), and the whole point of this Protocol is
    that the caller and the adapter agree on shape, not the service layer in
    between. ``ManualEntryAdapter`` additionally uses ``payload`` to carry the
    manually-observed result itself (see its module docstring).
    """

    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.entity_reference, "entity_reference")
        if not isinstance(self.verification_type, VerificationType):
            raise ValueError(
                f"verification_type must be a VerificationType, got {self.verification_type!r}"
            )
        if not isinstance(self.entity_type, VerificationEntityType):
            raise ValueError(
                f"entity_type must be a VerificationEntityType, got {self.entity_type!r}"
            )


@dataclass(frozen=True)
class VerificationOutcome:
    """What the adapter found, in the platform's own vocabulary.

    ``provider`` is the adapter's own, self-reported name — the service layer
    persists it verbatim onto ``VerificationResult.provider`` and never
    rewrites, defaults, or substitutes it (see
    ``application/verification_service.py``'s module docstring and
    ``tests/contract/test_verification_adapter_interface.py``'s
    ``test_provider_is_never_rewritten`` for the acceptance test this backs).
    """

    provider: str
    provider_reference: str | None
    status: VerificationResultStatus
    normalized_result: dict[str, Any]
    risk_level: VerificationRiskLevel | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        if not isinstance(self.status, VerificationResultStatus):
            raise ValueError(
                f"status must be a VerificationResultStatus, got {self.status!r}"
            )
        if self.risk_level is not None and not isinstance(self.risk_level, VerificationRiskLevel):
            raise ValueError(
                f"risk_level must be a VerificationRiskLevel or None, got {self.risk_level!r}"
            )


@dataclass(frozen=True)
class VerificationCapabilityDeclaration:
    """The static capability declaration for one verification adapter.

    Generalizes ``kyb``'s ``KYBVendorCapabilityDeclaration`` (vendor_id,
    supported_countries, supported_entity_types, processing_mode) past a
    single vendor concept keyed on country: a verification adapter is keyed on
    which :class:`VerificationType`/:class:`VerificationEntityType`
    combinations it can answer, not which countries it covers.

    ``processing_mode`` reuses :class:`~app.shared.enums.kyb.
    KYBVendorProcessingMode` rather than a new, identically-shaped enum: the
    concept (does this adapter answer synchronously or does the caller have to
    poll ``get_verification_status`` later) is not actually KYB-specific,
    despite the module it happens to live in.
    """

    provider: str
    supported_verification_types: tuple[VerificationType, ...]
    supported_entity_types: tuple[VerificationEntityType, ...]
    processing_mode: KYBVendorProcessingMode

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        if not self.supported_verification_types:
            raise ValueError("supported_verification_types must not be empty")
        if not self.supported_entity_types:
            raise ValueError("supported_entity_types must not be empty")


@runtime_checkable
class VerificationAdapter(Protocol):
    """One extensible mechanism to trigger and record *any* verification check.

    The generalization this ticket (EXP-2) exists for: a KYC check on a
    director and a bank-account check on an exporter both call
    ``application/verification_service.py``'s ``trigger_verification``, which
    resolves *this* Protocol by provider name via the registry below and calls
    ``.verify()`` — never branching on ``verification_type`` itself. Adding a
    new check type is a new enum member (:class:`VerificationType`) plus,
    where a real vendor is involved, a new adapter; it is never a new
    ``if verification_type == ...`` branch in the service layer.
    """

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        """Returns the static capability declaration for this adapter."""
        ...

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Submit ``request`` for verification, returning the outcome.

        For a synchronous adapter this is the final answer. For an
        asynchronous one, ``VerificationOutcome.status`` may be ``PENDING``,
        with the final answer arriving later via :meth:`get_verification_status`.
        """
        ...

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Poll for the result of a previously submitted, asynchronous check.

        Not applicable (or a documented no-op) for synchronous adapters — see
        ``ManualEntryAdapter.get_verification_status``'s docstring for how this
        adapter answers that, mirroring
        ``kyb.infrastructure.adapters.trulioo``'s own synchronous-vendor
        precedent.
        """
        ...

    def get_vendor_health(self) -> VendorHealthStatus:
        """Performs a health check on this verification provider."""
        ...


@runtime_checkable
class BatchVerificationAdapter(Protocol):
    """The optional, additive "one payload produces many results" capability
    (EXP-2 plan point 6 / Exporter CRM Piece 3): a provider like RXIL hands
    over a batch of already-run checks in one package, unlike Middesk/
    Trulioo/``ManualEntryAdapter``'s one-call-one-result shape.

    **Design decision — a separate Protocol, not a method added to**
    :class:`VerificationAdapter`. The alternative this ticket also considered
    was a ``verify_batch`` method on :class:`VerificationAdapter` itself,
    defaulting to "not supported" for adapters that don't implement it. That
    would mean either turning :class:`VerificationAdapter` from a pure
    structural :class:`Protocol` into a base class every adapter must
    actually subclass (to inherit the default), or leaving every current and
    future single-check adapter (:class:`ManualEntryAdapter`, any future
    Middesk/Trulioo wrapper) to carry a method that only ever raises. Neither
    fits this module's own stated rule: "Rules every contract follows" this
    file's own docstring and comments describe one Protocol per capability,
    each independent of the others (``EntityVerifier``, ``UboMapper``,
    ``Screener``, ... nine of them, plus :class:`VerificationAdapter` itself
    for EXP-2). Batch verification is its own capability by that same logic —
    it gets its own Protocol, exactly like every other capability here, and
    an adapter that has no use for it (every adapter except an RXIL-shaped
    one, for the foreseeable future) simply never implements it. A caller
    checks for batch support the same way this module's registry consumers
    already check for anything else: ``isinstance(adapter,
    BatchVerificationAdapter)`` (a `runtime_checkable` structural check, not a
    capability flag on a shared base) — see
    ``application/verification_service.py``'s ``trigger_verification_batch``.

    An adapter that implements this normally also implements
    :class:`VerificationAdapter` (so the registry's ordinary single-check
    path and health-check machinery still work for it), but nothing here
    requires that structurally — the two Protocols are independent, exactly
    like every other pair in this module.
    """

    def verify_batch(self, requests: list[VerificationRequest]) -> list[VerificationOutcome]:
        """Run every check in ``requests``, returning one
        :class:`VerificationOutcome` per request, in the same order.

        All-or-nothing from the caller's perspective: either every check in
        the batch produces an outcome, or this raises and
        ``VerificationService.trigger_verification_batch`` persists nothing
        — the same one-payload-one-transaction shape the batch capability
        exists to prove.
        """
        ...


#: Every :class:`VerificationAdapter` class, keyed by the provider name callers
#: pass to ``trigger_verification``. A straight generalization of
#: ``kyb.domain.ports.REGISTRY``: same dict-backed shape, parameterized by
#: :class:`VerificationAdapter` instead of ``KYBAdapter``. Shared verbatim by
#: :class:`BatchVerificationAdapter` implementations too (``StubRxilAdapter``
#: registers into this exact registry) — batch support is a second,
#: independently-checked capability of a registry entry, not a second
#: registry.
VERIFICATION_ADAPTER_REGISTRY: dict[str, type[VerificationAdapter]] = {}


def register_adapter(name: str, adapter_cls: type[VerificationAdapter]) -> None:
    VERIFICATION_ADAPTER_REGISTRY[name] = adapter_cls


def get_adapter(class_path: str) -> type[VerificationAdapter]:
    if class_path in VERIFICATION_ADAPTER_REGISTRY:
        return VERIFICATION_ADAPTER_REGISTRY[class_path]
    if "." in class_path:
        module_name, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    raise ValueError(
        f"Verification adapter class {class_path} not found in registry and not fully qualified"
    )


# ── The set the workflow's activities are built with ──────────────────────────


@dataclass(frozen=True)
class OnboardingWorkflowDependencies:
    """Every capability the onboarding workflow orchestrates, injected together."""

    entity_verifier: EntityVerifier
    ubo_mapper: UboMapper
    document_checklist: DocumentChecklist
    screener: Screener
    risk_rater: RiskRater
    compliance_approver: ComplianceApprover
    account_creator: AccountCreator
    customer_user_provisioner: CustomerUserProvisioner
    completion_notifier: CompletionNotifier

    def __post_init__(self) -> None:
        # Checked on construction so a missing method fails when the worker is
        # built rather than midway through an onboarding.
        for name, protocol in _DEPENDENCY_PROTOCOLS.items():
            if not isinstance(getattr(self, name), protocol):
                raise TypeError(f"{name} does not implement {protocol.__name__}")


#: The protocol each :class:`OnboardingWorkflowDependencies` field must satisfy.
_DEPENDENCY_PROTOCOLS: dict[str, type] = {
    "entity_verifier": EntityVerifier,
    "ubo_mapper": UboMapper,
    "document_checklist": DocumentChecklist,
    "screener": Screener,
    "risk_rater": RiskRater,
    "compliance_approver": ComplianceApprover,
    "account_creator": AccountCreator,
    "customer_user_provisioner": CustomerUserProvisioner,
    "completion_notifier": CompletionNotifier,
}
