"""Required document categories as a setting, and the guard condition that reads
them — **owner: Developer 2** (plan P2-5a and P2-5b, allocation tasks 2.2 and 2.3,
migration 0030).

Three things are tested here, in this order:

1. the **setting**: versioned, append-only, ADMIN-only writes;
2. the **policy**: which categories a deal is missing, and what counts;
3. the **guard**: that a deal missing one is refused by name, through the routes.

The append-only guarantee goes through **raw SQL**, because the point of a
database trigger is that it holds for a writer that never went through the
service.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application import deal_service as deal_service_module
from app.modules.onboarding.application.deal_required_documents_service import (
    DealRequiredDocumentsPolicy,
    DealRequiredDocumentsService,
)
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.storage_service import StorageService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.deal_required_document import (
    DealRequiredDocument,
)
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome
from app.modules.onboarding.exceptions import DealRequiredDocumentChangedError
from app.modules.onboarding.infrastructure.storage import LocalDiskStorage
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
SETTINGS = f"{BASE}/settings/deal-required-documents"
PDF = b"%PDF-1.4 proforma invoice"


class _Scanner:
    """A scanner whose verdict the test chooses, so "only AVAILABLE counts" can be
    tested with a document that really is not available."""

    name = "fake"

    def __init__(self, status: DocumentScanStatus = DocumentScanStatus.AVAILABLE) -> None:
        self._status = status

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        return ScanOutcome(status=self._status, scanner_name=self.name)


@pytest.fixture
def clear_background_check(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        deal_service_module, "read_background_check", lambda company: "CLEAR"
    )


async def _active_keys() -> set[tuple[DocumentCategory, str]]:
    async with db_services.AsyncSessionLocal() as db:
        rows = await DealRequiredDocumentsService(db).active()
    return {(row.category, row.document_type) for row in rows}


@pytest.fixture(autouse=True)
async def _restore_the_rule():
    """Put the requirements back exactly as the test found them.

    These tests write to a table the whole suite's handovers depend on, and it is
    append-only — so "restore" means appending versions that say what was in force
    before, not deleting what the test wrote. Without this, a test that removes the
    `PRE_SHIPMENT` requirement would silently disable the guard for every test
    that ran after it.

    Restored to the set in force **before the test**, not to "the seed and nothing
    else": the suite runs against a shared database, and a requirement someone
    configured there by hand is not this file's to switch off.
    """
    before = await _active_keys()
    yield
    after = await _active_keys()
    async with db_services.AsyncSessionLocal() as db:
        service = DealRequiredDocumentsService(db)
        for (category, document_type), active in [
            *((key, True) for key in sorted(before - after, key=str)),
            *((key, False) for key in sorted(after - before, key=str)),
        ]:
            await service.set_requirement(
                category=category,
                document_type=document_type or None,
                active=active,
                actor_id="test-teardown",
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


async def _deal_with_a_buyer(company_id: uuid.UUID) -> uuid.UUID:
    """At ``GATHERING_PAPERWORK``, with a buyer and no documents."""
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference=f"Required docs {uuid.uuid4().hex[:8]}", actor_id="t"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id, name="Rotterdam Trading BV", country="NL", actor_id="t"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            view.id, DealStage.GATHERING_PAPERWORK, actor_id="t"
        )
    return view.id


async def _upload(
    deal_id: uuid.UUID,
    tmp_path: Path,
    *,
    category: DocumentCategory,
    document_type: str = "proforma_invoice",
    status: DocumentScanStatus = DocumentScanStatus.AVAILABLE,
) -> uuid.UUID:
    storage = StorageService(LocalDiskStorage(root=tmp_path), _Scanner(status))
    async with db_services.AsyncSessionLocal() as db:
        view = await DocumentService(db, storage=storage).upload(
            PDF,
            deal_id=deal_id,
            category=category,
            document_type=document_type,
            source=DocumentSource.EXPORTER_UPLOAD,
            file_name=f"{document_type}.pdf",
            content_type="application/pdf",
            actor_id="t",
        )
    return view.id


async def _missing(deal_id: uuid.UUID) -> tuple[str, ...]:
    async with db_services.AsyncSessionLocal() as db:
        return await DealRequiredDocumentsPolicy(db).missing_for_deal(deal_id)


async def _version_of(category: DocumentCategory, document_type: str = "") -> int:
    """The current version of one key, or 0 if it has none.

    Versions are **global and monotonic** on the suite's shared database: the
    table is append-only, so a key's version keeps climbing as tests and
    teardowns append to it. Every assertion about a version is therefore an
    assertion about an *increment* from whatever it was — asserting an absolute
    number would pass only when this file runs first.
    """
    async with db_services.AsyncSessionLocal() as db:
        rows = await DealRequiredDocumentsService(db).current()
    return next(
        (
            row.version
            for row in rows
            if row.category is category and row.document_type == document_type
        ),
        0,
    )




# ── 1. The setting ───────────────────────────────────────────────────────────


async def test_the_seeded_rule_is_one_pre_shipment_requirement():
    """IQ-10: migration 0030 seeds exactly this, with no ``created_by`` — nobody
    added it, so attributing it to someone would be a lie.

    Asserted about **version 1**, not about whatever version is active now: this
    file's teardown appends versions to the same key, so the current version
    climbs as the suite runs. Version 1 is the seed and never changes.
    """
    async with db_services.AsyncSessionLocal() as db:
        history = await DealRequiredDocumentsService(db).history()

    # Identified by `source`, which is what says a row came from the migration.
    # Not by `version == 1`: every key's first version is 1, and other tests in
    # this file add keys of their own.
    seeded = [row for row in history if row.source == "migration_0030_seed"]
    assert [
        (row.category, row.document_type, row.version, row.active) for row in seeded
    ] == [
        (DocumentCategory.PRE_SHIPMENT, "", 1, True)
    ], "the migration seeds exactly one requirement"
    assert seeded[0].created_by is None
    assert seeded[0].source == "migration_0030_seed"

    # And it is in force on a database nobody has reconfigured.
    async with db_services.AsyncSessionLocal() as db:
        active = await DealRequiredDocumentsService(db).active()
    assert [(row.category, row.document_type) for row in active] == [
        (DocumentCategory.PRE_SHIPMENT, "")
    ]


async def test_removing_a_requirement_writes_a_version_rather_than_deleting():
    was = await _version_of(DocumentCategory.PRE_SHIPMENT)
    async with db_services.AsyncSessionLocal() as db:
        await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.PRE_SHIPMENT,
            document_type=None,
            active=False,
            actor_id="admin-user",
        )

    async with db_services.AsyncSessionLocal() as db:
        service = DealRequiredDocumentsService(db)
        assert await service.active() == []
        # The key is still there, as its latest version, saying it was removed.
        # Filtered by category: `current()` also returns the keys other tests in
        # this file added and the teardown turned back off.
        [current] = [
            row
            for row in await service.current()
            if row.category is DocumentCategory.PRE_SHIPMENT
        ]
        assert (current.version, current.active, current.created_by) == (
            was + 1,
            False,
            "admin-user",
        )
        # And the version it superseded is untouched, so what was required when is
        # still readable — right back to the seed.
        versions = [
            (row.version, row.active)
            for row in await service.history()
            if row.category is DocumentCategory.PRE_SHIPMENT
        ]
        assert versions[:2] == [(was + 1, False), (was, True)]
        assert versions[-1] == (1, True)


async def test_a_requirement_can_be_added_back_as_a_later_version():
    was = await _version_of(DocumentCategory.PRE_SHIPMENT)
    async with db_services.AsyncSessionLocal() as db:
        await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.PRE_SHIPMENT,
            document_type=None,
            active=False,
            actor_id="admin-user",
        )
    async with db_services.AsyncSessionLocal() as db:
        row = await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.PRE_SHIPMENT,
            document_type=None,
            active=True,
            actor_id="admin-user",
        )
    assert (row.version, row.active) == (was + 2, True)


async def test_a_company_category_cannot_be_required_of_a_deal():
    """``ENTITY_KYC`` is filed against a company (architecture §3.4), so requiring
    it of a deal would be a rule no deal could ever satisfy — refused rather than
    stored."""
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError) as caught:
            await DealRequiredDocumentsService(db).set_requirement(
                category=DocumentCategory.ENTITY_KYC,
                document_type=None,
                active=True,
                actor_id="admin-user",
            )
    assert "not a deal" in str(caught.value)


async def test_a_change_that_changes_nothing_is_refused():
    """An append-only table should not fill up with versions that repeat the
    previous one."""
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError) as caught:
            await DealRequiredDocumentsService(db).set_requirement(
                category=DocumentCategory.PRE_SHIPMENT,
                document_type=None,
                active=True,
                actor_id="admin-user",
            )
    assert "already required" in str(caught.value)


async def test_raw_sql_cannot_update_or_delete_a_requirement():
    """The append-only trigger, proved around the service."""
    async with db_services.AsyncSessionLocal() as db:
        row_id = (await DealRequiredDocumentsService(db).active())[0].id

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            for statement in (
                "UPDATE onboarding.deal_required_document SET active = false WHERE id = %s",
                "DELETE FROM onboarding.deal_required_document WHERE id = %s",
            ):
                with pytest.raises(psycopg2.errors.RaiseException):
                    cursor.execute(statement, (str(row_id),))
                connection.rollback()
    finally:
        connection.close()


async def test_one_requirement_cannot_be_added_twice_at_one_version():
    """``uq_deal_required_document_key_version``. Checked in the database because
    ``''`` is a sentinel for "any type" precisely so this constraint bites — two
    NULLs would not collide."""
    connection = _raw_sql()
    try:
        with connection.cursor() as cursor, pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(
                "INSERT INTO onboarding.deal_required_document "
                "(category, document_type, version, active, source) "
                "VALUES ('PRE_SHIPMENT', '', 1, true, 'test');"
            )
        connection.rollback()
    finally:
        connection.close()


# ── 2. The policy ────────────────────────────────────────────────────────────


async def test_a_deal_with_no_documents_is_missing_the_required_category():
    deal_id = await _deal_with_a_buyer(await _customer())
    assert await _missing(deal_id) == ("PRE_SHIPMENT",)


async def test_any_document_in_the_category_satisfies_the_seeded_rule(tmp_path: Path):
    """The seeded rule names no type, so a purchase order does as well as a
    proforma invoice (IQ-10)."""
    deal_id = await _deal_with_a_buyer(await _customer())
    await _upload(
        deal_id,
        tmp_path,
        category=DocumentCategory.PRE_SHIPMENT,
        document_type="purchase_order",
    )
    assert await _missing(deal_id) == ()


async def test_a_document_in_another_category_does_not_satisfy_it(tmp_path: Path):
    deal_id = await _deal_with_a_buyer(await _customer())
    await _upload(
        deal_id,
        tmp_path,
        category=DocumentCategory.SHIPPING,
        document_type="bill_of_lading",
    )
    assert await _missing(deal_id) == ("PRE_SHIPMENT",)


@pytest.mark.parametrize(
    "status",
    [
        DocumentScanStatus.PENDING_SCAN,
        DocumentScanStatus.QUARANTINED,
        DocumentScanStatus.SCAN_FAILED,
    ],
)
async def test_only_an_available_document_counts(
    status: DocumentScanStatus, tmp_path: Path
):
    """IQ-11. "We have not scanned it" and "it is clean" must not collapse into
    one outcome — the same rule the download route applies."""
    deal_id = await _deal_with_a_buyer(await _customer())
    await _upload(
        deal_id, tmp_path, category=DocumentCategory.PRE_SHIPMENT, status=status
    )
    assert await _missing(deal_id) == ("PRE_SHIPMENT",)


async def test_a_requirement_naming_a_type_needs_that_type(tmp_path: Path):
    deal_id = await _deal_with_a_buyer(await _customer())
    async with db_services.AsyncSessionLocal() as db:
        await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.SHIPPING,
            document_type="bill_of_lading",
            active=True,
            actor_id="admin-user",
        )

    # A different type in the same category does not satisfy it.
    await _upload(
        deal_id,
        tmp_path,
        category=DocumentCategory.SHIPPING,
        document_type="packing_list",
    )
    assert "SHIPPING (bill_of_lading)" in await _missing(deal_id)

    await _upload(
        deal_id,
        tmp_path,
        category=DocumentCategory.SHIPPING,
        document_type="bill_of_lading",
    )
    assert "SHIPPING (bill_of_lading)" not in await _missing(deal_id)


async def test_no_requirements_means_nothing_is_missing():
    deal_id = await _deal_with_a_buyer(await _customer())
    async with db_services.AsyncSessionLocal() as db:
        await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.PRE_SHIPMENT,
            document_type=None,
            active=False,
            actor_id="admin-user",
        )
    assert await _missing(deal_id) == ()


# ── 3. The guard, through the routes ─────────────────────────────────────────


async def test_the_handover_is_refused_and_names_the_missing_category(
    client: AsyncClient, clear_background_check
):
    """Task 2.3's acceptance criterion."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal_id = await _deal_with_a_buyer(await _customer())

    detail = await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))
    assert "missing required documents: PRE_SHIPMENT" in (
        detail.json()["handover_blocked_reason"] or ""
    )
    assert "HANDED_OVER" not in {
        move["to_stage"] for move in detail.json()["allowed_stage_moves"]
    }

    resp = await client.post(
        f"{BASE}/deals/{deal_id}/transitions",
        json={"to_stage": "HANDED_OVER"},
        headers=auth_header(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DEAL_HANDOVER_BLOCKED"
    assert "PRE_SHIPMENT" in resp.json()["detail"]


async def test_every_unmet_condition_is_named_at_once(client: AsyncClient):
    """The paperwork condition joins the others rather than replacing them: an
    operator must not have to fix one to discover the next (contract §4.1)."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    # No substitution, and a company left at LEAD→PROSPECT: so the journey, the
    # check and the paperwork are all unmet.
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = ExporterJourney.PROSPECT
        await db.commit()
    deal_id = await _deal_with_a_buyer(company_id)

    reason = (
        await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))
    ).json()["handover_blocked_reason"]
    assert reason == (
        "the company is PROSPECT, not CUSTOMER; "
        "the background check is NOT_STARTED, not CLEAR; "
        "missing required documents: PRE_SHIPMENT"
    )


async def test_the_handover_goes_through_once_the_document_is_there(
    client: AsyncClient, clear_background_check, tmp_path: Path
):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    deal_id = await _deal_with_a_buyer(await _customer())
    await _upload(deal_id, tmp_path, category=DocumentCategory.PRE_SHIPMENT)

    resp = await client.post(
        f"{BASE}/deals/{deal_id}/transitions",
        json={"to_stage": "HANDED_OVER"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "HANDED_OVER"


async def test_a_deal_handed_over_before_the_rule_existed_is_not_re_judged(
    clear_background_check, tmp_path: Path
):
    """The guard runs on the move, never retrospectively — so turning a
    requirement on does not invalidate a past handover."""
    deal_id = await _deal_with_a_buyer(await _customer())
    await _upload(deal_id, tmp_path, category=DocumentCategory.PRE_SHIPMENT)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="t"
        )

    async with db_services.AsyncSessionLocal() as db:
        await DealRequiredDocumentsService(db).set_requirement(
            category=DocumentCategory.BUYER,
            document_type=None,
            active=True,
            actor_id="admin-user",
        )

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).get_deal(deal_id)
    assert view.stage is DealStage.HANDED_OVER
    # Terminal, so no move is offered and no reason is served: there is nothing to
    # be blocked from.
    assert view.allowed_stage_moves == ()
    assert view.handover_blocked_reason is None


# ── The routes' own rules ────────────────────────────────────────────────────


async def test_staff_may_read_the_rule_and_only_admin_may_change_it(
    client: AsyncClient,
):
    for role in (UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.DEVELOPER):
        token = await token_with_role(client, role)
        resp = await client.get(SETTINGS, headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        # The screen offers the controls from the server, not from the role.
        assert resp.json()["can_edit"] is False

    admin = await token_with_role(client, UserRole.ADMIN)
    resp = await client.get(SETTINGS, headers=auth_header(admin))
    assert resp.json()["can_edit"] is True
    # The seeded rule is in force. Other tests in this file leave *inactive* keys
    # behind — `requirements` shows a removed requirement rather than hiding it —
    # so this asserts what is active, not the whole list.
    assert [
        (row["category"], row["document_type"])
        for row in resp.json()["requirements"]
        if row["active"]
    ] == [("PRE_SHIPMENT", None)]


async def test_admin_adds_and_removes_a_category_through_the_routes(
    client: AsyncClient,
):
    """Task 2.2's acceptance criterion: ADMIN can add/remove a category, and the
    history of changes is kept."""
    admin = await token_with_role(client, UserRole.ADMIN)
    # A real configured type — an unconfigured one is refused (see below). Its key
    # may already have versions from earlier runs on this database, so the
    # assertions are about increments from wherever it stands (`_version_of`).
    document_type = "buyer_rating_report"
    was = await _version_of(DocumentCategory.BUYER, document_type)

    added = await client.post(
        SETTINGS,
        json={"category": "BUYER", "document_type": document_type},
        headers=auth_header(admin),
    )
    assert added.status_code == 201, added.text
    assert added.json()["version"] == was + 1
    assert added.json()["active"] is True
    assert added.json()["document_type"] == document_type

    removed = await client.post(
        SETTINGS,
        json={"category": "BUYER", "document_type": document_type, "active": False},
        headers=auth_header(admin),
    )
    assert removed.status_code == 201, removed.text
    assert removed.json()["version"] == was + 2

    rule = (await client.get(SETTINGS, headers=auth_header(admin))).json()
    history = [
        (row["version"], row["active"])
        for row in rule["history"]
        if row["category"] == "BUYER" and row["document_type"] == document_type
    ]
    assert history[:2] == [(was + 2, False), (was + 1, True)]


@pytest.mark.parametrize(
    ("category", "document_type"),
    [
        # A typo of a real type: what an administrator typing free text produces.
        ("PRE_SHIPMENT", "Proforma Invoice"),
        # A real type, but configured under another category.
        ("PRE_SHIPMENT", "bill_of_lading"),
    ],
)
async def test_a_type_the_settings_do_not_configure_cannot_be_required(
    client: AsyncClient, category: str, document_type: str
):
    """The upload route refuses a type the document settings do not configure under
    the category, so a requirement naming one could never be met and every handover
    would be blocked by it. Refused with the upload route's own code, and nothing is
    written."""
    admin = await token_with_role(client, UserRole.ADMIN)
    before = await _version_of(DocumentCategory(category), document_type)

    resp = await client.post(
        SETTINGS,
        json={"category": category, "document_type": document_type},
        headers=auth_header(admin),
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "DOCUMENT_TYPE_NOT_ALLOWED"
    assert await _version_of(DocumentCategory(category), document_type) == before


async def test_stopping_a_requirement_that_was_never_made_is_refused():
    """A key nobody ever required is already "not required", so writing a first
    version that says so would be a change that changes nothing."""
    category, document_type = DocumentCategory.INSURANCE, "marine_certificate"
    assert (category, document_type) not in await _active_keys()
    before = await _version_of(category, document_type)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError) as caught:
            await DealRequiredDocumentsService(db).set_requirement(
                category=category,
                document_type=document_type,
                active=False,
                actor_id="admin-user",
            )

    assert "already not required" in str(caught.value)
    assert await _version_of(category, document_type) == before


async def test_two_administrators_changing_one_requirement_at_once(
    monkeypatch: pytest.MonkeyPatch,
):
    """Both read the same current version and write the next one;
    ``uq_deal_required_document_key_version`` lets the first in, and the second gets
    409 ``DEAL_REQUIRED_DOCUMENT_CHANGED`` with nothing saved — not a 500.

    The race is made deterministic by giving the second writer the rule as it
    stood before the first one committed, which is exactly what it read."""
    category, document_type = DocumentCategory.BUYER, "buyer_kyc"
    async with db_services.AsyncSessionLocal() as db:
        stale = await DealRequiredDocumentsService(db).current()
    was = await _version_of(category, document_type)

    async with db_services.AsyncSessionLocal() as db:
        first = await DealRequiredDocumentsService(db).set_requirement(
            category=category, document_type=document_type, active=True, actor_id="first"
        )
    assert first.version == was + 1

    async with db_services.AsyncSessionLocal() as db:
        second = DealRequiredDocumentsService(db)

        async def _as_it_was() -> list[DealRequiredDocument]:
            return stale

        monkeypatch.setattr(second, "current", _as_it_was)
        with pytest.raises(DealRequiredDocumentChangedError) as caught:
            await second.set_requirement(
                category=category, document_type=document_type, active=True, actor_id="second"
            )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "DEAL_REQUIRED_DOCUMENT_CHANGED"
    async with db_services.AsyncSessionLocal() as db:
        versions = [
            (row.version, row.created_by)
            for row in await DealRequiredDocumentsService(db).history()
            if row.category is category and row.document_type == document_type
        ]
    assert versions[0] == (was + 1, "first"), "only the first change was saved"


async def test_a_company_only_category_is_refused_by_the_route(client: AsyncClient):
    admin = await token_with_role(client, UserRole.ADMIN)
    resp = await client.post(
        SETTINGS, json={"category": "ENTITY_KYC"}, headers=auth_header(admin)
    )
    assert resp.status_code == 422, resp.text


async def test_the_stored_sentinel_never_reaches_a_caller(client: AsyncClient):
    """``''`` is a database detail. A caller sees ``null``, and sends ``null`` or
    nothing at all."""
    admin = await token_with_role(client, UserRole.ADMIN)
    body = (await client.get(SETTINGS, headers=auth_header(admin))).json()
    assert all(
        row["document_type"] is None or row["document_type"] != ""
        for row in body["requirements"] + body["history"]
    )

    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalars(select(DealRequiredDocument.document_type))
    assert "" in set(stored), "the seeded rule stores the sentinel, not NULL"
