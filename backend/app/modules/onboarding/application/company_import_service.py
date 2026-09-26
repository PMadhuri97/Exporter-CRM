"""``CompanyImportService`` — bulk CSV import of companies (L2-13, assumption
A14). **Owner: Developer 2.**

**The template** is fixed: ``TEMPLATE_COLUMNS``, one header row, UTF-8. A
file whose header is not exactly those columns is refused as a whole before
any row is read. ``gstins`` holds several GSTINs separated by ``;``. There is
deliberately no column for who owns or entered a company: the signed-in user
is the actor, and ownership is not imported.

**Each row is judged by the CRM's own rules**, never CSV-only ones: identity
and tax IDs by ``check_identity`` (the same normalisers manual creation uses),
matching by ``CompanyMatcher`` (the same algorithm RXIL intake uses), creation
by ``ExporterProfileService.create_or_get_profile``. Every row ends in exactly
one status, with machine-readable codes and messages:

* ``accepted`` — ``created`` as a new ``LEAD``, or ``matched`` to the company
  its PAN already belongs to (nothing on that company is changed; the report
  names it). Warnings, such as a GSTIN another company also holds, ride along.
* ``rejected`` — invalid or missing values, or identifiers that point at
  different companies.
* ``possible_duplicate`` — shares identifiers with existing companies but no
  PAN confirms it; nothing is created, for a person to decide.

**Transactions: one per created row.** ``create_or_get_profile`` commits the
company, its GSTINs and its history row together, so each accepted row is
complete or absent — never half-written — and a row that fails later cannot
reach back into rows already committed. A failure inside a row rolls that row
back and is reported; the import carries on. This is the boundary the services
already provide: a whole-file transaction would need the services to stop
committing, which is the open decision U4 and is not assumed here. A later
row in the same file therefore sees earlier rows' companies: a second row with
the same PAN is ``matched`` to the first.

New companies start as ``LEAD``. Import never qualifies a company, never makes
one a ``CUSTOMER``, and needs no background check, conversation or deal.
"""

from __future__ import annotations

import csv
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_matching import CompanyMatcher
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.company_intake import MatchKind, Reason, check_identity
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.exceptions import DuplicatePanError
from app.shared.exceptions import AnerBaseException, ValidationError

logger = structlog.get_logger(__name__)

TEMPLATE_COLUMNS: tuple[str, ...] = (
    "name", "country", "pan", "gstins", "iec", "cin", "source", "industry", "website",
)
TEMPLATE_CSV = ",".join(TEMPLATE_COLUMNS) + "\r\n"

#: Most data rows one file may hold.
MAX_ROWS = 5000

#: Sources a row may give. `RXIL` companies arrive through RXIL intake only.
_IMPORTABLE_SOURCES = {s.value: s for s in ExporterSource if s is not ExporterSource.RXIL}


@dataclass
class RowResult:
    #: The row's line in the file (the header is line 1), so an operator can
    #: find it.
    line: int
    status: str  # accepted | rejected | possible_duplicate
    action: str | None = None  # created | matched, for accepted rows
    customer_id: uuid.UUID | None = None
    reasons: list[Reason] = field(default_factory=list)
    warnings: list[Reason] = field(default_factory=list)
    candidates: list[uuid.UUID] = field(default_factory=list)


@dataclass
class ImportReport:
    rows: list[RowResult] = field(default_factory=list)

    def _count(self, status: str, action: str | None = None) -> int:
        return sum(
            1 for r in self.rows if r.status == status and (action is None or r.action == action)
        )

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def accepted(self) -> int:
        return self._count("accepted")

    @property
    def created(self) -> int:
        return self._count("accepted", "created")

    @property
    def matched(self) -> int:
        return self._count("accepted", "matched")

    @property
    def rejected(self) -> int:
        return self._count("rejected")

    @property
    def possible_duplicates(self) -> int:
        return self._count("possible_duplicate")


class CompanyImportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def import_csv(self, lines: Iterable[str], *, actor_id: str | None) -> ImportReport:
        """Import a CSV file given as an iterable of text lines (a stream is
        read row by row, never whole). Raises ``ValidationError`` for a file
        that cannot be imported at all; otherwise every row is in the report."""
        reader = csv.DictReader(lines)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if tuple(sorted(header)) != tuple(sorted(TEMPLATE_COLUMNS)) or len(header) != len(set(header)):
            raise ValidationError(
                "the file's header must be exactly the template's columns: "
                + ", ".join(TEMPLATE_COLUMNS)
            )
        reader.fieldnames = header

        report = ImportReport()
        for raw in reader:
            if len(report.rows) >= MAX_ROWS:
                raise ValidationError(f"a file may hold at most {MAX_ROWS} rows")
            if not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
                continue  # a blank line
            report.rows.append(await self._import_row(reader.line_num, raw, actor_id))

        logger.info(
            "company_import.done",
            total=report.total_rows,
            created=report.created,
            matched=report.matched,
            rejected=report.rejected,
            possible_duplicates=report.possible_duplicates,
            actor_id=actor_id,
        )
        return report

    async def _import_row(self, line: int, raw: dict, actor_id: str | None) -> RowResult:
        if raw.get(None):  # more cells than the header has columns
            return RowResult(line, "rejected", reasons=[
                Reason("MALFORMED_ROW", "the row has more cells than the template has columns")
            ])

        def cell(name: str) -> str | None:
            value = (raw.get(name) or "").strip()
            return value or None

        identity, reasons = check_identity(
            name=cell("name"),
            country=cell("country"),
            pan=cell("pan"),
            gstins=[g for g in (cell("gstins") or "").split(";") if g.strip()],
            iec=cell("iec"),
            cin=cell("cin"),
        )
        source_value = (cell("source") or ExporterSource.MANUAL.value).upper()
        source = _IMPORTABLE_SOURCES.get(source_value)
        if source is None:
            reasons.append(Reason(
                "INVALID_SOURCE",
                f"source must be one of {sorted(_IMPORTABLE_SOURCES)} (RXIL companies arrive "
                "through RXIL intake)",
            ))
        for name, limit in (("industry", 255), ("website", 2048)):
            if len(cell(name) or "") > limit:
                reasons.append(Reason(f"INVALID_{name.upper()}", f"{name} is longer than {limit}"))
        if reasons:
            return RowResult(line, "rejected", reasons=reasons)
        assert identity is not None and source is not None

        try:
            return await self._place(line, identity, source, cell, actor_id)
        except AnerBaseException as exc:
            await self._db.rollback()
            return RowResult(
                line, "rejected", reasons=[Reason(exc.error_code or "REJECTED", exc.detail)]
            )
        except Exception:  # noqa: BLE001 — one bad row must not stop the file
            await self._db.rollback()
            logger.exception("company_import.row_failed", line=line)
            return RowResult(line, "rejected", reasons=[
                Reason("INTERNAL_ERROR", "the row could not be saved; nothing from it was kept")
            ])

    async def _place(self, line, identity, source, cell, actor_id) -> RowResult:
        for _attempt in range(2):
            match = await CompanyMatcher(self._db).match(identity)
            warnings = list(match.warnings)
            if match.kind is MatchKind.MATCHED:
                return RowResult(
                    line, "accepted", action="matched", customer_id=match.customer_id,
                    warnings=warnings,
                )
            if match.kind is MatchKind.CONFLICT:
                return RowResult(
                    line, "rejected", reasons=list(match.reasons),
                    candidates=list(match.candidates), warnings=warnings,
                )
            if match.kind is MatchKind.POSSIBLE_DUPLICATE:
                return RowResult(
                    line, "possible_duplicate", reasons=list(match.reasons),
                    candidates=list(match.candidates), warnings=warnings,
                )
            try:
                profile, _created = await ExporterProfileService(self._db).create_or_get_profile(
                    uuid.uuid4(),
                    source=source,
                    name=identity.name,
                    country=identity.country,
                    pan=identity.pan,
                    gstins=list(identity.gstins),
                    iec=identity.iec,
                    cin=identity.cin,
                    industry=cell("industry"),
                    website=cell("website"),
                    actor_id=actor_id,
                    history_source="company_import.csv",
                )
            except DuplicatePanError:
                await self._db.rollback()
                continue  # created by someone else meanwhile: match again
            return RowResult(
                line, "accepted", action="created", customer_id=profile.customer_id,
                warnings=warnings,
            )
        return RowResult(line, "rejected", reasons=[
            Reason("CONCURRENT_CHANGE", "the company changed while this row was being matched")
        ])


__all__ = ["MAX_ROWS", "TEMPLATE_COLUMNS", "TEMPLATE_CSV", "CompanyImportService", "ImportReport"]
