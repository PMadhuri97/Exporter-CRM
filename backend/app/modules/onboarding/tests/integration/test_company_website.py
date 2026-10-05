"""The company website is gone, and stored values survive it.

This file used to prove that every write path applied the one link rule
(``domain/web_links.py``) to ``exporter_profile.website``. There is no such write
path any more, so it proves the other half of the decision instead, which is the
half that can go wrong silently:

* **no write path accepts one** — the API refuses it rather than ignoring it, the
  CSV template has dropped the column, and an RXIL package's ``website`` is read
  and discarded;
* **no read path shows one**, for any role;
* **nothing was destroyed.** The column and every value already in it are still
  there, which is the actual instruction ("keep stored websites, hide them") and
  the one thing no amount of schema-level checking would catch.

The link rule itself still has a caller — a verification result's ``url``
evidence — covered by ``test_web_links.py`` and
``test_verification_integrity_rules.py``.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_COLUMNS,
    CompanyImportService,
)
from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


async def _companies_with_pan(pan: str) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(ExporterProfile).where(ExporterProfile.pan == pan)
        )


# ── The column and its values are still there ─────────────────────────────────


async def test_the_column_still_exists_and_a_stored_value_is_left_alone():
    """The decision is "keep stored websites, hide them", so the value a company
    had before this release must still be readable with SQL. Written with raw SQL
    on purpose: the ORM entity still maps the column, but a later cleanup that
    dropped it would make every *other* test in this file pass while quietly
    destroying data, and only this one would fail."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Legacy Website Co", country="IN"
        )
    async with db_services.AsyncSessionLocal() as db:
        # Stand in for a row written before the field retired. Nothing in the
        # application can put a value here any more, which is the point.
        await db.execute(
            text(
                "UPDATE onboarding.exporter_profile SET website = :w "
                "WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"w": "https://legacy.example", "c": str(customer_id)},
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalar(
            text(
                "SELECT website FROM onboarding.exporter_profile "
                "WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"c": str(customer_id)},
        )
    assert stored == "https://legacy.example"


async def test_no_response_carries_the_website_for_any_role(client: AsyncClient):
    """Hidden means hidden from the JSON, not just from the screen: a masked role
    reading the API directly is exactly the reader server-side masking exists for."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Hidden Website Co", country="IN"
        )
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE onboarding.exporter_profile SET website = :w "
                "WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"w": "https://hidden.example", "c": str(customer_id)},
        )
        await db.commit()

    for role in (UserRole.ADMIN, UserRole.COMPLIANCE, UserRole.OPERATIONS, UserRole.DEVELOPER):
        _user_id, token = await user_with_role(client, role)
        detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
        assert detail.status_code == 200, detail.text
        assert "website" not in detail.json(), role
        assert "hidden.example" not in detail.text, role

        listed = await client.get(
            f"{BASE}/exporters", params={"name": "Hidden Website Co"}, headers=auth_header(token)
        )
        assert listed.status_code == 200, listed.text
        assert "hidden.example" not in listed.text, role


# ── No write path accepts one ─────────────────────────────────────────────────


async def test_creating_a_company_with_a_website_is_refused(client: AsyncClient):
    """`extra="forbid"` on the request schema, so a client still sending the field
    is told rather than having the value silently dropped. The company is not
    created either — a 422 that half-worked would be worse than the field."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    resp = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": "Website Co",
            "country": "IN",
            "pan": pan,
            "website": "https://acme.example",
        },
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422, resp.text
    assert "website" in resp.text
    assert await _companies_with_pan(pan) == 0


async def test_editing_a_company_to_set_a_website_is_refused(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Edit Website Co", country="IN"
        )

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"website": "https://acme.example"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_clearing_a_website_is_refused_too(client: AsyncClient):
    """Sending `null` is a *write* — "clear this field" — and the field is no
    longer writable. It matters that this is refused rather than accepted as a
    no-op: accepting it would tell a client the clear had happened."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Clear Website Co", country="IN"
        )

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}", json={"website": None}, headers=auth_header(token)
    )
    assert resp.status_code == 422, resp.text


# ── CSV import: the old header still works, the column is ignored ─────────────


def _row(columns: tuple[str, ...], **cells) -> str:
    values = {"name": f"Import Co {uuid.uuid4().hex[:8]}", "country": "IN", **cells}
    return ",".join(str(values.get(col, "") or "") for col in columns)


async def test_the_template_no_longer_offers_a_website_column():
    assert "website" not in TEMPLATE_COLUMNS


async def test_a_csv_file_with_the_old_website_header_still_imports():
    """The acceptance criterion for the website's removal. A file somebody downloaded before
    this release still has the column, and the importer refuses any header it does
    not recognise — so an unrecognised one would reject the whole file, not one
    row."""
    pan = _pan()
    old_columns = TEMPLATE_COLUMNS + ("website",)
    csv_file = io.StringIO(
        "\n".join(
            (
                ",".join(old_columns),
                _row(old_columns, pan=pan, website="https://acme.example"),
            )
        )
        + "\n"
    )
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(csv_file, actor_id="importer-1")

    [row] = report.rows
    assert row.status == "accepted", row.reasons
    assert row.customer_id is not None
    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalar(
            text(
                "SELECT website FROM onboarding.exporter_profile "
                "WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"c": str(row.customer_id)},
        )
    # Read and discarded, not stored: the row imported, the value did not.
    assert stored is None


async def test_a_csv_row_whose_website_would_once_have_been_refused_now_imports():
    """A value the old importer rejected the row for (`INVALID_WEBSITE`) no longer
    stops a company being imported. "A missing website is never a failure"
    goes for a malformed one too, now that nothing renders it."""
    pan = _pan()
    old_columns = TEMPLATE_COLUMNS + ("website",)
    csv_file = io.StringIO(
        "\n".join(
            (
                ",".join(old_columns),
                _row(old_columns, pan=pan, website="javascript:alert(1)"),
            )
        )
        + "\n"
    )
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(csv_file, actor_id="importer-1")

    [row] = report.rows
    assert row.status == "accepted", row.reasons
    assert "INVALID_WEBSITE" not in {reason.code for reason in row.reasons}
    assert await _companies_with_pan(pan) == 1


async def test_a_header_with_an_unknown_column_is_still_refused():
    """The transition tolerates one named retired column, not any column: a
    misspelled header is still a whole-file error, as it was before."""
    columns = TEMPLATE_COLUMNS + ("web_site",)
    csv_file = io.StringIO(
        "\n".join((",".join(columns), _row(columns, pan=_pan()))) + "\n"
    )
    from app.shared.exceptions import ValidationError

    with pytest.raises(ValidationError, match="header"):
        async with db_services.AsyncSessionLocal() as db:
            await CompanyImportService(db).import_csv(csv_file, actor_id="importer-1")


# ── RXIL intake ───────────────────────────────────────────────────────────────


async def test_an_rxil_package_carrying_a_website_is_accepted_and_ignores_it():
    """"RXIL ignores `website` in the package". The format is provisional
    and partner-driven, so a value we no longer want must not fail the delivery —
    an exporter rejected over a field we stopped using would be a real company
    lost to a formatting detail."""
    pan = _pan()
    package = {
        "exporter": {
            "legal_name": f"RXIL Exporter {uuid.uuid4().hex[:8]}",
            "country": "IN",
            "pan": pan,
            "gstins": [f"27{pan}1Z5"],
            # Both a value we would once have stored and one we would once have
            # refused: neither is read any more.
            "website": "javascript:alert(1)",
        },
        "qualification": {
            "decision": "QUALIFIED",
            "method": "MANUAL",
            "criteria": [{"criterion": "export_history", "result": "PASS"}],
        },
    }
    intake = parse_rxil_company_package(package)
    assert not hasattr(intake, "website")

    async with db_services.AsyncSessionLocal() as db:
        result = await PartnerIntakeService(db).ingest(intake, actor_id="rxil-desk")
    assert result.company == "created"
    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalar(
            text(
                "SELECT website FROM onboarding.exporter_profile "
                "WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"c": str(result.customer_id)},
        )
    assert stored is None
