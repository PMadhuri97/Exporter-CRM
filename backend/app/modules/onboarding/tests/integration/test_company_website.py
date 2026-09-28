"""A company website is an http(s) link or nothing, on every path that writes it.

The website is rendered to other staff as ``<a href>``, and React 18 renders a
``javascript:`` or ``data:`` href as written, so a stored one would be script run in
the reader's session. ``domain/web_links.py`` holds the one rule; these tests prove
each write path applies it — manual create and edit (API), CSV import and RXIL
intake — and that a refused value leaves nothing behind.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_COLUMNS,
    CompanyImportService,
)
from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.application.exporter_profile_service import (
    HISTORY_DIMENSION_PROFILE,
    ExporterProfileService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"

#: Values a browser would not treat as a link to another site. The first three run
#: script; the last two are not absolute http(s) links with a host.
REFUSED = [
    "javascript:alert(document.cookie)",
    " javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "//evil.example",
    "www.example.com",
]


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


async def _company(**fields) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Website Co", country="IN", **fields
        )
    return customer_id


async def _current(customer_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await ExporterProfileService(db)._require_profile(customer_id)


async def _companies_with_pan(pan: str) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(ExporterProfile).where(ExporterProfile.pan == pan)
        )


# ── Manual create and edit ───────────────────────────────────────────────────


@pytest.mark.parametrize("value", REFUSED)
async def test_creating_a_company_with_a_non_web_website_is_refused(
    client: AsyncClient, value: str
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    pan = _pan()
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Script Co", "country": "IN", "pan": pan,
              "website": value},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422, resp.text
    assert await _companies_with_pan(pan) == 0


async def test_creating_a_company_with_an_https_website_is_accepted(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Linked Co", "country": "IN",
              "website": "https://linked.example"},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["website"] == "https://linked.example"


@pytest.mark.parametrize("value", REFUSED)
async def test_editing_the_website_to_a_non_web_value_is_refused_and_records_nothing(
    client: AsyncClient, value: str
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _company(website="https://acme.example")

    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}", json={"website": value}, headers=auth_header(token)
    )
    assert resp.status_code == 422, resp.text
    assert (await _current(customer_id)).website == "https://acme.example"
    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(
            customer_id, dimension=HISTORY_DIMENSION_PROFILE, limit=10
        )
    assert list(rows) == []


# ── CSV import ────────────────────────────────────────────────────────────────


def _row(**cells) -> str:
    values = {"name": f"Import Co {uuid.uuid4().hex[:8]}", "country": "IN", **cells}
    return ",".join(str(values.get(col, "") or "") for col in TEMPLATE_COLUMNS)


async def test_a_csv_row_with_a_script_website_is_rejected_and_nothing_is_created():
    pan = _pan()
    csv_file = io.StringIO(
        "\n".join((",".join(TEMPLATE_COLUMNS), _row(pan=pan, website="javascript:alert(1)")))
        + "\n"
    )
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(csv_file, actor_id="importer-1")
    [row] = report.rows
    assert row.status == "rejected"
    assert "INVALID_WEBSITE" in {reason.code for reason in row.reasons}
    assert row.customer_id is None
    assert await _companies_with_pan(pan) == 0


# ── RXIL intake ───────────────────────────────────────────────────────────────


async def test_an_rxil_package_with_a_script_website_creates_no_company():
    pan = _pan()
    package = {
        "exporter": {
            "legal_name": f"RXIL Exporter {uuid.uuid4().hex[:8]}",
            "country": "IN",
            "pan": pan,
            "gstins": [f"27{pan}1Z5"],
            "website": "javascript:alert(1)",
        },
        "qualification": {
            "decision": "QUALIFIED",
            "method": "MANUAL",
            "criteria": [{"criterion": "export_history", "result": "PASS"}],
        },
    }
    with pytest.raises(ValidationError, match="website"):
        async with db_services.AsyncSessionLocal() as db:
            await PartnerIntakeService(db).ingest(
                parse_rxil_company_package(package), actor_id="rxil-desk"
            )
    assert await _companies_with_pan(pan) == 0
