"""Read-model views and the pure decision rules for the background check —
**owner: Developer 4A** (L4-03, L4-06, L4-08; ``docs/contracts/background-check.md``).

Pure data structures and pure functions — no I/O, no session — the same pattern as
``deal_views.py`` and ``engagement_views.py``. ``BackgroundCheckService`` assembles
the views and calls the rules.

Two things live here, and both are here for the same reason:

- **The view types** the service returns and (phase 4A-7) the router serialises.
- **The ``CLEAR`` prerequisite rule**, as one pure function over
  ``CompanyComplianceInputs`` plus the decision's own inputs. The task requires the
  rule to be one function rather than conditions spread through repository queries
  (``4a-task.md`` §5.6), so that when D1–D3 are answered exactly one function and its
  unit tests change.

**The prerequisite rule is parameterised.** A3 fixes *which* four prerequisites
exist; D1–D3 fix what two of its phrases mean ("pending", "answered") and D4 what
"evidence recorded" covers. Those meanings are ``ClearPolicy`` fields rather than
literals in the rule body, so an answer is one value rather than a scattered edit.
**D1–D4 were decided on 28 September 2026** and ``CLEAR_POLICY`` carries them;
``docs/contracts/background-check.md`` §14 records each answer and who made it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.onboarding.domain.compliance_inputs import CompanyComplianceInputs
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)

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
    uuid with no foreign key and is ``None`` until Dev4B's 4B-2 lands (contract §6.1)."""

    screening_items: tuple[uuid.UUID, ...] = ()
    """``screening_review_item.id`` of every catalogue item that has a recorded row.
    An item never answered has no row to pin, so it contributes nothing."""

    documents: tuple[uuid.UUID, ...] = ()
    """``crm_document.id`` of the company's own documents that passed the scan gate
    (**D4, settled 28 September 2026**). Deal paperwork is not pinned: it belongs to
    the deal, not to the company's standing."""

    @property
    def count(self) -> int:
        return len(self.verifications) + len(self.screening_items) + len(self.documents)


@dataclass(frozen=True)
class DocumentInput:
    """One of the company's documents, as the evidence rule sees it.

    Deliberately not the ``CrmDocument`` entity: the rule stays pure and unit-testable
    without the ORM, and Developer 3B's row shape can change without touching this.
    """

    document_id: uuid.UUID
    scan_status: str  # DocumentScanStatus value


#: **D4, settled 28 September 2026.** Only a document that passed the scan gate is
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

    Pins the verification results, the screening rows, and — **D4, settled 28
    September 2026** — the company's own ``AVAILABLE`` documents. The caller supplies
    the document list so this function stays pure; applying D4's scan-status rule
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


# ── The CLEAR prerequisite rule ──────────────────────────────────────────────

#: The four prerequisite names A3 fixes. Returned verbatim to the caller so a
#: refusal names each unmet one (contract §13).
CLEAR_RISK_REQUIRED = "risk_rating"
CLEAR_NO_CHECKS_PENDING = "no_checks_pending"
CLEAR_SCREENING_ANSWERED = "screening_items_answered"
CLEAR_EVIDENCE_RECORDED = "evidence_recorded"


@dataclass(frozen=True)
class ClearPolicy:
    """What A3's two ambiguous phrases mean.

    A3 states the four prerequisites; it does not define "pending" or "answered".
    Those meanings are fields here rather than literals inside
    :func:`evaluate_clear_prerequisites`, so the answers live in one value that a test
    can vary — which is what let the mechanism be built and tested while D2–D4 were
    still open, and what makes a future change to any of them a one-line change.
    """

    pending_verification_statuses: frozenset[str]
    """D2 — which ``VerificationInput.status`` values count as "still pending"."""

    placeholder_counts_as_pending: bool
    """D2 — whether a result created without a provider (``is_placeholder``) is pending."""

    answered_screening_statuses: frozenset[str]
    """D3 — which ``ScreeningItemInput.status`` values count as "answered"."""

    evidence_required: bool
    """D4 — whether "evidence recorded" means at least one pinned id."""


#: **The settled CLEAR rule — D1, D2, D3 and D4, decided 28 September 2026** (recorded
#: with the decider in ``docs/contracts/background-check.md`` §14).
#:
#: D1: the prerequisites are exactly A3's four, and no others.
CLEAR_POLICY = ClearPolicy(
    # D2: a check is pending unless it reached a terminal answer with a real provider.
    # `REVIEW` means a human has not finished; a placeholder row means nothing ever ran.
    pending_verification_statuses=frozenset({"PENDING", "REVIEW"}),
    placeholder_counts_as_pending=True,
    # D3: "answered" means answered satisfactorily. A `FAILED` item blocks `CLEAR` —
    # a company with a failed screening item is `FLAGGED`, which is what that state is
    # for (architecture §3.3). `NEEDS_REVIEW` and a never-recorded item also block.
    answered_screening_statuses=frozenset({"PASSED", "EXEMPT"}),
    # D4: a cleared company must rest on something recorded.
    evidence_required=True,
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
    """A3's four prerequisites for ``IN_REVIEW → CLEAR``, as one pure function.

    Pure over ``CompanyComplianceInputs`` plus the decision's own inputs (the risk the
    actor gave and the evidence about to be pinned), so it is unit-testable with no
    database and no session — which is the point of the seam returning facts rather
    than judgements (§6.2 invariant 1).

    **The prerequisites are A3's; their precise meaning is D1–D4**, settled 28
    September 2026 and carried by ``policy``. Returns every unmet prerequisite rather
    than the first, so a refusal can name them all (contract §13).
    """
    unmet: list[str] = []

    # 1. "risk rating" — settled: required on CLEAR (contract §7).
    if risk is None:
        unmet.append(CLEAR_RISK_REQUIRED)

    # 2. "no checks still pending" — D2 supplies what pending means.
    if any(
        check.status in policy.pending_verification_statuses
        or (policy.placeholder_counts_as_pending and check.is_placeholder)
        for check in inputs.verifications
    ):
        unmet.append(CLEAR_NO_CHECKS_PENDING)

    # 3. "all eight screening items answered" — the catalogue is the seam's, so the
    #    count is never hard-coded here; D3 supplies what answered means.
    answered = {
        item.item_key
        for item in inputs.screening_items
        if item.status in policy.answered_screening_statuses
    }
    if any(key not in answered for key in inputs.screening_catalogue):
        unmet.append(CLEAR_SCREENING_ANSWERED)

    # 4. "evidence recorded" — D4 supplies what counts.
    if policy.evidence_required and evidence.count == 0:
        unmet.append(CLEAR_EVIDENCE_RECORDED)

    return ClearPrerequisites(unmet=tuple(unmet))


__all__ = [
    "CLEAR_EVIDENCE_RECORDED",
    "CLEAR_NO_CHECKS_PENDING",
    "CLEAR_RISK_REQUIRED",
    "CLEAR_SCREENING_ANSWERED",
    "CLEAR_POLICY",
    "SERVABLE_SCAN_STATUS",
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
