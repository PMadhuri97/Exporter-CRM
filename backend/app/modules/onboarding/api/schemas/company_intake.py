"""Response schemas for RXIL intake and bulk import — **owner: Developer 2**
(L2-12, L2-13)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.modules.onboarding.application.company_import_service import ImportReport, RowResult
from app.modules.onboarding.application.company_intake_service import IntakeResult
from app.modules.onboarding.domain.company_intake import Reason


class ReasonResponse(BaseModel):
    """Machine-readable `code`, human-readable `message`."""

    code: str
    message: str

    @classmethod
    def of(cls, reason: Reason) -> ReasonResponse:
        return cls(code=reason.code, message=reason.message)


class IntakeResponse(BaseModel):
    customer_id: uuid.UUID
    #: `created` or `matched`.
    company: str
    #: `recorded`, or `already_qualified` when the company was qualified before.
    qualification: str
    #: True when this exact delivery had already been processed.
    replayed: bool
    warnings: list[ReasonResponse]

    @classmethod
    def of(cls, result: IntakeResult) -> IntakeResponse:
        return cls(
            customer_id=result.customer_id,
            company=result.company,
            qualification=result.qualification,
            replayed=result.replayed,
            warnings=[ReasonResponse.of(w) for w in result.warnings],
        )


class ImportRowResponse(BaseModel):
    #: The row's line in the file; the header is line 1.
    line: int
    #: `accepted`, `rejected` or `possible_duplicate`.
    status: str
    #: `created` or `matched`, for an accepted row.
    action: str | None
    customer_id: uuid.UUID | None
    reasons: list[ReasonResponse]
    warnings: list[ReasonResponse]
    #: Existing companies the row matched ambiguously or conflicted with.
    candidates: list[uuid.UUID]

    @classmethod
    def of(cls, row: RowResult) -> ImportRowResponse:
        return cls(
            line=row.line,
            status=row.status,
            action=row.action,
            customer_id=row.customer_id,
            reasons=[ReasonResponse.of(r) for r in row.reasons],
            warnings=[ReasonResponse.of(w) for w in row.warnings],
            candidates=list(row.candidates),
        )


class ImportReportResponse(BaseModel):
    total_rows: int
    accepted: int
    created: int
    matched: int
    rejected: int
    possible_duplicates: int
    rows: list[ImportRowResponse]

    @classmethod
    def of(cls, report: ImportReport) -> ImportReportResponse:
        return cls(
            total_rows=report.total_rows,
            accepted=report.accepted,
            created=report.created,
            matched=report.matched,
            rejected=report.rejected,
            possible_duplicates=report.possible_duplicates,
            rows=[ImportRowResponse.of(r) for r in report.rows],
        )
