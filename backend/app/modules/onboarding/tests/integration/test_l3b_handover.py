"""Handing a deal to the lending team (L3-10).

Assumption A5, architecture §3.6.

**These tests isolate the handover from the background check.** The success-path
tests below put the company at ``CUSTOMER`` directly and **substitute
``read_background_check``** with "CLEAR", so they exercise exactly the code after the
guard — the document snapshot, the history row and the announcement — without
depending on Developer 4's rules. The guard itself is tested unpatched, and refuses.

The whole path with nothing substituted — a real CLEAR decision promoting the company
to ``CUSTOMER`` and its deal being handed over — is ``test_crm_end_to_end.py``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application import deal_service as deal_service_module
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.storage_service import StorageService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.exceptions import DealTerminalError
from app.modules.onboarding.infrastructure.repositories.deal_buyer_repository import (
    DealBuyerRepository,
)
from app.modules.onboarding.infrastructure.storage import LocalDiskStorage
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.platform.messaging.ports import InMemoryEventBus
from app.platform.messaging.schemas import EventType

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
PDF = b"%PDF-1.4 bill of lading"


class _CleanScanner:
    name = "fake"

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        return ScanOutcome(status=DocumentScanStatus.AVAILABLE, scanner_name=self.name)


@pytest.fixture
def clear_background_check(monkeypatch: pytest.MonkeyPatch):
    """Pretend Developer 4's column exists and reads ``CLEAR``.

    The **only** thing substituted is the one-function read seam. Everything the
    handover then does — snapshot, history, event — runs for real against Postgres.
    """
    monkeypatch.setattr(
        deal_service_module, "read_background_check", lambda company: "CLEAR"
    )


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> InMemoryEventBus:
    """An in-memory bus this test can read, injected for the duration.

    ``OnboardingEventPublisher`` resolves the bus at construction, and
    ``DealService`` constructs one per instance, so patching the getter covers every
    service built inside the test.
    """
    injected = InMemoryEventBus()
    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: injected)
    return injected


async def _customer() -> uuid.UUID:
    """A company put at ``CUSTOMER`` directly — assumption A5's first half — so these
    tests do not depend on the promotion. The real promotion is covered by
    ``test_customer_promotion.py``."""
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = ExporterJourney.CUSTOMER
        await db.commit()
    return company_id


async def _deal_ready_to_hand_over(company_id: uuid.UUID) -> uuid.UUID:
    """A deal at ``GATHERING_PAPERWORK`` with a buyer **and its required
    paperwork** — everything but the check.

    The pre-shipment document is here because P2-5b made "the required documents
    are present" a condition of the handover, and migration 0030 seeds one
    requirement: category ``PRE_SHIPMENT``, any type (IQ-10). Without it the guard
    refuses, correctly, and these tests would be exercising that refusal instead
    of what they are about.

    It belongs in this helper rather than in each test because the helper's
    contract is "everything but the check", and the paperwork is now part of
    everything. ``test_l4a_background_check_reader.py`` imports this helper for
    its concurrency tests, so the one change here keeps that lane green too.
    """
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference="Rotterdam shipment", actor_id="tester"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id,
            name="Rotterdam Trading BV",
            country="NL",
            registration_number="NL-8899",
            actor_id="tester",
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            view.id, DealStage.GATHERING_PAPERWORK, actor_id="tester"
        )
    await _add_required_document(view.id)
    await record_legacy_buyer_checks(view.id)
    return view.id


async def record_legacy_buyer_checks(
    deal_id: uuid.UUID, *, status: str = "PASSED"
) -> None:
    """PASSED sanctions and AML on the deal's ``deal_buyer`` row.

    Needed since task 2.5 wired Developer 1's reader: BQ-4 requires the buyer's
    sanctions **and** AML to be ``PASSED``, and a buyer nobody has checked reads
    ``MISSING`` — which is the point of requiring `PASSED` rather than "not FAILED".
    Without these two results the guard refuses, correctly, and a test about anything
    else would be exercising that refusal instead.

    Recorded against ``VerificationEntityType.BUYER`` keyed to the ``deal_buyer`` row,
    which is where ``ComplianceFactsReader.for_legacy_buyer`` reads them.

    Exported (no leading underscore) because
    ``test_l4a_background_check_reader.py`` and
    ``test_dev1_concurrency.py`` reach a real handover through
    ``_deal_ready_to_hand_over`` and need the same two results.
    """
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
        VerificationType,
    )
    from app.modules.onboarding.domain.verification_evidence import VerificationEvidence

    async with db_services.AsyncSessionLocal() as db:
        buyer = await DealBuyerRepository(db).get_for_deal(deal_id)
        assert buyer is not None, "the deal needs its buyer before its buyer's checks"
        buyer_id = buyer.id

    for verification_type in (VerificationType.SANCTIONS, VerificationType.AML):
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).trigger_verification(
                verification_type,
                VerificationEntityType.BUYER,
                buyer_id,
                provider="manual",
                payload={"status": status},
                actor_id="tester",
                evidence=VerificationEvidence(note="Test: screened the buyer."),
            )


async def _deal_with_a_buyer_but_no_paperwork(company_id: uuid.UUID) -> uuid.UUID:
    """A deal at ``GATHERING_PAPERWORK`` with a buyer and **no documents** — what
    ``_deal_ready_to_hand_over`` was before P2-5b.

    Only the two tests about the required-document condition use it; everything
    else wants a deal that can actually be handed over.
    """
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference="Rotterdam shipment, no paperwork", actor_id="tester"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id,
            name="Rotterdam Trading BV",
            country="NL",
            registration_number="NL-8899",
            actor_id="tester",
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            view.id, DealStage.GATHERING_PAPERWORK, actor_id="tester"
        )
    return view.id


async def _add_required_document(deal_id: uuid.UUID) -> uuid.UUID:
    """One ``AVAILABLE`` ``PRE_SHIPMENT`` document, satisfying migration 0030's
    seeded requirement.

    Written through ``DocumentService`` with the clean scanner, like every other
    document in these tests, so the row's ``scan_status`` is ``AVAILABLE`` for the
    real reason rather than being set by hand — only ``AVAILABLE`` counts (IQ-11).

    Its own ``tmp_path`` is not available here (this helper is called from
    fixtures without one), so it writes under a per-deal temporary directory.
    """
    import tempfile

    storage = StorageService(
        LocalDiskStorage(root=Path(tempfile.mkdtemp(prefix="required-doc-"))),
        _CleanScanner(),
    )
    async with db_services.AsyncSessionLocal() as db:
        view = await DocumentService(db, storage=storage).upload(
            PDF,
            deal_id=deal_id,
            category=DocumentCategory.PRE_SHIPMENT,
            document_type="proforma_invoice",
            source=DocumentSource.EXPORTER_UPLOAD,
            file_name="proforma-invoice.pdf",
            content_type="application/pdf",
            actor_id="tester",
        )
    return view.id


async def _add_document(deal_id: uuid.UUID, tmp_path: Path, name: str) -> uuid.UUID:
    storage = StorageService(LocalDiskStorage(root=tmp_path), _CleanScanner())
    async with db_services.AsyncSessionLocal() as db:
        view = await DocumentService(db, storage=storage).upload(
            PDF,
            deal_id=deal_id,
            category=DocumentCategory.SHIPPING,
            document_type="bill_of_lading",
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


# ── The guard, unpatched: it refuses, and says why ───────────────────────────


async def test_the_handover_is_refused_while_the_check_has_not_started():
    """No substitution here: a customer with a buyer and paperwork still cannot be
    handed over while its background check is ``NOT_STARTED`` — "not started" is
    not "clear"."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).get_deal(deal_id)
    assert "background check is NOT_STARTED, not CLEAR" in (view.handover_blocked_reason or "")
    assert DealStage.HANDED_OVER not in {m.to for m in view.allowed_stage_moves}

    with pytest.raises(Exception) as caught:
        await _hand_over(deal_id)
    assert getattr(caught.value, "error_code", None) == "DEAL_HANDOVER_BLOCKED"

    async with db_services.AsyncSessionLocal() as db:
        after = await DealService(db).get_deal(deal_id)
    assert after.stage is DealStage.GATHERING_PAPERWORK
    assert after.handed_over_at is None


async def test_a_prospect_is_refused_even_with_a_clear_check(clear_background_check):
    """A5 is an **and**: a clear check on a company that is not yet a customer is
    still not a handover."""
    company_id = await make_prospect()
    deal_id = await _deal_ready_to_hand_over(company_id)

    with pytest.raises(Exception) as caught:
        await _hand_over(deal_id)
    assert getattr(caught.value, "error_code", None) == "DEAL_HANDOVER_BLOCKED"
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).get_deal(deal_id)
    assert "not CUSTOMER" in (view.handover_blocked_reason or "")


# ── The path after the guard (read the module docstring) ─────────────────────


async def test_a_handover_records_the_stage_the_time_and_the_history(
    clear_background_check, bus
):
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    view = await _hand_over(deal_id)

    assert view.stage is DealStage.HANDED_OVER
    assert view.handed_over_at is not None
    # Terminal: nothing follows, so nothing is offered.
    assert view.allowed_stage_moves == ()

    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(company_id, dimension="deal")
    latest = rows[0]  # newest first
    assert latest.event_type == "deal_transition"
    assert latest.from_status == "GATHERING_PAPERWORK"
    assert latest.to_status == "HANDED_OVER"
    assert latest.deal_id == deal_id


async def test_the_announcement_carries_the_buyer_and_a_document_snapshot(
    clear_background_check, bus, tmp_path: Path
):
    """Architecture §3.6: the lending team is given the deal, its buyer and the list
    of documents the handover rested on."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    first = await _add_document(deal_id, tmp_path, "bol-1.pdf")
    second = await _add_document(deal_id, tmp_path, "bol-2.pdf")

    await _hand_over(deal_id)

    published = [
        envelope
        for envelope in bus.published
        if envelope.event_type is EventType.DEAL_HANDED_OVER
    ]
    assert len(published) == 1
    payload = published[0].payload
    assert payload["deal_id"] == str(deal_id)
    assert payload["company_id"] == str(company_id)
    assert payload["buyer"]["name"] == "Rotterdam Trading BV"
    assert payload["buyer"]["country"] == "NL"
    # A superset, not an equality: `_deal_ready_to_hand_over` also uploaded the
    # PRE_SHIPMENT document migration 0030 requires, and the snapshot is every
    # document on the deal — so asserting equality here would be asserting the
    # requirement's absence.
    assert {str(first), str(second)} <= set(payload["document_ids"])
    # The company is the partition key, so a company's events stay ordered together.
    assert published[0].deal_id == str(deal_id)


async def test_the_document_snapshot_does_not_change_afterwards(
    clear_background_check, bus, tmp_path: Path
):
    """The snapshot is what the handover rested on (architecture §3.6).

    Two guarantees, and the second is stronger than it was when this test was
    written. The snapshot names the documents that existed at the moment of the
    handover — and a handed-over deal now refuses new paperwork outright, so there is
    no later upload to disagree with it. The review asked for that rule; this test is
    where its effect on the snapshot is pinned.
    """
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    at_handover = await _add_document(deal_id, tmp_path, "at-handover.pdf")

    await _hand_over(deal_id)

    payload = next(
        e.payload for e in bus.published if e.event_type is EventType.DEAL_HANDED_OVER
    )
    at_handover_ids = payload["document_ids"]
    assert str(at_handover) in at_handover_ids

    # A later upload is refused, rather than landing outside the snapshot.
    with pytest.raises(DealTerminalError):
        await _add_document(deal_id, tmp_path, "after-handover.pdf")

    # And the history row carries the same list, so the record survives even if the
    # announcement was never received.
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(company_id, dimension="deal")
    assert rows[0].event_metadata["document_ids"] == at_handover_ids


async def test_a_handover_with_no_documents_at_all_is_now_refused(
    clear_background_check, bus
):
    """**This test used to assert the opposite**, and said so: "paperwork is not a
    condition of the handover (assumption A5 names the customer status and the
    check, and nothing else)".

    P2-5b changed that rule deliberately (IQ-10): migration 0030 requires a
    ``PRE_SHIPMENT`` document, so a deal with no paperwork is refused and the
    refusal names the category. It is kept here, inverted, rather than deleted —
    the old behaviour is what a reader of this file would otherwise assume still
    holds.
    """
    company_id = await _customer()
    # Deliberately **not** `_deal_ready_to_hand_over`, which now uploads the
    # required document: this deal has nothing.
    deal_id = await _deal_with_a_buyer_but_no_paperwork(company_id)

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).get_deal(deal_id)
    assert "missing required documents: PRE_SHIPMENT" in (view.handover_blocked_reason or "")
    assert DealStage.HANDED_OVER not in {m.to for m in view.allowed_stage_moves}

    with pytest.raises(Exception) as caught:
        await _hand_over(deal_id)
    assert getattr(caught.value, "error_code", None) == "DEAL_HANDOVER_BLOCKED"
    assert not [e for e in bus.published if e.event_type is EventType.DEAL_HANDED_OVER]


async def test_a_handover_is_allowed_once_the_required_document_is_there(
    clear_background_check, bus
):
    """The other half: the requirement is satisfied by any ``PRE_SHIPMENT``
    document, because the seeded rule names no type (IQ-10)."""
    company_id = await _customer()
    deal_id = await _deal_with_a_buyer_but_no_paperwork(company_id)
    required = await _add_required_document(deal_id)
    # BQ-4's buyer checks too, since 2.5 wired the real reader — this test is about
    # the paperwork condition, not about the buyer's screening.
    await record_legacy_buyer_checks(deal_id)

    view = await _hand_over(deal_id)

    assert view.stage is DealStage.HANDED_OVER
    payload = next(
        e.payload for e in bus.published if e.event_type is EventType.DEAL_HANDED_OVER
    )
    assert payload["document_ids"] == [str(required)]


async def test_a_handed_over_deal_cannot_move_or_be_handed_over_twice(
    clear_background_check, bus
):
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)

    for target in (DealStage.WITHDRAWN, DealStage.HANDED_OVER, DealStage.GATHERING_PAPERWORK):
        with pytest.raises(Exception) as caught:
            async with db_services.AsyncSessionLocal() as db:
                await DealService(db).transition_stage(
                    deal_id, target, reason="anything", actor_id="tester"
                )
        assert getattr(caught.value, "error_code", None) == "DEAL_TERMINAL"

    # Exactly one announcement, however many attempts followed it.
    assert (
        len([e for e in bus.published if e.event_type is EventType.DEAL_HANDED_OVER]) == 1
    )


async def test_a_handed_over_deals_buyer_is_frozen(clear_background_check, bus):
    """What the lending team was given must not be editable afterwards."""
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)
    await _hand_over(deal_id)

    with pytest.raises(Exception) as caught:
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).set_buyer(
                deal_id, name="Someone Else BV", country="DE", actor_id="tester"
            )
    assert getattr(caught.value, "error_code", None) == "DEAL_TERMINAL"


async def test_a_dead_bus_does_not_undo_a_committed_handover(
    clear_background_check, monkeypatch: pytest.MonkeyPatch
):
    """The announcement is best effort (architecture §3.6): the history row is the
    source of truth, so a publish failure must not lose the handover."""

    class _BrokenBus:
        async def publish(self, envelope):  # noqa: ANN001 - test double
            raise RuntimeError("bus is down")

    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: _BrokenBus())

    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    view = await _hand_over(deal_id)
    assert view.stage is DealStage.HANDED_OVER

    async with db_services.AsyncSessionLocal() as db:
        after = await DealService(db).get_deal(deal_id)
    assert after.stage is DealStage.HANDED_OVER
    assert after.handed_over_at is not None


# ── Through the API ──────────────────────────────────────────────────────────


async def test_the_api_refuses_the_handover_and_names_the_reason(client: AsyncClient):
    """Unpatched, through the routes: what an operator sees today."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    detail = await client.get(f"{BASE}/deals/{deal_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text
    assert (
        "background check is NOT_STARTED, not CLEAR" in detail.json()["handover_blocked_reason"]
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


async def test_the_api_hands_over_once_the_check_reads_clear(
    client: AsyncClient, clear_background_check, bus
):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    company_id = await _customer()
    deal_id = await _deal_ready_to_hand_over(company_id)

    resp = await client.post(
        f"{BASE}/deals/{deal_id}/transitions",
        json={"to_stage": "HANDED_OVER"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "HANDED_OVER"
    assert resp.json()["handed_over_at"] is not None
    assert resp.json()["allowed_stage_moves"] == []
