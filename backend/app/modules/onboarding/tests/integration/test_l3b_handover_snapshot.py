"""The persisted handover snapshot — **owner: Developer 2** (plan P2-7,
allocation task 2.1, migrations 0028 and 0029).

A separate file from ``test_l3b_handover.py`` on purpose: that file is about the
guard and the announcement, this one is about the **record**. The distinction is
the whole point of P2-7 — the announcement is best effort and the history row
carries only document ids, so neither was a record of the buyer the lending team
was given.

The immutability tests go through **raw SQL**, around the ORM and around the
service, because that is the only way to prove the database is what enforces the
rule rather than the code that happens to call it (the same method
``test_crm_integrity_guards_0022.py`` uses for 0022's rules).
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application import deal_service as deal_service_module
from app.modules.onboarding.application.deal_service import (
    SNAPSHOT_TAKEN_AT_HANDOVER,
    DealService,
)
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.storage_service import StorageService
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome
from app.modules.onboarding.infrastructure.storage import LocalDiskStorage
from app.modules.onboarding.migrations import onboarding_0029_deal_snapshot as snapshot_migration
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
PDF = b"%PDF-1.4 bill of lading"


class _CleanScanner:
    name = "fake"

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        return ScanOutcome(status=DocumentScanStatus.AVAILABLE, scanner_name=self.name)


@pytest.fixture
def clear_background_check(monkeypatch: pytest.MonkeyPatch):
    """The one read seam substituted, as in ``test_l3b_handover.py``: everything
    after the guard runs for real against Postgres."""
    monkeypatch.setattr(
        deal_service_module, "read_background_check", lambda company: "CLEAR"
    )


def _raw_sql():
    return psycopg2.connect(
        get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    )


async def _customer() -> uuid.UUID:
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = ExporterJourney.CUSTOMER
        await db.commit()
    return company_id


async def _deal_ready_to_hand_over(company_id: uuid.UUID) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference=f"Snapshot {uuid.uuid4().hex[:8]}", actor_id="tester"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id,
            name="Rotterdam Trading BV",
            country="NL",
            registration_number="NL-8899",
            tax_id="NL123456789B01",
            contact_email="ops@rotterdamtrading.example",
            contact_phone="+31201234567",
            actor_id="tester",
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            view.id, DealStage.GATHERING_PAPERWORK, actor_id="tester"
        )
    # The PRE_SHIPMENT document migration 0030 requires (P2-5b). Without it the
    # guard refuses and these tests never reach the snapshot they are about.
    await _add_document(
        view.id,
        Path(tempfile.mkdtemp(prefix="required-doc-")),
        "proforma-invoice.pdf",
        category=DocumentCategory.PRE_SHIPMENT,
        document_type="proforma_invoice",
    )
    return view.id


async def _add_document(
    deal_id: uuid.UUID,
    tmp_path: Path,
    name: str,
    *,
    category: DocumentCategory = DocumentCategory.SHIPPING,
    document_type: str = "bill_of_lading",
) -> uuid.UUID:
    storage = StorageService(LocalDiskStorage(root=tmp_path), _CleanScanner())
    async with db_services.AsyncSessionLocal() as db:
        view = await DocumentService(db, storage=storage).upload(
            PDF,
            deal_id=deal_id,
            category=category,
            document_type=document_type,
            source=DocumentSource.EXPORTER_UPLOAD,
            file_name=name,
            content_type="application/pdf",
            actor_id="tester",
        )
    return view.id


async def _hand_over(deal_id: uuid.UUID):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="tester"
        )


async def _stored_snapshot(deal_id: uuid.UUID) -> dict | None:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(select(Deal.handover_snapshot).where(Deal.id == deal_id))


# ── The snapshot is written, and is what the handover rested on ──────────────


async def test_a_handover_persists_the_buyer_and_the_documents(
    clear_background_check, tmp_path: Path
):
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    document_id = await _add_document(deal_id, tmp_path, "bol.pdf")

    await _hand_over(deal_id)

    snapshot = await _stored_snapshot(deal_id)
    assert snapshot is not None, "a handed-over deal must carry its snapshot"
    assert snapshot["buyer"]["name"] == "Rotterdam Trading BV"
    assert snapshot["buyer"]["country"] == "NL"
    # The identifiers are stored **unmasked**: the record of what was handed over
    # must not depend on who reads it. Masking happens in the response.
    assert snapshot["buyer"]["tax_id"] == "NL123456789B01"
    # The required PRE_SHIPMENT document is on the deal too, so this is a
    # membership check: the snapshot is every document the handover rested on.
    assert str(document_id) in snapshot["document_ids"]
    assert len(snapshot["document_ids"]) == 2
    assert snapshot["snapshot_source"] == SNAPSHOT_TAKEN_AT_HANDOVER
    assert snapshot["snapshot_at"] is not None
    # No company link yet: P4-4 records one, P4-6 backfills it.
    assert snapshot["buyer_company_id"] is None


async def test_the_snapshot_is_written_in_the_same_transaction_as_the_stage(
    clear_background_check,
):
    """``trg_deal_terminal_freeze`` fires on the OLD row, whose stage is still
    ``GATHERING_PAPERWORK``, so the snapshot lands before it is frozen. A snapshot
    written in a second UPDATE would be refused by the set-once rule, and this is
    the test that would catch that regression."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    view = await _hand_over(deal_id)

    assert view.stage is DealStage.HANDED_OVER
    assert view.handover_snapshot is not None
    assert await _stored_snapshot(deal_id) == view.handover_snapshot


async def test_editing_the_buyer_afterwards_cannot_change_the_snapshot(
    clear_background_check,
):
    """P2-7's acceptance criterion. Today the service refuses the edit outright;
    the next test proves the database would refuse the change even if it did not."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)
    before = await _stored_snapshot(deal_id)

    with pytest.raises(Exception) as caught:
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).set_buyer(
                deal_id, name="Someone Else BV", country="DE", actor_id="tester"
            )
    assert getattr(caught.value, "error_code", None) == "DEAL_TERMINAL"
    assert await _stored_snapshot(deal_id) == before


# ── The database enforces it, not the service (raw SQL) ──────────────────────


async def test_raw_sql_cannot_change_a_snapshot_once_set(clear_background_check):
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)
    before = await _stored_snapshot(deal_id)

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            for new_value in ('\'{"buyer": {"name": "Forged BV"}}\'::jsonb', "NULL"):
                with pytest.raises(psycopg2.errors.RaiseException) as caught:
                    cursor.execute(
                        f"UPDATE onboarding.deal SET handover_snapshot = {new_value}"
                        " WHERE id = %s;",
                        (str(deal_id),),
                    )
                assert "handover snapshot" in str(caught.value)
                connection.rollback()
    finally:
        connection.close()

    assert await _stored_snapshot(deal_id) == before


async def test_raw_sql_may_fill_a_snapshot_that_is_missing(clear_background_check):
    """Set-once, not frozen: migration 0029's backfill and P4-6's have to be able
    to fill a deal that was handed over before snapshots existed. The 0022 columns
    stay frozen outright while this happens."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            # Clear it the only way the rule allows: it does not, so arrange the
            # "no snapshot yet" state by disabling the trigger for this one
            # statement — which is what proves the rule is the trigger's.
            cursor.execute("ALTER TABLE onboarding.deal DISABLE TRIGGER trg_deal_terminal_freeze;")
            cursor.execute(
                "UPDATE onboarding.deal SET handover_snapshot = NULL WHERE id = %s;",
                (str(deal_id),),
            )
            cursor.execute("ALTER TABLE onboarding.deal ENABLE TRIGGER trg_deal_terminal_freeze;")
            # Now the backfill's UPDATE, with the trigger back on: allowed.
            cursor.execute(
                "UPDATE onboarding.deal SET handover_snapshot ="
                " '{\"snapshot_source\": \"backfilled_from_deal_buyer\"}'::jsonb"
                " WHERE id = %s;",
                (str(deal_id),),
            )
            # And a second change is refused, as it is for any other snapshot.
            with pytest.raises(psycopg2.errors.RaiseException):
                cursor.execute(
                    "UPDATE onboarding.deal SET handover_snapshot = '{}'::jsonb WHERE id = %s;",
                    (str(deal_id),),
                )
            connection.rollback()
    finally:
        connection.close()


async def test_the_migration_backfill_rebuilds_what_the_handover_wrote(
    clear_background_check,
):
    """Migration 0029's own ``_BACKFILL`` statement, run for real rather than
    imitated: on a deal handed over through the service and then stripped of its
    snapshot, the reconstruction has the same keys, the same buyer, the same
    paperwork and the same moment as the snapshot the handover took — so one reader
    serves both. A handed-over deal with no buyer row and no handover history row
    gets ``buyer: null`` and ``document_ids: null`` ("not recorded"), never ``[]``.

    Everything runs in one transaction that is rolled back, because the statement
    fills **every** handed-over deal without a snapshot."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)
    taken = await _stored_snapshot(deal_id)
    bare_id = uuid.uuid4()

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE onboarding.deal DISABLE TRIGGER trg_deal_terminal_freeze;")
            cursor.execute(
                "UPDATE onboarding.deal SET handover_snapshot = NULL WHERE id = %s;",
                (str(deal_id),),
            )
            cursor.execute("ALTER TABLE onboarding.deal ENABLE TRIGGER trg_deal_terminal_freeze;")
            # A deal that reached HANDED_OVER without a buyer row or a history row —
            # possible only around the service, which is the case the nulls are for.
            cursor.execute(
                "INSERT INTO onboarding.deal (id, company_id, reference, stage, handed_over_at)"
                " VALUES (%s, %s, 'Handed over off the books', 'HANDED_OVER', now());",
                (str(bare_id), str(company_id)),
            )

            cursor.execute(snapshot_migration._BACKFILL)

            cursor.execute(
                "SELECT id, handover_snapshot FROM onboarding.deal WHERE id IN (%s, %s);",
                (str(deal_id), str(bare_id)),
            )
            rebuilt = {uuid.UUID(str(row_id)): snapshot for row_id, snapshot in cursor.fetchall()}
    finally:
        connection.rollback()
        connection.close()

    again = rebuilt[deal_id]
    assert set(again) == set(taken)
    assert again["snapshot_source"] == "backfilled_from_deal_buyer"
    assert again["buyer"] == taken["buyer"]
    assert again["document_ids"] == taken["document_ids"]
    assert again["buyer_company_id"] is None
    assert datetime.fromisoformat(again["snapshot_at"]) == datetime.fromisoformat(
        taken["snapshot_at"]
    )

    bare = rebuilt[bare_id]
    assert (bare["buyer"], bare["document_ids"]) == (None, None)
    assert bare["snapshot_source"] == "backfilled_from_deal_buyer"


async def test_the_0022_columns_are_still_frozen_outright(clear_background_check):
    """0029 replaced ``prevent_terminal_deal_change()``; the five columns 0022
    froze must keep exactly the rule 0022 gave them."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            for column, value in (
                ("stage", "'OPEN'"),
                ("reference", "'Rewritten'"),
                ("handed_over_at", "NULL"),
            ):
                with pytest.raises(psycopg2.errors.RaiseException) as caught:
                    cursor.execute(
                        f"UPDATE onboarding.deal SET {column} = {value} WHERE id = %s;",
                        (str(deal_id),),
                    )
                assert "a closed deal no longer changes" in str(caught.value)
                connection.rollback()
    finally:
        connection.close()


# ── The new deal columns, and their constraints ──────────────────────────────


async def test_a_company_cannot_be_both_sides_of_a_deal():
    """``ck_deal_buyer_is_not_the_seller`` (migration 0028). Checked in the
    database because P4-6's migration writes the column directly."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor, pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "UPDATE onboarding.deal SET buyer_company_id = company_id WHERE id = %s;",
                (str(deal_id),),
            )
        connection.rollback()
    finally:
        connection.close()


async def test_a_buyer_company_must_exist():
    """``fk_deal_buyer_company_id``: the buyer is a real company record, so a
    dangling id is refused rather than stored."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor, pytest.raises(
            psycopg2.errors.ForeignKeyViolation
        ):
            cursor.execute(
                "UPDATE onboarding.deal SET buyer_company_id = %s WHERE id = %s;",
                (str(uuid.uuid4()), str(deal_id)),
            )
        connection.rollback()
    finally:
        connection.close()


# ── Through the API, per role ────────────────────────────────────────────────


async def test_the_deal_response_carries_the_snapshot_masked_by_role(
    client: AsyncClient, clear_background_check, tmp_path: Path
):
    """The snapshot's buyer is masked by exactly the rule that masks the live
    buyer: being inside a snapshot does not make a tax identifier more visible."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _add_document(deal_id, tmp_path, "bol.pdf")
    await _hand_over(deal_id)

    for role in (UserRole.COMPLIANCE, UserRole.ADMIN):
        token = await token_with_role(client, role)
        body = (await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))).json()
        assert body["handover_snapshot"]["buyer"]["tax_id"] == "NL123456789B01"
        assert body["handover_snapshot"]["buyer"]["contact_email"] == (
            "ops@rotterdamtrading.example"
        )

    for role in (UserRole.OPERATIONS, UserRole.DEVELOPER):
        token = await token_with_role(client, role)
        body = (await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))).json()
        buyer = body["handover_snapshot"]["buyer"]
        # Written out rather than computed, so this asserts what goes on the wire
        # rather than re-deriving it from the function under test.
        assert buyer["tax_id"] == "••••••••••9B01"  # NL123456789B01
        assert buyer["registration_number"] == "•••8899"  # NL-8899
        assert buyer["contact_email"] == "o•••@rotterdamtrading.example"
        assert buyer["contact_phone"] == "••••••••4567"  # +31201234567
        # The name and country stay visible: a handover is unrecognisable without
        # them, the same rule `DealBuyerResponse` applies. The keys that carry no
        # identifier pass through untouched.
        assert buyer["name"] == "Rotterdam Trading BV"
        assert buyer["country"] == "NL"
        assert body["handover_snapshot"]["snapshot_source"] == SNAPSHOT_TAKEN_AT_HANDOVER
        assert body["handover_snapshot"]["document_ids"] != []


async def test_a_deal_that_was_not_handed_over_has_no_snapshot(client: AsyncClient):
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    token = await token_with_role(client, UserRole.OPERATIONS)
    body = (await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))).json()
    assert body["handover_snapshot"] is None
    # The F2 fields are present in the shape and empty in fact, which is what lets
    # the company screens be built against them before P4-4 and P6-6 land.
    assert body["buyer_company"] is None
    assert body["seller_gst_registration_id"] is None
