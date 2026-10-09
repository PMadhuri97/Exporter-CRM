"""Response schemas for RXIL intake and bulk import."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.modules.onboarding.application.company_import_service import (
    ImportPreview,
    ImportReport,
    RowResult,
)
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


class ImportPreviewRowResponse(BaseModel):
    #: The row's line in the file (the sheet's row number for Excel); the header is line 1.
    line: int
    #: The row's cells in the header's order, then any cells past the last column.
    cells: list[str]


class ImportPreviewResponse(BaseModel):
    """A file as the import would read it, before any row is judged or saved."""

    #: The file's header, as written.
    columns: list[str]
    #: The first rows of the file.
    rows: list[ImportPreviewRowResponse]
    #: Every non-blank data row in the file.
    total_rows: int
    #: Template columns the header lacks.
    missing_columns: list[str]
    #: Header columns the template does not have.
    unknown_columns: list[str]
    #: Header columns given more than once.
    duplicate_columns: list[str]
    #: The most rows one file may hold.
    max_rows: int
    #: Whether the import would read this file at all. Each row is still judged on
    #: its own when it is imported.
    ready: bool

    @classmethod
    def of(cls, preview: ImportPreview) -> ImportPreviewResponse:
        return cls(
            columns=preview.columns,
            rows=[ImportPreviewRowResponse(line=r.line, cells=r.cells) for r in preview.rows],
            total_rows=preview.total_rows,
            missing_columns=preview.missing_columns,
            unknown_columns=preview.unknown_columns,
            duplicate_columns=preview.duplicate_columns,
            max_rows=preview.max_rows,
            ready=preview.ready,
        )
