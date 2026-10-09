"""Read-model views and the pure decision rules for the background check
(``docs/contracts/background-check.md``).

Pure data structures and pure functions — no I/O, no session — the same pattern as
``deal_views.py`` and ``engagement_views.py``. ``BackgroundCheckService`` assembles
the views and calls the rules.

Two things live here, and both are here for the same reason:

- **The view types** the service returns and the router serialises.
- **The ``CLEAR`` prerequisite rule**, as one pure function over
  ``CompanyComplianceInputs`` plus the decision's own inputs. The task requires the
  rule to be one function rather than conditions spread through repository queries
  (``background-check.md`` §14.1), so that a change to what it means touches exactly
  one function and its unit tests.

**The prerequisite rule is parameterised.** The contract fixes *which* four
prerequisites exist; ``ClearPolicy`` fixes what two of its phrases mean ("pending",
"answered") and what "evidence recorded" covers. Those meanings are fields rather than
literals in the rule body, so a change is one value rather than a scattered edit.
``CLEAR_POLICY`` carries the settled meanings (28 September 2026);
``docs/contracts/background-check.md`` §14 records each answer and who made it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.onboarding.domain.compliance_facts import CheckState, check_state
from app.modules.onboarding.domain.compliance_inputs import CompanyComplianceInputs
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)

# ── Rules versions ────────────────────────────────────────────────────────────

#: The Clear rules before 1 October 2026: the four prerequisites over the
#: **eight**-item screening checklist (``website-reviewed`` first). Never written:
#: it is what a decision with ``rules_version IS NULL`` means by the documented read
#: rule, because those decisions cannot be updated.
CLEAR_RULES_V1 = "clear-2026-09-28-8items"

#: The Clear rules since 1 October 2026: the same four prerequisites over the
#: **seven**-item checklist (``website-reviewed`` retired with the website field),
#: scoped to the company's current check cycle. Written on every new decision and on
#: every new cycle.
CLEAR_RULES_V2 = "clear-2026-10-01-7items"

#: The Clear rules since the passed-checks rule (1 October 2026): V2's four
#: prerequisites, plus KYB, AML and sanctions each **passed** in the current cycle
#: ("passed" as ``compliance_facts.check_state`` means it). Written on every
#: decision, proposal and cycle since.
CLEAR_RULES_V3 = "clear-2026-10-01-7items-kyb-aml-sanctions"

#: The version every new decision records.
CURRENT_CLEAR_RULES = CLEAR_RULES_V3


def effective_rules_version(stored: str | None) -> str:
    """A decision's rules version with the legacy read rule applied."""
    return stored or CLEAR_RULES_V1


# ── Views ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BackgroundCheckMove:
    """One move this viewer may make, and what it needs.

    The rules as data: the screen asks the server which moves to offer rather than
    keeping a copy of the table (contract §3, §7.5), so a rule change cannot leave a
    stale button behind. ``reason_required`` and ``risk_required`` let the screen ask
    for the text and the rating *before* submitting rather than showing a 422 after.
    """

    to: BackgroundCheckState
    reason_required: bool
    risk_required: bool
    #: Maker-checker: this move is recorded as a proposal and takes effect only
    #: when a different COMPLIANCE user approves it.
    approval_required: bool = False


@dataclass(frozen=True)
class BackgroundCheckCycleAction:
    """One new check cycle this viewer may start now.

    Served like ``allowed_moves``, so the Re-KYC / Re-KYB buttons appear exactly when
    the server would accept them. ``reopens`` says the start also moves a ``CLEAR``
    company back to ``IN_REVIEW`` in the same transaction, so the screen can say
    so before anyone presses it.
    """

    kind: str  # CheckCycleKind value
    reason_required: bool
    reopens: bool


@dataclass(frozen=True)
class EvidenceItemView:
    """One id a decision was recorded against. IDs only, never content (contract §6)."""

    kind: BackgroundCheckEvidenceKind
    crm_document_id: uuid.UUID | None = None
    verification_result_id: uuid.UUID | None = None
    verification_review_id: uuid.UUID | None = None
    screening_review_item_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BackgroundCheckDecisionView:
    """One recorded move, as a reader sees it."""

    id: uuid.UUID
    company_id: uuid.UUID
    from_value: BackgroundCheckState
    to_value: BackgroundCheckState
    decided_by: str | None
    decided_by_kind: BackgroundCheckDecidedByKind
    source: BackgroundCheckDecisionSource
    decided_at: datetime
    reason: str | None
    risk_rating: BackgroundCheckRisk | None
    supersedes_decision_id: uuid.UUID | None
    evidence: tuple[EvidenceItemView, ...] = ()
    #: The Clear rules in force when it was taken; ``None`` = v1 by rule.
    rules_version: str | None = None
    #: The check cycle it was taken in; ``None`` = cycle 1 by rule.
    cycle_id: uuid.UUID | None = None
    #: Maker-checker: the proposal it approved, who approved it and when.
    proposal_id: uuid.UUID | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    #: When a CLEAR stops being current; ``None`` on other moves, and on a
    #: CLEAR before 0027 (read as ``decided_at`` + one year).
    expires_at: datetime | None = None


# ── Maker-checker ────────────────────────────────────────────────────────────

#: What a viewer may do with an open proposal — served, like ``allowed_moves``.
PROPOSAL_APPROVE = "APPROVE"
PROPOSAL_REJECT = "REJECT"
PROPOSAL_WITHDRAW = "WITHDRAW"

#: A proposal's status: open until resolved, then its resolution's outcome.
PROPOSAL_OPEN = "OPEN"


@dataclass(frozen=True)
class BackgroundCheckProposalView:
    """One proposed move and, once resolved, how it ended."""

    id: uuid.UUID
    company_id: uuid.UUID
    based_on_decision_id: uuid.UUID
    from_value: BackgroundCheckState
    to_value: BackgroundCheckState
    risk_rating: BackgroundCheckRisk | None
    reason: str
    proposed_by: str
    proposed_at: datetime
    cycle_id: uuid.UUID
    rules_version: str
    evidence_count: int
    #: ``OPEN``, or the resolution's outcome (``APPROVED``/``REJECTED``/``WITHDRAWN``).
    status: str = PROPOSAL_OPEN
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    #: The decision an approval wrote.
    decision_id: uuid.UUID | None = None

    @property
    def is_open(self) -> bool:
        return self.status == PROPOSAL_OPEN


def proposal_actions(
    proposal: BackgroundCheckProposalView,
    *,
    viewer_id: str,
    viewer_may_resolve: bool,
    is_stale: bool,
) -> tuple[str, ...]:
    """What this viewer may do with ``proposal`` — role- **and user**-aware.

    The proposer may only withdraw; any other COMPLIANCE user may approve or
    reject. A stale proposal (the chain or the inputs moved) can no longer be approved,
    only rejected or withdrawn. Nothing on a resolved proposal.
    """
    if not proposal.is_open:
        return ()
    if viewer_id == proposal.proposed_by:
        return (PROPOSAL_WITHDRAW,)
    if not viewer_may_resolve:
        return ()
    return (PROPOSAL_REJECT,) if is_stale else (PROPOSAL_APPROVE, PROPOSAL_REJECT)


# ── The evidence snapshot ────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceSelection:
    """The ids a decision is about to be pinned to, chosen from the seam's inputs.

    Built by :func:`select_evidence` and turned into rows by the service, so *what*
    is pinned is decided by a pure function a unit test can drive, and the service
    only writes.
    """

    verifications: tuple[tuple[uuid.UUID, uuid.UUID | None], ...] = ()
    """``(verification_result_id, latest_review_id)`` pairs. The review id is a bare
    uuid with no foreign key, and ``None`` for a result with no review yet (contract
    §6.1)."""

    screening_items: tuple[uuid.UUID, ...] = ()
    """``screening_review_item.id`` of every catalogue item that has a recorded row.
    An item never answered has no row to pin, so it contributes nothing."""

    documents: tuple[uuid.UUID, ...] = ()
    """``crm_document.id`` of the company's own documents that passed the scan gate
    (settled 28 September 2026). Deal paperwork is not pinned: it belongs to
    the deal, not to the company's standing."""

    @property
    def count(self) -> int:
        return len(self.verifications) + len(self.screening_items) + len(self.documents)


@dataclass(frozen=True)
class DocumentInput:
    """One of the company's documents, as the evidence rule sees it.

    Deliberately not the ``CrmDocument`` entity: the rule stays pure and unit-testable
    without the ORM, and the document row's shape can change without touching this.
    """

    document_id: uuid.UUID
    scan_status: str  # DocumentScanStatus value


#: **Settled 28 September 2026.** Only a document that passed the scan gate is
#: pinned. A `PENDING_SCAN`, `QUARANTINED` or `SCAN_FAILED` document is never served
#: (`storage-and-documents.md` §4), so pinning one would name evidence that cannot be
#: opened.
SERVABLE_SCAN_STATUS = "AVAILABLE"


def select_evidence(
    inputs: CompanyComplianceInputs,
    documents: tuple[DocumentInput, ...] = (),
) -> EvidenceSelection:
    """The ids this decision rests on.

    Every decision takes a snapshot, not only ``CLEAR`` — the architecture says "each
    decision" (contract §6) — and a snapshot may legitimately be empty, which is the
    normal case for move 1 on a company with no inputs yet.

    Pins the verification results, the screening rows, and — **settled 28 September
    2026** — the company's own ``AVAILABLE`` documents. The caller supplies the
    document list so this function stays pure; applying the scan-status rule
    *here* rather than in the query is what keeps the decision in one testable place.
    """
    return EvidenceSelection(
        verifications=tuple(
            (item.verification_result_id, item.latest_review_id) for item in inputs.verifications
        ),
        screening_items=tuple(
            item.screening_review_item_id
            for item in inputs.screening_items
            if item.screening_review_item_id is not None
        ),
        documents=tuple(
            document.document_id
            for document in documents
            if document.scan_status == SERVABLE_SCAN_STATUS
        ),
    )


def inputs_fingerprint(inputs: CompanyComplianceInputs, evidence: EvidenceSelection) -> str:
    """A SHA-256 (hex) of what a decision would rest on (maker-checker).

    Taken when a move is proposed and again when it is approved; approval is refused if
    they differ, so the checker never approves a decision on inputs the maker did not
    see. It covers the cycle, each result's status and review head (a review, or a
    provider result settling, changes it), each screening answer row (append-only, so
    its id is its content) and the pinned documents. Order-independent.
    """
    canonical = {
        "cycle": str(inputs.current_cycle_id) if inputs.current_cycle_id else None,
        "verifications": sorted(
            [
                str(check.verification_result_id),
                check.status,
                str(check.latest_review_id) if check.latest_review_id else "",
                check.latest_review_status or "",
            ]
            for check in inputs.verifications
        ),
        "screening": sorted(
            [item.item_key, str(item.screening_review_item_id), item.status or ""]
            for item in inputs.screening_items
            if item.screening_review_item_id is not None
        ),
        "documents": sorted(str(document_id) for document_id in evidence.documents),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ── The CLEAR prerequisite rule ──────────────────────────────────────────────

#: The four prerequisite names the contract fixes. Returned verbatim to the caller so a
#: refusal names each unmet one (contract §13).
CLEAR_RISK_REQUIRED = "risk_rating"
CLEAR_NO_CHECKS_PENDING = "no_checks_pending"
CLEAR_SCREENING_ANSWERED = "screening_items_answered"
CLEAR_EVIDENCE_RECORDED = "evidence_recorded"


def passed_prerequisite(verification_type: str) -> str:
    """Rule B's prerequisite name for one required type: ``kyb_passed`` …"""
    return f"{verification_type.lower()}_passed"


#: The passed-checks rule's three, by name.
CLEAR_KYB_PASSED = passed_prerequisite("KYB")
CLEAR_AML_PASSED = passed_prerequisite("AML")
CLEAR_SANCTIONS_PASSED = passed_prerequisite("SANCTIONS")


@dataclass(frozen=True)
class ClearPolicy:
    """What the prerequisites' two ambiguous phrases mean.

    The contract states the four prerequisites; it does not define "pending" or "answered".
    Those meanings are fields here rather than literals inside
    :func:`evaluate_clear_prerequisites`, so the answers live in one value that a test
    can vary — which is what let the mechanism be built and tested while those
    meanings were still open, and what makes a future change to any of them a
    one-line change.
    """

    pending_verification_statuses: frozenset[str]
    """Which ``VerificationInput.status`` values count as "still pending"."""

    placeholder_counts_as_pending: bool
    """Whether a result created without a provider (``is_placeholder``) is pending."""

    answered_screening_statuses: frozenset[str]
    """Which ``ScreeningItemInput.status`` values count as "answered"."""

    evidence_required: bool
    """Whether "evidence recorded" means at least one pinned id."""

    concluding_review_statuses: frozenset[str] = frozenset()
    """Which ``latest_review_status`` values mean a human has finished with a
    result whose ``status`` alone would count as pending.

    Needed because a review never changes ``status``: ``VerificationService.review``
    records ``review_status`` and leaves a ``REVIEW`` result at ``REVIEW`` for ever.
    Without this, a result compliance had already accepted would block ``CLEAR``
    permanently. Empty (the default) is the strictest reading: no review concludes
    anything. A placeholder row is never concluded by a review — nothing ran."""

    required_passed_types: tuple[str, ...] = ()
    """The passed-checks rule — the verification types that must each have
    **passed** in the current cycle, in the order a refusal names them. "Passed" means
    ``compliance_facts.check_state`` is ``PASSED``: the latest real result of
    that type is ``PASSED``, or ``REVIEW`` with an ``ACCEPTED`` review; placeholders
    never count. A set in meaning; a tuple so the refusal's order is stable. Empty (the
    default) requires none, which is the rule before 1 October 2026."""


#: **The settled CLEAR rule, decided 28 September 2026** (recorded with the decider
#: in ``docs/contracts/background-check.md`` §14).
#:
#: The prerequisites are exactly the contract's four, and no others.
CLEAR_POLICY = ClearPolicy(
    # A check is pending unless it reached a terminal answer with a real provider.
    # `REVIEW` means a human has not finished; a placeholder row means nothing ever ran.
    pending_verification_statuses=frozenset({"PENDING", "REVIEW"}),
    placeholder_counts_as_pending=True,
    # Clarified 28 September 2026: `REVIEW` blocks while
    # "a human has not finished with it". A human has finished once the result has an
    # `ACCEPTED` or `REJECTED` review — the answer compliance then weighs, exactly as
    # it weighs a `FAILED` result. `ESCALATED` is not finished, so it still blocks.
    concluding_review_statuses=frozenset({"ACCEPTED", "REJECTED"}),
    # "Answered" means answered satisfactorily. A `FAILED` item blocks `CLEAR` —
    # a company with a failed screening item is `FLAGGED`, which is what that state is
    # for (architecture §3.3). `NEEDS_REVIEW` and a never-recorded item also block.
    answered_screening_statuses=frozenset({"PASSED", "EXEMPT"}),
    # A cleared company must rest on something recorded.
    evidence_required=True,
    # The passed-checks rule (1 October 2026): KYB, AML and sanctions each
    # passed in the current cycle.
    required_passed_types=("KYB", "AML", "SANCTIONS"),
)


@dataclass(frozen=True)
class ClearPrerequisites:
    """The result of the rule: which prerequisites are unmet, in a stable order."""

    unmet: tuple[str, ...] = field(default_factory=tuple)

    @property
    def met(self) -> bool:
        return not self.unmet


def evaluate_clear_prerequisites(
    inputs: CompanyComplianceInputs,
    *,
    risk: BackgroundCheckRisk | None,
    evidence: EvidenceSelection,
    policy: ClearPolicy = CLEAR_POLICY,
) -> ClearPrerequisites:
    """The four prerequisites for ``IN_REVIEW → CLEAR``, as one pure function.

    Pure over ``CompanyComplianceInputs`` plus the decision's own inputs (the risk the
    actor gave and the evidence about to be pinned), so it is unit-testable with no
    database and no session — which is the point of the seam returning facts rather
    than judgements (``background-check.md`` §12.1 invariant 1).

    **The prerequisites are the contract's; their precise meaning was** settled 28
    September 2026 and is carried by ``policy``. Returns every unmet prerequisite rather
    than the first, so a refusal can name them all (contract §13).
    """
    unmet: list[str] = []

    # 1. "risk rating" — settled: required on CLEAR (contract §7).
    if risk is None:
        unmet.append(CLEAR_RISK_REQUIRED)

    # 2. "no checks still pending" — the policy supplies what pending means. A status that
    #    reads as pending is concluded by a finishing review; a placeholder never is.
    if any(
        (
            check.status in policy.pending_verification_statuses
            and check.latest_review_status not in policy.concluding_review_statuses
        )
        or (policy.placeholder_counts_as_pending and check.is_placeholder)
        for check in inputs.verifications
    ):
        unmet.append(CLEAR_NO_CHECKS_PENDING)

    # 3. "all eight screening items answered" — the catalogue is the seam's, so the
    #    count is never hard-coded here; the policy supplies what answered means.
    answered = {
        item.item_key
        for item in inputs.screening_items
        if item.status in policy.answered_screening_statuses
    }
    if any(key not in answered for key in inputs.screening_catalogue):
        unmet.append(CLEAR_SCREENING_ANSWERED)

    # 4. "evidence recorded" — the policy supplies what counts.
    if policy.evidence_required and evidence.count == 0:
        unmet.append(CLEAR_EVIDENCE_RECORDED)

    # 5. Rule B — each required type passed in the current cycle (the seam is already
    #    scoped to it), named one by one so the refusal says which is missing.
    for required in required_check_states(inputs, policy):
        if required.state != "PASSED":
            unmet.append(passed_prerequisite(required.verification_type))

    return ClearPrerequisites(unmet=tuple(unmet))


@dataclass(frozen=True)
class RequiredCheckState:
    """One verification type the passed-checks rule requires, and where it stands in the current cycle
    — served by the background-check read so the screen keeps no list of its own."""

    verification_type: str
    state: CheckState


def required_check_states(
    inputs: CompanyComplianceInputs, policy: ClearPolicy = CLEAR_POLICY
) -> tuple[RequiredCheckState, ...]:
    """Each of ``policy.required_passed_types`` with its check state, in policy order."""
    return tuple(
        RequiredCheckState(
            verification_type=verification_type,
            state=check_state(inputs.verifications, verification_type),
        )
        for verification_type in policy.required_passed_types
    )


__all__ = [
    "CLEAR_AML_PASSED",
    "CLEAR_KYB_PASSED",
    "CLEAR_RULES_V3",
    "CLEAR_SANCTIONS_PASSED",
    "PROPOSAL_APPROVE",
    "PROPOSAL_OPEN",
    "PROPOSAL_REJECT",
    "PROPOSAL_WITHDRAW",
    "BackgroundCheckProposalView",
    "RequiredCheckState",
    "inputs_fingerprint",
    "passed_prerequisite",
    "proposal_actions",
    "required_check_states",
    "CLEAR_RULES_V1",
    "CLEAR_RULES_V2",
    "CURRENT_CLEAR_RULES",
    "effective_rules_version",
    "CLEAR_EVIDENCE_RECORDED",
    "CLEAR_NO_CHECKS_PENDING",
    "CLEAR_RISK_REQUIRED",
    "CLEAR_SCREENING_ANSWERED",
    "CLEAR_POLICY",
    "SERVABLE_SCAN_STATUS",
    "BackgroundCheckCycleAction",
    "BackgroundCheckDecisionView",
    "BackgroundCheckMove",
    "ClearPolicy",
    "DocumentInput",
    "ClearPrerequisites",
    "EvidenceItemView",
    "EvidenceSelection",
    "evaluate_clear_prerequisites",
    "select_evidence",
]
