"""Bulk CSV company import (L2-13).

Every row is judged by the CRM's own rules — the same identity checks, the
same matcher, the same creation service as a company entered by hand — and
lands in exactly one of accepted (created or matched), rejected or
possible_duplicate, with codes and messages.

Each test mints its own PANs, GSTINs, IECs and CINs, so runs never collide.
"""

from __future__ import annotations

import ast
import io
import time
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_COLUMNS,
    CompanyImportService,
)
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
MODULE = Path(__file__).resolve().parents[2]
HEADER = ",".join(TEMPLATE_COLUMNS)


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str, state: str = "27") -> str:
    return f"{state}{pan}1Z5"


def _iec() -> str:
    return uuid.uuid4().hex[:10].upper()


def _cin() -> str:
    return f"U17110MH2012PTC{uuid.uuid4().int % 10**6:06d}"


def _row(**cells) -> str:
    values = {"name": f"Import Co {uuid.uuid4().hex[:8]}", "country": "IN", **cells}
    return ",".join(str(values.get(col, "") or "") for col in TEMPLATE_COLUMNS)


def _csv(*rows: str) -> io.StringIO:
    return io.StringIO("\n".join((HEADER, *rows)) + "\n")


async def _import(*rows: str, actor_id: str = "importer-1"):
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyImportService(db).import_csv(_csv(*rows), actor_id=actor_id)


async def _company(**fields) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        profile, _ = await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES,
            name=fields.pop("name", f"Existing {uuid.uuid4().hex[:6]}"), country="IN", **fields
        )
    return profile


async def _count_with_pan(pan: str) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(ExporterProfile).where(ExporterProfile.pan == pan)
        )


def _codes(row) -> set[str]:
    return {r.code for r in row.reasons}


# ── The template ──────────────────────────────────────────────────────────────


async def test_the_template_is_served_and_has_every_identifier(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(f"{BASE}/imports/companies/template", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    columns = resp.text.strip().split(",")
    assert {"name", "country", "pan", "gstins", "iec", "cin"} <= set(columns)
    assert not {"actor_id", "created_by", "relationship_manager"} & set(columns)


@pytest.mark.parametrize(
    "header",
    [
        "name,country,pan",  # columns missing
        HEADER + ",actor_id",  # an uploaded actor is not accepted
        HEADER + ",relationship_manager",  # nor uploaded ownership
    ],
)
async def test_a_file_not_in_the_template_shape_is_refused_whole(header: str):
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await CompanyImportService(db).import_csv(
                io.StringIO(header + "\nX,IN\n"), actor_id="importer-1"
            )


# ── Accepted rows ─────────────────────────────────────────────────────────────


async def test_a_valid_row_creates_a_lead_through_the_normal_rules():
    pan, iec, cin = _pan(), _iec(), _cin()
    report = await _import(_row(
        name="Fresh Import Pvt Ltd", pan=pan.lower(), gstins=f"{_gstin(pan)};{_gstin(pan, '29')}",
        iec=iec, cin=cin, source="event", industry="Textiles",
    ))
    [row] = report.rows
    assert (row.status, row.action, row.line) == ("accepted", "created", 2)

    async with db_services.AsyncSessionLocal() as db:
        company = await ExporterProfileService(db)._require_profile(row.customer_id)
        history, _ = await HistoryService(db).list_for_company(row.customer_id)
    assert company.name == "Fresh Import Pvt Ltd"
    assert company.pan == pan  # normalised like a hand-entered PAN
    assert sorted(company.gstins) == sorted([_gstin(pan), _gstin(pan, "29")])
    assert (company.iec, company.cin, company.source) == (iec, cin, ExporterSource.EVENT)
    assert company.journey is ExporterJourney.LEAD  # imports start as leads
    assert company.qualification is QualificationState.NOT_YET_REVIEWED
    [created] = history
    assert (created.actor_id, created.event_metadata["source"]) == (
        "importer-1", "company_import.csv",
    )


async def test_a_row_whose_pan_exists_is_matched_not_duplicated():
    existing = await _company(pan=_pan())
    report = await _import(_row(name="Different Name Same PAN", pan=existing.pan))
    [row] = report.rows
    assert (row.status, row.action, row.customer_id) == ("accepted", "matched", existing.customer_id)
    assert await _count_with_pan(existing.pan) == 1

    async with db_services.AsyncSessionLocal() as db:
        company = await ExporterProfileService(db)._require_profile(existing.customer_id)
    assert company.name == existing.name  # a match changes nothing on the company


async def test_two_rows_with_one_pan_become_one_company():
    pan = _pan()
    report = await _import(_row(pan=pan), _row(pan=pan))
    first, second = report.rows
    assert (first.action, second.action) == ("created", "matched")
    assert first.customer_id == second.customer_id
    assert await _count_with_pan(pan) == 1


async def test_a_gstin_matches_through_the_pan_it_carries():
    existing = await _company(pan=_pan())
    report = await _import(_row(gstins=_gstin(existing.pan)))
    [row] = report.rows
    assert (row.action, row.customer_id) == ("matched", existing.customer_id)


async def test_iec_and_cin_agreeing_with_the_pan_match():
    iec, cin = _iec(), _cin()
    existing = await _company(pan=_pan(), iec=iec, cin=cin)
    report = await _import(_row(pan=existing.pan, iec=iec, cin=cin))
    [row] = report.rows
    assert (row.status, row.customer_id) == ("accepted", existing.customer_id)


async def test_a_gstin_held_elsewhere_is_a_warning_on_an_accepted_row():
    pan = _pan()
    holder = await _company(gstins=[_gstin(pan)])  # holds the GSTIN, has no PAN
    report = await _import(_row(pan=pan, gstins=_gstin(pan)))
    [row] = report.rows
    assert (row.status, row.action) == ("accepted", "created")
    [warning] = row.warnings
    assert warning.code == "GSTIN_HELD_BY_OTHER_COMPANY"
    assert str(holder.customer_id) in warning.message


# ── Rejected rows ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cells, code",
    [
        ({"pan": "ABCDE12345"}, "INVALID_PAN"),
        ({"gstins": "27ABCDE1234F1Z"}, "INVALID_GSTIN"),
        ({"pan": "AAAPL1234C", "gstins": "27ZZZPL9999Z1Z5"}, "GSTIN_PAN_MISMATCH"),
        ({"iec": "SHORT"}, "INVALID_IEC"),
        ({"cin": "X12345"}, "INVALID_CIN"),
        ({"name": " "}, "MISSING_NAME"),
        ({"country": ""}, "MISSING_COUNTRY"),
        ({"country": "India"}, "INVALID_COUNTRY"),
        ({"source": "RXIL"}, "INVALID_SOURCE"),
        ({"source": "CARRIER_PIGEON"}, "INVALID_SOURCE"),
    ],
)
async def test_invalid_values_are_rejected_with_a_code(cells: dict, code: str):
    report = await _import(_row(**cells))
    [row] = report.rows
    assert row.status == "rejected"
    assert code in _codes(row)
    assert all(reason.message for reason in row.reasons)
    assert row.customer_id is None


async def test_every_problem_in_a_row_is_reported_at_once():
    report = await _import(_row(name="", pan="BAD", iec="SHORT"))
    [row] = report.rows
    assert {"MISSING_NAME", "INVALID_PAN", "INVALID_IEC"} <= _codes(row)


async def test_identifiers_pointing_at_two_companies_are_rejected():
    a = await _company(pan=_pan())
    b = await _company(pan=_pan(), cin=_cin())
    report = await _import(_row(pan=a.pan, cin=b.cin))
    [row] = report.rows
    assert row.status == "rejected"
    assert "CONFLICTING_IDENTIFIERS" in _codes(row)
    assert set(row.candidates) == {a.customer_id, b.customer_id}


async def test_a_pan_whose_company_has_another_iec_is_rejected():
    existing = await _company(pan=_pan(), iec=_iec())
    report = await _import(_row(pan=existing.pan, iec=_iec()))
    [row] = report.rows
    assert row.status == "rejected"
    assert "CONFLICTING_IDENTIFIERS" in _codes(row)


# ── Possible duplicates ───────────────────────────────────────────────────────


async def test_a_shared_cin_without_a_pan_is_a_possible_duplicate():
    existing = await _company(cin=_cin())
    report = await _import(_row(cin=existing.cin))
    [row] = report.rows
    assert row.status == "possible_duplicate"
    assert "POSSIBLE_DUPLICATE" in _codes(row)
    assert row.candidates == [existing.customer_id]
    assert row.customer_id is None  # nothing created


async def test_several_resemblances_are_an_ambiguous_match():
    pan = _pan()
    first = await _company(gstins=[_gstin(pan)])
    second = await _company(gstins=[_gstin(pan)])
    report = await _import(_row(gstins=_gstin(pan)))
    [row] = report.rows
    assert row.status == "possible_duplicate"
    assert {"POSSIBLE_DUPLICATE", "AMBIGUOUS_MATCH"} <= _codes(row)
    assert set(row.candidates) == {first.customer_id, second.customer_id}


# ── The whole file ────────────────────────────────────────────────────────────


async def test_the_report_counts_every_outcome():
    existing = await _company(pan=_pan())
    lookalike = await _company(cin=_cin())
    report = await _import(
        _row(pan=_pan()),  # created
        _row(pan=existing.pan),  # matched
        _row(pan="BAD"),  # rejected
        _row(cin=lookalike.cin),  # possible duplicate
        "",  # a blank line is skipped, not counted
    )
    assert (report.total_rows, report.accepted, report.created, report.matched) == (4, 2, 1, 1)
    assert (report.rejected, report.possible_duplicates) == (1, 1)
    assert [r.line for r in report.rows] == [2, 3, 4, 5]


async def test_a_failing_row_cannot_damage_the_rows_around_it(monkeypatch):
    """Row 3's save blows up half-way. Rows 2 and 4 are saved complete; row 3
    leaves nothing behind — no company, no GSTIN, no history."""
    before_pan, broken_pan, after_pan = _pan(), _pan(), _pan()
    real_create = ExporterProfileService.create_or_get_profile

    async def create_but_break_one(self, customer_id, **kwargs):
        if kwargs.get("pan") == broken_pan:
            self._db.add(ExporterGstin(customer_id=customer_id, gstin=_gstin(broken_pan)))
            raise RuntimeError("disk full")
        return await real_create(self, customer_id, **kwargs)

    monkeypatch.setattr(ExporterProfileService, "create_or_get_profile", create_but_break_one)
    report = await _import(
        _row(pan=before_pan, gstins=_gstin(before_pan)),
        _row(pan=broken_pan, gstins=_gstin(broken_pan)),
        _row(pan=after_pan, gstins=_gstin(after_pan)),
    )
    monkeypatch.undo()

    first, broken, last = report.rows
    assert (first.status, last.status) == ("accepted", "accepted")
    assert broken.status == "rejected"
    assert _codes(broken) == {"INTERNAL_ERROR"}

    assert await _count_with_pan(before_pan) == 1
    assert await _count_with_pan(after_pan) == 1
    assert await _count_with_pan(broken_pan) == 0
    async with db_services.AsyncSessionLocal() as db:
        stray = await db.scalar(
            select(func.count()).select_from(ExporterGstin)
            .where(ExporterGstin.gstin == _gstin(broken_pan))
        )
        for row in (first, last):
            company = await ExporterProfileService(db)._require_profile(row.customer_id)
            assert len(company.gstins) == 1
            history, _ = await HistoryService(db).list_for_company(row.customer_id)
            assert len(history) == 1
    assert stray == 0


async def _import_on_the_apps_kind_of_engine(*rows: str):
    """Import on a pooled engine configured like the app's, created and
    disposed inside the test.

    The suite swaps the app's pooled engine for NullPool (`backend/conftest.py`),
    which opens a fresh connection for the first statement after every
    commit. Import commits once per row (decision U4 is open), so under
    NullPool a 1,000-row file spends most of its time connecting — measured at
    one connection and ~150 ms per row on a developer machine, against one
    connection in all at 46 ms per row pooled. A time budget measured on
    NullPool would be measuring the test harness, not the import. The pool is
    disposed before the test ends, so no idle pooled connection outlives it
    (the Windows problem conftest's NullPool avoids).
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )
    try:
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
        async with factory() as db:
            return await CompanyImportService(db).import_csv(_csv(*rows), actor_id="importer-1")
    finally:
        await engine.dispose()


# Its own budget below is 180s; the suite-wide 120s pytest-timeout would
# otherwise kill the whole run (thread method) on a slow machine first.
@pytest.mark.timeout(300)
async def test_a_representative_thousand_row_file():
    """900 new companies, 40 matches to existing ones, 30 rejects and 30
    possible duplicates, shuffled together."""
    existing = [await _company(pan=_pan()) for _ in range(40)]
    lookalikes = [await _company(cin=_cin()) for _ in range(30)]
    rows = (
        [_row(pan=(p := _pan()), gstins=_gstin(p), iec=_iec()) for _ in range(900)]
        + [_row(pan=c.pan) for c in existing]
        + [_row(pan="BAD" + str(i)) for i in range(30)]
        + [_row(cin=c.cin) for c in lookalikes]
    )
    order = sorted(range(len(rows)), key=lambda i: uuid.uuid5(uuid.NAMESPACE_OID, str(i)))
    rows = [rows[i] for i in order]
    assert len(rows) == 1000

    started = time.perf_counter()
    report = await _import_on_the_apps_kind_of_engine(*rows)
    elapsed = time.perf_counter() - started

    assert report.total_rows == 1000
    assert (report.created, report.matched) == (900, 40)
    assert (report.rejected, report.possible_duplicates) == (30, 30)
    assert elapsed < 180, f"1,000 rows took {elapsed:.0f}s"
    created_ids = [r.customer_id for r in report.rows if r.action == "created"]
    async with db_services.AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(func.count()).select_from(ExporterProfile)
            .where(ExporterProfile.customer_id.in_(created_ids))
        )
        not_leads = await db.scalar(
            select(func.count()).select_from(ExporterProfile)
            .where(
                ExporterProfile.customer_id.in_(created_ids),
                ExporterProfile.journey != ExporterJourney.LEAD,
            )
        )
    assert (saved, not_leads) == (900, 0)


# ── Dependencies ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "relative",
    ["application/company_import_service.py", "application/company_matching.py"],
)
async def test_import_needs_no_background_check_conversation_deal_or_legacy_table(relative: str):
    source = (MODULE / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(
        word in module
        for module in imported
        for word in ("onboarding_request", "screening", "verification", "engagement", "rxil")
    )
    for word in ("background_check", "CLEAR", "CUSTOMER"):
        assert word not in source.replace("``CUSTOMER``", "")


# ── Through the API ───────────────────────────────────────────────────────────


async def test_an_upload_is_imported_as_the_signed_in_user(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    content = "\n".join((HEADER, _row(pan=pan, gstins=_gstin(pan)))) + "\n"
    resp = await client.post(
        f"{BASE}/imports/companies",
        files={"file": ("companies.csv", content.encode("utf-8"), "text/csv")},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["total_rows"], body["created"]) == (1, 1)
    customer_id = body["rows"][0]["customer_id"]
    async with db_services.AsyncSessionLocal() as db:
        [created], _ = await HistoryService(db).list_for_company(uuid.UUID(customer_id))
    assert created.actor_id == str(user_id)


async def test_a_developer_cannot_import(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.DEVELOPER)
    resp = await client.post(
        f"{BASE}/imports/companies",
        files={"file": ("companies.csv", (HEADER + "\n").encode(), "text/csv")},
        headers=auth_header(token),
    )
    assert resp.status_code == 403


async def test_a_file_that_is_not_utf8_is_a_422(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.ADMIN)
    resp = await client.post(
        f"{BASE}/imports/companies",
        files={"file": ("companies.csv", b"\xff\xfe\x00bad", "text/csv")},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


# ── A file refused as a whole leaves nothing behind ───────────────────────────
#
# Rows are committed one by one, so a whole-file refusal that surfaced part-way
# through would leave the rows before it saved behind an error that reports
# none of them. The file is read and checked in full before any row is saved.


def _bytes_with_a_bad_byte_after(first_row: str) -> bytes:
    # Blank lines are skipped, not rows; they push the bad byte past the
    # decoder's first chunk, so it is only met after the first row was read.
    return (HEADER + "\n" + first_row + "\n" + "\n" * 20_000).encode() + b"Bad \xff Co,IN\n"


async def test_a_bad_byte_late_in_the_file_saves_nothing():
    pan = _pan()
    content = _bytes_with_a_bad_byte_after(_row(pan=pan))
    async with db_services.AsyncSessionLocal() as db:
        lines = io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline="")
        with pytest.raises(ValidationError, match="UTF-8"):
            await CompanyImportService(db).import_csv(lines, actor_id="importer-1")
    assert await _count_with_pan(pan) == 0


async def test_a_bad_byte_late_in_an_upload_is_a_422_that_saves_nothing(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.ADMIN)
    pan = _pan()
    resp = await client.post(
        f"{BASE}/imports/companies",
        files={"file": ("companies.csv", _bytes_with_a_bad_byte_after(_row(pan=pan)), "text/csv")},
        headers=auth_header(token),
    )
    assert resp.status_code == 422
    assert await _count_with_pan(pan) == 0


async def test_a_file_over_the_row_limit_saves_nothing(monkeypatch):
    from app.modules.onboarding.application import company_import_service

    monkeypatch.setattr(company_import_service, "MAX_ROWS", 2)
    pans = [_pan() for _ in range(3)]
    with pytest.raises(ValidationError, match="at most 2 rows"):
        await _import(*(_row(pan=p) for p in pans))
    assert [await _count_with_pan(p) for p in pans] == [0, 0, 0]


async def test_a_file_at_the_row_limit_is_imported(monkeypatch):
    from app.modules.onboarding.application import company_import_service

    monkeypatch.setattr(company_import_service, "MAX_ROWS", 2)
    report = await _import(_row(pan=_pan()), "", _row(pan=_pan()))  # the blank line is not a row
    assert report.created == 2


async def test_a_line_that_is_not_valid_csv_saves_nothing():
    import csv

    pan = _pan()
    previous = csv.field_size_limit(64)
    try:
        with pytest.raises(ValidationError, match="not valid CSV near line 3"):
            await _import(_row(pan=pan), _row(website="https://example.com/" + "x" * 100))
    finally:
        csv.field_size_limit(previous)
    assert await _count_with_pan(pan) == 0
