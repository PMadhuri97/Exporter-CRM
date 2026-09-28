"""The 4A ↔ 4B compliance-inputs contract — **owner: Developer 4B** (4B-0).

Pure data structures and one ``Protocol`` — no I/O, no session — the same pattern
as ``deal_views.py`` and ``engagement_views.py``.
``application/compliance_inputs.py::ComplianceInputsService`` implements the
Protocol.

Developer 4A reads the inputs to a background-check decision through this and
nothing else: the eight screening items and the verification results whose
subject is the company. Dev4A imports this module and the service; it never
reads or imports Dev4B's tables, repositories or services directly
(``docs/dev4/4b-task.md`` §6.4).

**Facts, not judgements.** Every field is a stored fact: a status, an id, a
timestamp. There is deliberately no ``is_clear_ready``, no "pending" verdict and
no "answered" verdict — what those mean is Dev4A's rule and decision gates D1–D3.
A judgement field here would be a contract change.

**The output shape is frozen** (§6.2 invariant 7). Dev4B may change how the
values are read; it may not add, remove, rename or retype a field without both
developers' written agreement in both task files (§6.4).
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


@dataclass(frozen=True)
class ScreeningItemInput:
    """The latest recorded decision on one checklist item, or none."""

    item_key: str
    screening_review_item_id: uuid.UUID | None  # the latest row; None if never recorded
    status: str | None  # NEEDS_REVIEW | PASSED | FAILED | EXEMPT | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class CompanyComplianceInputs:
    """Everything company-scoped a background-check decision reads."""

    company_id: uuid.UUID
    screening_catalogue: tuple[str, ...]  # the eight keys, in display order
    screening_items: tuple[ScreeningItemInput, ...]  # exactly one per catalogue key, same order
    verifications: tuple[VerificationInput, ...]  # subject EXPORTER + this company, newest first


class ComplianceInputsReader(Protocol):
    """Read-only, in the caller's session: never commits, flushes, locks or writes.

    Errors (§6.3): an unknown company raises ``ExporterProfileNotFoundError``; an
    unknown ``deal_buyer_id`` raises ``ComplianceInputsBuyerNotFoundError`` (404);
    a company with no inputs is a valid empty value; database errors propagate.
    """

    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs: ...

    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]: ...


__all__ = [
    "CompanyComplianceInputs",
    "ComplianceInputsReader",
    "ScreeningItemInput",
    "VerificationInput",
]
