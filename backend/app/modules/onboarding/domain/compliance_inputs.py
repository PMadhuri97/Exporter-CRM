"""The compliance-inputs contract (seam **v2**) between verification and screening
and the background check.

Pure data structures and one ``Protocol`` — no I/O, no session — the same pattern
as ``deal_views.py`` and ``engagement_views.py``.
``application/compliance_inputs.py::ComplianceInputsService`` implements the
Protocol.

The background check reads the inputs to a decision through this and
nothing else: the eight screening items and the verification results whose
subject is the company. It imports this module and the service; it never
reads or imports verification's tables, repositories or services directly
(``docs/contracts/background-check.md`` §12.1 invariant 6).

**Facts, not judgements.** Every field is a stored fact: a status, an id, a
timestamp. There is deliberately no ``is_clear_ready``, no "pending" verdict and
no "answered" verdict — what those mean is the background check's ``ClearPolicy``.
A judgement field here would be a contract change.

**The output shape is frozen** (§12.1 invariant 7). The reader may change how the
values are read; it may not add, remove, rename or retype a field without the
agreement of the seam's owner and its consumers.

Seam v2 — the one deliberate revision
-------------------------------------
Recorded in ``docs/contracts/background-check.md`` §12. Three fields were added, each
at the end of its type with a ``None`` default, so every v1 construction still builds:

* ``VerificationInput.cycle_id`` and ``ScreeningItemInput.cycle_id`` — the check cycle
  the row belongs to. A legacy row (``cycle_id IS NULL`` in the table) is reported with
  the company's **cycle 1** id: the read rule is applied here, once, so no consumer
  re-implements it. ``None`` only for a company that has no cycle row at all.
* ``CompanyComplianceInputs.current_cycle_id`` — the cycle the inputs are scoped to:
  the company's highest-numbered cycle, or ``None`` before it has one.

What the reads mean in v2:

* ``company_inputs(company_id)`` returns the inputs of the **current cycle** only. The
  argument is the *subject company*: the company the checks are about. Since checks
  became company-keyed that is ``subject_company_id = company_id`` (set on every company-subject result,
  and on a deal-buyer result the deal-buyer migration maps to a company), with a row
  recorded before then still found by ``entity_type = EXPORTER`` and
  ``entity_reference = company_id`` — a change to how the value is read, not to its
  shape. One set of checks per company, whatever role it plays in a deal.
* ``buyer_checks(deal_buyer_id)`` is **legacy**: it serves deals whose buyer is still a
  ``deal_buyer`` row, and is replaced by ``company_inputs(buyer_company_id)`` once a
  deal names a buyer company. Legacy buyers have no background check and
  no cycles, so its rows carry ``cycle_id = None``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class VerificationInput:
    """One ``verification_result`` row, as a decision may rely on it."""

    verification_result_id: uuid.UUID
    verification_type: str  # VerificationType value
    entity_type: str  # "EXPORTER" in company_inputs; "BUYER" in buyer_checks
    provider: str  # stored provider, verbatim
    status: str  # PENDING | PASSED | FAILED | REVIEW
    risk_level: str | None
    performed_at: datetime
    is_placeholder: bool  # created without a provider (e.g. normalized_result.stub)
    latest_review_id: uuid.UUID | None
    latest_review_status: str | None  # ACCEPTED | REJECTED | ESCALATED
    latest_reviewed_at: datetime | None
    evidence_document_ids: tuple[uuid.UUID, ...]
    #: v2: the cycle the result belongs to; a legacy row reports cycle 1's id.
    cycle_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ScreeningItemInput:
    """The latest recorded decision on one checklist item, or none."""

    item_key: str
    screening_review_item_id: uuid.UUID | None  # the latest row; None if never recorded
    status: str | None  # NEEDS_REVIEW | PASSED | FAILED | EXEMPT | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    #: v2: the cycle of the latest row; ``None`` when the item has no row this cycle.
    cycle_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CompanyComplianceInputs:
    """Everything company-scoped a background-check decision reads — for the current
    cycle only (v2)."""

    company_id: uuid.UUID
    screening_catalogue: tuple[str, ...]  # the catalogue keys, in display order
    screening_items: tuple[ScreeningItemInput, ...]  # exactly one per catalogue key, same order
    verifications: tuple[VerificationInput, ...]  # subject EXPORTER + this company, newest first
    #: v2: the cycle these inputs belong to; ``None`` before the company has a cycle.
    current_cycle_id: uuid.UUID | None = None


class ComplianceInputsReader(Protocol):
    """Read-only, in the caller's session: never commits, flushes, locks or writes.

    Errors (§12.1): an unknown company raises ``ExporterProfileNotFoundError``; an
    unknown ``deal_buyer_id`` raises ``ComplianceInputsBuyerNotFoundError`` (404);
    a company with no inputs is a valid empty value; database errors propagate.
    """

    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs:
        """The subject company's inputs in its current cycle (v2)."""
        ...

    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]:
        """Legacy: the checks on one ``deal_buyer`` row (v2 keeps it for old deals)."""
        ...


__all__ = [
    "CompanyComplianceInputs",
    "ComplianceInputsReader",
    "ScreeningItemInput",
    "VerificationInput",
]
