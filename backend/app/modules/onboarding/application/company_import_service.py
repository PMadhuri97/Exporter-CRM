"""``CompanyImportService`` — bulk import of companies from a CSV or Excel file.

**The template** is ``TEMPLATE_COLUMNS``, one header row. It is offered as CSV and
as an Excel workbook (``company_import_template.py``), and either kind of file is
accepted back: a ``.csv`` in UTF-8, or an ``.xlsx`` whose *Companies* sheet holds
the header and rows. A file that cannot be read, has a header other than an
accepted set of columns, or holds more than ``MAX_ROWS`` rows is refused as a
whole, and all of that is checked before any row is saved.

**Two headers are accepted**. ``website`` left the
template, but a file somebody downloaded before that release still carries the
column, and this importer refuses any header it does not recognise — so a
header carrying ``website`` is still read, and the column's values are
**ignored**. Nothing else about such a row changes. ``_ACCEPTED_HEADERS`` holds
both spellings; drop the retired one once no such file is in circulation. ``gstins`` holds several GSTINs separated by ``;``. There is
deliberately no column for who owns or entered a company: the signed-in user
is the actor, and ownership is not imported.

**Names are accepted where a person would pick one.** ``country`` may be the ISO
code or the country's name (the Excel template's dropdown offers names), and
``source`` may be the code or its label ("Existing customer"). Both are turned into
the code before any rule sees them, so the rules are the same either way.

**Each row is judged by the CRM's own rules**, never file-only ones: identity
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
committing, which is not assumed here. A later
row in the same file therefore sees earlier rows' companies: a second row with
the same PAN is ``matched`` to the first.

New companies start as ``LEAD``. Import never qualifies a company, never makes
one a ``CUSTOMER``, and needs no background check, conversation or deal.

**Preview** (``preview_file``) reads a file exactly as the import would — the same
reader, the same header rules — and reports its columns, its first rows and what is
wrong with its header, without judging or saving any row. It is what the import
screen shows before the person presses Import.
"""

from __future__ import annotations

import csv
import io
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

import structlog
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_matching import CompanyMatcher
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.company_identity import (
    normalise_registration_number,
    require_foreign_registration_number,
)
from app.modules.onboarding.domain.company_intake import MatchKind, Reason, check_identity
from app.modules.onboarding.domain.countries import country_code_for
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.exceptions import DuplicatePanError
from app.shared.exceptions import AnerBaseException, ValidationError

logger = structlog.get_logger(__name__)

#: Columns every file must carry. A file missing one is refused whole: a header
#: is cheap to fix, and importing a thousand rows with a column silently absent
#: is not.
_REQUIRED_COLUMNS: tuple[str, ...] = (
    "name", "country", "pan", "gstins", "iec", "cin", "source", "industry",
)

#: Columns a file may carry. ``registration_number`` is newer than the template and
#: optional rather than required, so a file written against the older template
#: still imports — the rule that actually matters (a foreign company carries a
#: registration number) is enforced per row, where it can name the row.
_OPTIONAL_COLUMNS: tuple[str, ...] = ("registration_number",)

#: Columns the template used to carry, still read and **ignored**
#: (module docstring).
_RETIRED_COLUMNS: tuple[str, ...] = ("website",)

#: What the downloaded template offers: everything a file may usefully carry.
TEMPLATE_COLUMNS: tuple[str, ...] = _REQUIRED_COLUMNS + _OPTIONAL_COLUMNS
TEMPLATE_CSV = ",".join(TEMPLATE_COLUMNS) + "\r\n"

#: Every column this importer recognises at all.
_KNOWN_COLUMNS: frozenset[str] = frozenset(
    _REQUIRED_COLUMNS + _OPTIONAL_COLUMNS + _RETIRED_COLUMNS
)

#: Most data rows one file may hold. Rows are matched and saved one by one
#: inside a single request, measured at about 46 ms a row on the app's pooled
#: engine, so 1,000 rows (the size the plan asks for) finish in about a minute;
#: 5,000 would run for about four, past a typical proxy timeout, leaving the
#: user an error while rows kept saving. A larger file needs a background job.
MAX_ROWS = 1000
#: How far down a workbook's sheet is read at all — blank rows included — before the
#: file is refused: past what any real list of companies needs.
_XLSX_MAX_SHEET_ROWS = 50 * MAX_ROWS

#: The sheet of an Excel file that holds the companies. A workbook with a single
#: sheet is read whatever that sheet is called.
COMPANIES_SHEET = "Companies"

#: Rows a preview shows.
PREVIEW_ROWS = 10

#: Sources a row may give, with the label a person sees. RXIL companies arrive
#: through the partner intake, and DEAL_BUYER companies through the buyer-company
#: path, which creates them outside the pipeline. An import creates leads, so
#: neither is a source it can claim. The labels match the New company form's.
IMPORT_SOURCE_LABELS: dict[ExporterSource, str] = {
    ExporterSource.MANUAL: "Manual entry",
    ExporterSource.SALES: "Sales",
    ExporterSource.REFERRAL: "Referral",
    ExporterSource.PARTNER: "Partner",
    ExporterSource.API: "API",
    ExporterSource.BROKER: "Broker",
    ExporterSource.EVENT: "Event",
    ExporterSource.EXISTING_CUSTOMER: "Existing customer",
}

_SOURCES_BY_SPELLING: dict[str, ExporterSource] = {
    **{source.value.casefold(): source for source in IMPORT_SOURCE_LABELS},
    **{label.casefold(): source for source, label in IMPORT_SOURCE_LABELS.items()},
}


@dataclass
class RowResult:
    #: The row's line in the file (the header is line 1), so an operator can
    #: find it. For an Excel file it is the sheet's row number.
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


@dataclass
class ParsedFile:
    """A file as read: its header, and every non-blank data row with its line.

    A row is a mapping of column to cell text, like ``csv.DictReader`` gives;
    cells past the header's last column sit under the key ``None``. A workbook's
    rows past what an import can take are counted (``uncollected``) but not kept."""

    header: list[str]
    rows: list[tuple[int, dict]]
    uncollected: int = 0

    @property
    def total_rows(self) -> int:
        return len(self.rows) + self.uncollected


@dataclass
class PreviewRow:
    line: int
    cells: list[str]


@dataclass
class ImportPreview:
    columns: list[str]
    rows: list[PreviewRow]
    total_rows: int
    missing_columns: list[str]
    unknown_columns: list[str]
    duplicate_columns: list[str]
    max_rows: int

    @property
    def ready(self) -> bool:
        """Whether the import would read this file at all (each row is still
        judged on its own when it is imported)."""
        return not (
            self.missing_columns
            or self.unknown_columns
            or self.duplicate_columns
            or self.total_rows > self.max_rows
        )


class CompanyImportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def import_file(
        self, file_name: str | None, content: bytes, *, actor_id: str | None
    ) -> ImportReport:
        """Import an uploaded file, CSV or Excel (``read_file``)."""
        return await self._import_rows(_checked_rows(read_file(file_name, content)), actor_id)

    async def import_csv(self, lines: Iterable[str], *, actor_id: str | None) -> ImportReport:
        """Import a CSV file given as an iterable of text lines. Raises
        ``ValidationError`` for a file that cannot be imported at all;
        otherwise every row is in the report.

        The whole file is read and checked first — its encoding, its CSV
        shape, its header and the row limit — and only then is any row saved.
        Rows are committed one by one, so a file refused as a whole part-way
        through would leave the rows before that point saved behind an error
        that reports none of them; checking first means a refused file leaves
        nothing behind.
        """
        return await self._import_rows(_checked_rows(_read_csv(lines)), actor_id)

    async def _import_rows(
        self, rows: list[tuple[int, dict]], actor_id: str | None
    ) -> ImportReport:
        report = ImportReport()
        for line, raw in rows:
            report.rows.append(await self._import_row(line, raw, actor_id))

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
                Reason("MALFORMED_ROW", "The row has more cells than the template has columns")
            ])

        def cell(name: str) -> str | None:
            value = (raw.get(name) or "").strip()
            return value or None

        country = country_code_for(cell("country"))
        identity, reasons = check_identity(
            name=cell("name"),
            country=country,
            pan=cell("pan"),
            gstins=[g for g in (cell("gstins") or "").split(";") if g.strip()],
            iec=cell("iec"),
            cin=cell("cin"),
        )
        source = _source_for(cell("source"))
        if source is None:
            reasons.append(Reason(
                "INVALID_SOURCE",
                "Source must be one of: " + ", ".join(IMPORT_SOURCE_LABELS.values()),
            ))
        if len(cell("industry") or "") > 255:
            reasons.append(Reason("INVALID_INDUSTRY", "Industry must be at most 255 characters"))
        # A `website` column, if the file still has one, is neither checked nor
        # stored: a value that would once have rejected the row no longer
        # stops a company being imported.
        try:
            normalise_registration_number(cell("registration_number"))
            # The foreign-identity rule, checked here as well as in the service so the report
            # names the row and the column instead of failing it late. `country`
            # is the cell's own value rather than `identity`'s, which is
            # `None` when the identity itself did not pass.
            require_foreign_registration_number(
                country=country,
                pan=cell("pan"),
                registration_number=cell("registration_number"),
            )
        except ValidationError as exc:
            reasons.append(Reason("INVALID_REGISTRATION_NUMBER", exc.detail))
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
                Reason("INTERNAL_ERROR", "The row could not be saved; nothing from it was kept")
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
                    registration_number=cell("registration_number"),
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
            Reason("CONCURRENT_CHANGE", "The company changed while this row was being matched")
        ])


def preview_file(file_name: str | None, content: bytes) -> ImportPreview:
    """The file as the import would read it, without judging or saving a row.

    A file that cannot be read at all raises ``ValidationError``, exactly as the
    import would; a header problem or too many rows is reported, not raised, so
    the screen can show the file and point at what to fix."""
    parsed = read_file(file_name, content)
    missing, unknown, duplicate = _header_problems(parsed.header)
    return ImportPreview(
        columns=parsed.header,
        rows=[
            PreviewRow(
                line=line,
                cells=[raw.get(column) or "" for column in parsed.header]
                + [value for value in (raw.get(None) or []) if value],
            )
            for line, raw in parsed.rows[:PREVIEW_ROWS]
        ],
        total_rows=parsed.total_rows,
        missing_columns=missing,
        unknown_columns=unknown,
        duplicate_columns=duplicate,
        max_rows=MAX_ROWS,
    )


def read_file(file_name: str | None, content: bytes) -> ParsedFile:
    """Read an uploaded file: Excel when it is one (by its name or its first
    bytes), CSV otherwise. ``ValidationError`` for a file that cannot be read."""
    name = (file_name or "").lower()
    if name.endswith(".xls") or content.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValidationError(
            "This is an old-style Excel file (.xls). Save it as .xlsx or .csv and try again"
        )
    if name.endswith(".xlsx") or content.startswith(b"PK\x03\x04"):
        return _read_xlsx(content)
    return _read_csv(io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline=""))


def _source_for(value: str | None) -> ExporterSource | None:
    """The source a cell names, by code or label; blank means Manual entry."""
    if value is None:
        return ExporterSource.MANUAL
    spelling = value.strip().casefold()
    return _SOURCES_BY_SPELLING.get(spelling) or _SOURCES_BY_SPELLING.get(
        spelling.replace(" ", "_")
    )


def _header_problems(header: list[str]) -> tuple[list[str], list[str], list[str]]:
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    unknown = [c for c in header if c not in _KNOWN_COLUMNS]
    duplicate = sorted({c for c in header if header.count(c) > 1})
    return missing, unknown, duplicate


def _checked_rows(parsed: ParsedFile) -> list[tuple[int, dict]]:
    """The rows of a file whose header and size the import accepts, or
    ``ValidationError`` naming what to fix."""
    if any(_header_problems(parsed.header)):
        # One message naming the template, whichever way the header is wrong:
        # the fix is the same, and listing the retired column as "accepted"
        # would invite people to keep filling it in.
        raise ValidationError(
            "The file's header must be exactly the template's columns: "
            + ", ".join(TEMPLATE_COLUMNS)
        )
    if parsed.total_rows > MAX_ROWS:
        raise ValidationError(f"A file may hold at most {MAX_ROWS} rows")
    return parsed.rows


def _read_csv(lines: Iterable[str]) -> ParsedFile:
    """Every non-blank data row with its line number, or ``ValidationError``
    for a file that cannot be read at all. Reads the whole file, so an
    encoding or CSV error anywhere in it surfaces before any row is saved."""
    reader = csv.DictReader(lines)
    try:
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        rows: list[tuple[int, dict]] = []
        for raw in reader:
            if not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
                continue  # a blank line
            rows.append((reader.line_num, raw))
    except UnicodeDecodeError as exc:
        raise ValidationError("The file must be UTF-8 text") from exc
    except csv.Error as exc:
        # `line_num` does not yet count the line being parsed when it fails.
        raise ValidationError(
            f"The file is not valid CSV near line {reader.line_num + 1}: {exc}"
        ) from exc
    return ParsedFile(header=header, rows=rows)


def _read_xlsx(content: bytes) -> ParsedFile:
    """The *Companies* sheet of an Excel workbook (or its only sheet), read like a
    CSV: the first row is the header, blank rows are skipped, and each row keeps
    its sheet row number.

    A small upload can unpack into a vast sheet, so only the rows an import could take
    (and one more) are kept; the rest are counted, and a sheet longer than
    ``_XLSX_MAX_SHEET_ROWS`` is refused without reading on."""
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise ValidationError("The file is not a readable Excel workbook (.xlsx)") from exc
    try:
        if COMPANIES_SHEET in workbook.sheetnames:
            sheet = workbook[COMPANIES_SHEET]
        elif len(workbook.sheetnames) == 1:
            sheet = workbook.worksheets[0]
        else:
            raise ValidationError(
                f"The workbook has no '{COMPANIES_SHEET}' sheet. Use the template, or "
                "keep the companies on a sheet with that name"
            )
        header: list[str] | None = None
        rows: list[tuple[int, dict]] = []
        uncollected = 0
        for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            if number > _XLSX_MAX_SHEET_ROWS:
                raise ValidationError(f"A file may hold at most {MAX_ROWS} rows")
            cells = _trimmed([_cell_text(value) for value in values])
            if header is None:
                header = [c.strip() for c in cells]
                continue
            if not any(c.strip() for c in cells):
                continue  # a blank row
            if len(rows) > MAX_ROWS:
                uncollected += 1
                continue
            raw: dict = {column: (cells[i] if i < len(cells) else "") for i, column in enumerate(header)}
            extra = [c for c in cells[len(header):] if c.strip()]
            if extra:
                raw[None] = extra
            rows.append((number, raw))
    finally:
        workbook.close()
    return ParsedFile(header=header or [], rows=rows, uncollected=uncollected)


def _trimmed(cells: list[str]) -> list[str]:
    """Cells without the empty ones after the last value (a sheet's row often
    runs on past its data)."""
    end = len(cells)
    while end and not cells[end - 1].strip():
        end -= 1
    return cells[:end]


def _cell_text(value: object) -> str:
    """A cell as the text a CSV would carry. A whole number Excel stored as a
    number (an IEC typed into a number-formatted cell) loses no ``.0``; a date
    becomes its ISO form."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


__all__ = [
    "COMPANIES_SHEET",
    "IMPORT_SOURCE_LABELS",
    "MAX_ROWS",
    "TEMPLATE_COLUMNS",
    "TEMPLATE_CSV",
    "CompanyImportService",
    "ImportPreview",
    "ImportReport",
    "preview_file",
    "read_file",
]
