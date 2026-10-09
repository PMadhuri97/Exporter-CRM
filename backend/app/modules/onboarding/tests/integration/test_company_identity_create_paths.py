"""Company identity on every create path, and the pipeline refusal.

Migration 0032 added the columns; this proves the application fills them, consistently, from
each of the four ways a company comes into being, and that a company which is not
in the sales pipeline cannot be put through a sales step.

What is worth testing here, as opposed to restating the schema:

* ``created_via`` is derived from ``history_source``, and migration 0033's
  backfill uses the same mapping expressed as SQL. **The two agreeing is the only
  thing keeping a backfilled company and a freshly created one comparable**, so
  one test compares the two mappings directly rather than trusting both.
* ``identity_type`` is decided from the identifiers held, never from the country.
  A buyer with neither keeps ``NULL`` — which is the value the identity completion
  list is built on, so a guess here would empty that list.
* The foreign-identity rule is enforced in ``create_or_get_profile``, so every path inherits
  it. The CSV importer and the RXIL parser check it *again* so their reports can
  name the row or the field; those are tested through their own entry points.
* A ``NOT_IN_PIPELINE`` company is refused by qualification and conversation.
  Without that refusal, qualifying a buyer-only company would move its journey to
  ``PROSPECT`` and ``ck_exporter_profile_not_in_pipeline_start`` would turn a
  sales action into a constraint violation.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.company_import_service import (
    TEMPLATE_COLUMNS,
    CompanyImportService,
)
from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_identity import (
    CreatedVia,
    created_via_for_history_source,
    decide_identity_type,
    normalise_registration_number,
    registration_key,
)
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue,
)
from app.modules.onboarding.exceptions import CompanyNotInPipelineError
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.modules.onboarding.migrations.onboarding_0033_created_via import _CHANNEL_BY_SOURCE
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.deals import make_deal
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _pan() -> str:
    """A PAN nothing else holds: `uq_exporter_profile_pan` is real and this
    suite's database persists between runs."""
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _registration() -> str:
    """Likewise for `uq_exporter_profile_country_registration_number`."""
    return f"REG-{uuid.uuid4().hex[:10].upper()}"


async def _row_of(customer_id: uuid.UUID) -> dict:
    async with db_services.AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT identity_type, registration_number, pipeline_status, created_via, "
                "created_via_deal_id, country, pan "
                "FROM onboarding.exporter_profile WHERE customer_id = CAST(:c AS uuid)"
            ),
            {"c": str(customer_id)},
        )
        return dict(result.mappings().one())


# ── The one mapping, in two places ────────────────────────────────────────────


def test_the_migration_backfill_and_the_live_path_map_the_same_sources():
    """A company created today and one the backfill answered must read the same.

    The live mapping is a dict in `domain/company_identity.py`; migration 0033
    freezes it as SQL built from `_CHANNEL_BY_SOURCE`. They are deliberately
    separate — a migration that imported evolving application code would change
    meaning under us — so this is the test that keeps them honest. Adding a
    channel to one and not the other fails here instead of quietly backfilling
    `NULL` for every company that arrived through it.
    """
    from_migration = {source: channel for source, channel in _CHANNEL_BY_SOURCE}
    from_live = {
        source: created_via_for_history_source(source).value for source in from_migration
    }
    assert from_live == from_migration

    # And every channel the application can write is covered by the backfill, so
    # no live path exists whose companies the migration would leave NULL.
    assert set(from_migration.values()) == {c.value for c in CreatedVia}


def test_an_unmapped_history_source_is_not_guessed_as_manual():
    """`None`, not `MANUAL`: "entered by hand" is a claim about how a company
    reached us, and an unrecognised channel is not evidence for it."""
    assert created_via_for_history_source("seed") is None
    assert created_via_for_history_source(None) is None
    assert created_via_for_history_source("exporter_profile_service.create_lead") is (
        CreatedVia.MANUAL
    )


# ── identity_type comes from the identifiers, not the country ─────────────────


def test_identity_type_is_decided_by_what_the_company_holds():
    assert decide_identity_type(pan="ABCDE1234F", registration_number=None) is (
        CompanyIdentityType.IN_PAN
    )
    assert decide_identity_type(pan=None, registration_number="KVK-1") is (
        CompanyIdentityType.FOREIGN_REG
    )
    # A PAN wins: a company holding one is Indian however it reached us.
    assert decide_identity_type(pan="ABCDE1234F", registration_number="KVK-1") is (
        CompanyIdentityType.IN_PAN
    )
    # Neither: left open, which is what the identity completion list reads.
    assert decide_identity_type(pan=None, registration_number=None) is None


def test_a_registration_number_is_stored_as_written_and_compared_without_punctuation():
    """The registrar's own formatting is shown back to staff, so it is kept; only
    comparison normalises, and it must normalise exactly as the unique index does
    or a lookup reports "new" for a number the insert then refuses."""
    assert normalise_registration_number("  KVK 12.345 ") == "KVK 12.345"
    assert registration_key("KVK 12.345") == registration_key("kvk-12345") == "KVK12345"
    assert normalise_registration_number("   ") is None
    assert normalise_registration_number(None) is None
    with pytest.raises(ValidationError, match="letters or digits"):
        normalise_registration_number("--/--")
    with pytest.raises(ValidationError, match="at most"):
        normalise_registration_number("X" * 101)


# ── Manual create (API) ───────────────────────────────────────────────────────


async def test_creating_an_indian_company_records_in_pan_and_manual(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Mumbai Textiles", "country": "IN", "pan": _pan()},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["identity_type"] == "IN_PAN"
    assert body["pipeline_status"] == "IN_PIPELINE"

    row = await _row_of(uuid.UUID(body["customer_id"]))
    assert row["created_via"] == CreatedVia.MANUAL.value
    assert row["created_via_deal_id"] is None


async def test_creating_a_foreign_company_needs_a_registration_number(client: AsyncClient):
    """The foreign-identity rule at the API boundary. The refusal is a 422 naming the field,
    not a company created with an identity nobody can check."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Rotterdam Trading BV", "country": "NL"},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422, resp.text
    assert "Registration number is required" in resp.text


async def test_creating_a_foreign_company_with_a_number_records_foreign_reg(
    client: AsyncClient,
):
    # COMPLIANCE, because the number comes back masked for a role that may not reveal
    # identifiers — which is its own test below.
    _user_id, token = await user_with_role(client, UserRole.COMPLIANCE)
    registration = _registration()
    resp = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": "Rotterdam Trading BV",
            "country": "NL",
            "registration_number": registration,
        },
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["identity_type"] == "FOREIGN_REG"
    assert body["registration_number"] == registration


async def test_a_foreign_company_holding_a_pan_needs_no_registration_number(
    client: AsyncClient,
):
    """A PAN is itself an identity, so the foreign-identity rule has nothing left to ask for.
    An Indian company registered abroad is a real case, and refusing it would push
    staff into inventing a number to get past the form."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Singapore Branch Ltd", "country": "SG", "pan": _pan()},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["identity_type"] == "IN_PAN"


async def test_two_companies_cannot_share_a_registration_number_in_one_country(
    client: AsyncClient,
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    registration = _registration()
    first = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "First BV", "country": "NL",
              "registration_number": registration},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert first.status_code in (200, 201), first.text

    # Same number, different punctuation and case: one registration, so refused —
    # with a 409 naming the company that holds it, the way a duplicate PAN is, not
    # the 500 a bare constraint violation would give.
    second = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Second BV", "country": "nl",
              "registration_number": registration.lower().replace("-", " ")},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["error_code"] == "DUPLICATE_REGISTRATION_NUMBER", body
    assert body["error_context"]["existing_customer_id"] == first.json()["customer_id"]
    # The number itself is not echoed: the caller sent it, and a masked role may
    # read this response.
    assert registration not in second.text

    # The same number in another country is a different registration.
    third = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Third NV", "country": "BE",
              "registration_number": registration},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert third.status_code in (200, 201), third.text


# ── Masked like CIN ───────────────────────────────────────────────────────────


async def test_a_registration_number_is_masked_for_a_role_that_may_not_reveal(
    client: AsyncClient,
):
    _admin_id, admin_token = await user_with_role(client, UserRole.COMPLIANCE)
    registration = _registration()
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Masked BV", "country": "NL",
              "registration_number": registration},
        headers={**auth_header(admin_token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code in (200, 201), created.text
    customer_id = created.json()["customer_id"]

    for role in (UserRole.OPERATIONS, UserRole.DEVELOPER, UserRole.ADMIN):
        _user_id, token = await user_with_role(client, role)
        resp = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        shown = resp.json()["registration_number"]
        assert shown != registration, role
        # Same mask shape as CIN: only the last four characters survive.
        assert shown.endswith(registration[-4:]), (role, shown)
        assert "•" in shown, (role, shown)

    for role in (UserRole.COMPLIANCE,):
        _user_id, token = await user_with_role(client, role)
        resp = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
        assert resp.json()["registration_number"] == registration, role


async def test_a_masked_registration_number_cannot_be_written_back(client: AsyncClient):
    """`NotMasked`, as for the other identifiers: a client echoing what it read
    would otherwise overwrite the real number with bullets."""
    _user_id, token = await user_with_role(client, UserRole.COMPLIANCE)
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Echo BV", "country": "NL",
              "registration_number": _registration()},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    customer_id = created.json()["customer_id"]
    resp = await client.patch(
        f"{BASE}/exporters/{customer_id}",
        json={"registration_number": "•••••••••1234"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


# ── CSV import ────────────────────────────────────────────────────────────────


def _csv(columns: tuple[str, ...], *rows: dict) -> io.StringIO:
    lines = [",".join(columns)]
    for cells in rows:
        values = {"name": f"CSV Co {uuid.uuid4().hex[:8]}", "country": "IN", **cells}
        lines.append(",".join(str(values.get(col, "") or "") for col in columns))
    return io.StringIO("\n".join(lines) + "\n")


async def test_a_csv_row_records_the_csv_channel_and_its_identity():
    registration = _registration()
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(
            _csv(TEMPLATE_COLUMNS, {"country": "NL", "registration_number": registration}),
            actor_id="importer-1",
        )
    [row] = report.rows
    assert row.status == "accepted", row.reasons
    stored = await _row_of(row.customer_id)
    assert stored["created_via"] == CreatedVia.CSV.value
    assert stored["identity_type"] == "FOREIGN_REG"
    assert stored["registration_number"] == registration


async def test_a_csv_row_for_a_foreign_company_with_no_number_is_rejected_by_name():
    """The report names the row and the column, rather than the import failing
    late or the row landing with an identity nobody can check."""
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(
            _csv(TEMPLATE_COLUMNS, {"country": "NL"}), actor_id="importer-1"
        )
    [row] = report.rows
    assert row.status == "rejected"
    assert "INVALID_REGISTRATION_NUMBER" in {reason.code for reason in row.reasons}
    assert row.customer_id is None


async def test_a_csv_file_written_before_the_column_existed_still_imports():
    """`registration_number` is optional in the header, so last month's file keeps
    working; the foreign-identity rule still applies per row, which is where it belongs."""
    older_columns = tuple(c for c in TEMPLATE_COLUMNS if c != "registration_number")
    async with db_services.AsyncSessionLocal() as db:
        report = await CompanyImportService(db).import_csv(
            _csv(older_columns, {"country": "IN", "pan": _pan()}), actor_id="importer-1"
        )
    [row] = report.rows
    assert row.status == "accepted", row.reasons
    assert (await _row_of(row.customer_id))["identity_type"] == "IN_PAN"


# ── RXIL intake ───────────────────────────────────────────────────────────────


def _package(**exporter) -> dict:
    return {
        "exporter": {
            "legal_name": f"RXIL Exporter {uuid.uuid4().hex[:8]}",
            "country": "IN",
            **exporter,
        },
        "qualification": {
            "decision": "QUALIFIED",
            "method": "MANUAL",
            "criteria": [{"criterion": "export_history", "result": "PASS"}],
        },
    }


async def test_an_rxil_package_records_the_rxil_channel():
    pan = _pan()
    async with db_services.AsyncSessionLocal() as db:
        result = await PartnerIntakeService(db).ingest(
            parse_rxil_company_package(_package(pan=pan, gstins=[f"27{pan}1Z5"])),
            actor_id="rxil-desk",
        )
    stored = await _row_of(result.customer_id)
    assert stored["created_via"] == CreatedVia.RXIL.value
    assert stored["identity_type"] == "IN_PAN"


async def test_an_rxil_delivery_cannot_reach_the_foreign_identity_case_at_all():
    """The foreign-identity rule is not checked by the RXIL parser, and this is why.

    Intake refuses any delivery without a PAN or at least one GSTIN, so that a
    repeated delivery finds the same company — and a GSTIN carries a PAN, so both
    mean the exporter is identified by one. A foreign exporter carrying *only* a
    registration number is therefore refused by intake before the rule could have
    anything to say, and a check in the parser would be unreachable code claiming
    to enforce a rule.

    Worth a test rather than a comment: if that identifier rule is ever relaxed,
    this fails, and whoever relaxes it is told that the rule now needs a home on this
    path. Note the refusal comes from `ingest`, not from the parser — the parser
    accepts the package, which is exactly why the distinction needs recording.
    """
    from app.modules.onboarding.exceptions import PartnerPackageInvalidError

    intake = parse_rxil_company_package(
        _package(country="NL", registration_number=_registration())
    )
    assert intake.identity.country == "NL"

    with pytest.raises(PartnerPackageInvalidError, match="PAN or at least one GSTIN"):
        async with db_services.AsyncSessionLocal() as db:
            await PartnerIntakeService(db).ingest(intake, actor_id="rxil-desk")


async def test_an_rxil_package_may_still_carry_a_registration_number():
    """An exporter can hold both — an Indian company registered abroad. The PAN
    decides the identity type; the number is kept rather than dropped, because
    nothing else records it and the company page shows it."""
    pan = _pan()
    registration = _registration()
    async with db_services.AsyncSessionLocal() as db:
        result = await PartnerIntakeService(db).ingest(
            parse_rxil_company_package(
                _package(
                    country="NL",
                    pan=pan,
                    gstins=[f"27{pan}1Z5"],
                    registration_number=registration,
                )
            ),
            actor_id="rxil-desk",
        )
    stored = await _row_of(result.customer_id)
    assert stored["created_via"] == CreatedVia.RXIL.value
    assert stored["identity_type"] == "IN_PAN"
    assert stored["registration_number"] == registration


# ── The buyer path keeps the rule's one exception ─────────────────────────────


async def test_a_migrated_buyer_may_have_neither_identifier():
    """The rule's exception: a buyer the migration creates may be nothing
    but a name and a country, because the rule cannot be met retroactively. It
    keeps `identity_type NULL` — the value the completion list is built on — and
    is **not** guessed as FOREIGN_REG from its country."""
    deal_id = await make_deal()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Antwerp Shipping NV", country="BE", created_via_deal_id=deal_id
            ),
            actor_id="migration",
        )
    stored = await _row_of(company_id)
    assert stored["identity_type"] is None
    assert stored["registration_number"] is None
    assert stored["pipeline_status"] == "NOT_IN_PIPELINE"
    assert stored["created_via"] == CreatedVia.DEAL_BUYER.value
    assert str(stored["created_via_deal_id"]) == str(deal_id)


async def test_a_buyer_company_with_a_registration_number_records_it():
    """The same path, given the number: `create_or_get_profile` now owns these
    columns, so the buyer path must come out identical to a manual create."""
    registration = _registration()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Rotterdam Trading BV", country="NL", registration_number=registration
            ),
            actor_id="rm-1",
        )
    stored = await _row_of(company_id)
    assert stored["identity_type"] == "FOREIGN_REG"
    assert stored["registration_number"] == registration
    assert stored["created_via"] == CreatedVia.DEAL_BUYER.value


# ── A company outside the pipeline is not sold to ─────────────────────────────


async def _buyer_only_company() -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(name="Buyer Only BV", country="NL",
                              registration_number=_registration()),
            actor_id="rm-1",
        )


async def test_qualification_refuses_a_company_that_is_not_in_the_pipeline():
    """Without this, a QUALIFIED outcome would move the journey to PROSPECT and
    `ck_exporter_profile_not_in_pipeline_start` would refuse the write — turning a
    sales action into a database constraint violation. This is also the refusal
    full-depth buyer checks rely on: a buyer-only company can never be promoted."""
    company_id = await _buyer_only_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(CompanyNotInPipelineError):
            await QualificationService(db).record_outcome(
                company_id,
                outcome=QualificationOutcomeValue.QUALIFIED,
                note="should never be recorded",
                actor_id="rm-1",
            )
    # Nothing moved.
    stored = await _row_of(company_id)
    assert stored["pipeline_status"] == "NOT_IN_PIPELINE"


async def test_the_conversation_gauge_refuses_a_company_that_is_not_in_the_pipeline():
    company_id = await _buyer_only_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(CompanyNotInPipelineError):
            await ConversationService(db).set_conversation(
                company_id, ExporterConversation.REACHING_OUT, actor_id="rm-1"
            )


async def test_reading_a_buyer_only_company_still_works():
    """The refusal is on the write paths only. A buyer-only company is a full
    company record — full-depth buyer checks screen and clear one — so every read
    must keep rendering, including the gauges that do not apply to it."""
    company_id = await _buyer_only_company()
    async with db_services.AsyncSessionLocal() as db:
        view = await QualificationService(db).get_qualification(company_id)
        assert view is not None
    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(company_id)
    assert detail.pipeline_status is CompanyPipelineStatus.NOT_IN_PIPELINE
    assert detail.source is ExporterSource.DEAL_BUYER
