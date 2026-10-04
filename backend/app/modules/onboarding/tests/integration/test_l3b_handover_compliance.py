"""The handover guard's compliance conditions, wired to Developer 1's real reader —
**owner: Developer 2** (plan P3-3b, P3-4, P4-7; allocation task 2.5).

``test_l3b_handover_conditions.py`` proves the rules against fakes. This file proves
the **wiring**: that ``DealService`` hands Developer 1's ``ComplianceFactsService`` to
the guard, so a real expired Clear and a real ``FAILED`` sanctions result on a real
company actually stop a handover. Before task 2.5 the conditions existed and were
inert, which is exactly the kind of gap a fake cannot catch.

It also pins the lock order P4-7 asks for: both parties share-locked, sorted by
``customer_id``, so a handover and a flag on the buyer cannot interleave.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.storage_service import StorageService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome
from app.modules.onboarding.infrastructure.storage import LocalDiskStorage
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import record_required_checks
from app.modules.onboarding.tests.integration._dev1_support import cleared_company
from app.modules.onboarding.tests.integration.test_l3b_handover import (
    record_legacy_buyer_checks,
)
from app.platform.database import services as db_services
from app.shared.clock import FixedClock, use_clock

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4 proforma invoice"


class _CleanScanner:
    name = "fake"

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        return ScanOutcome(status=DocumentScanStatus.AVAILABLE, scanner_name=self.name)


async def _cleared_customer() -> uuid.UUID:
    """A company that is really a ``CUSTOMER`` with a really current ``CLEAR``.

    Nothing is substituted. ``cleared_company`` is Developer 1's own helper — it
    answers the checklist, records rule B's three checks and takes the company to
    CLEAR through the maker-checker — so the facts the guard reads below are the ones
    their reader derives from real rows, not from a shape this file invented.

    The journey is then set directly: A5's first half is not what this file is about,
    and the promotion belongs to Developer 3's service.
    """
    company_id = await cleared_company(await make_company())

    async with db_services.AsyncSessionLocal() as db:
        company = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert company.background_check.value == "CLEAR", "the helper should have cleared it"
        company.journey = ExporterJourney.CUSTOMER
        await db.commit()
    return company_id


async def _deal_ready(
    company_id: uuid.UUID,
    *,
    buyer_company_id: uuid.UUID | None = None,
    check_the_legacy_buyer: bool = True,
):
    """A deal at ``GATHERING_PAPERWORK`` with a buyer and its required document."""
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference=f"Compliance {uuid.uuid4().hex[:8]}", actor_id="t"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id, name="Rotterdam Trading BV", country="NL", actor_id="t"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            view.id, DealStage.GATHERING_PAPERWORK, actor_id="t"
        )
    storage = StorageService(
        LocalDiskStorage(root=Path(tempfile.mkdtemp(prefix="req-"))), _CleanScanner()
    )
    async with db_services.AsyncSessionLocal() as db:
        await DocumentService(db, storage=storage).upload(
            PDF,
            deal_id=view.id,
            category=DocumentCategory.PRE_SHIPMENT,
            document_type="proforma_invoice",
            source=DocumentSource.EXPORTER_UPLOAD,
            file_name="proforma-invoice.pdf",
            content_type="application/pdf",
            actor_id="t",
        )
    if buyer_company_id is None and check_the_legacy_buyer:
        # BQ-4 applies to the legacy buyer too, and a test about the seller's own
        # standing should not have the buyer's clauses in its expected message.
        await record_legacy_buyer_checks(view.id)
    if buyer_company_id is not None:
        # Nothing writes this column until task 2.4, so set it directly — this file
        # is about the guard reading it, not about the route that fills it.
        async with db_services.AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE onboarding.deal SET buyer_company_id = CAST(:b AS uuid)"
                " WHERE id = CAST(:d AS uuid)"),
                {"b": str(buyer_company_id), "d": str(view.id)},
            )
            await db.commit()
    return view.id


async def _reason(deal_id: uuid.UUID) -> str | None:
    async with db_services.AsyncSessionLocal() as db:
        return (await DealService(db).get_deal(deal_id)).handover_blocked_reason


async def _clear_expires_at(company_id: uuid.UUID) -> datetime:
    """When this company's Clear stops being current.

    Read from the decision rather than computed: `background_check_decision` is
    append-only (Developer 1's immutability trigger refuses UPDATE), so a test cannot
    move a Clear's expiry. It moves **now** instead, with the shared clock — which is
    what `app/shared/clock.py` exists for.
    """
    async with db_services.AsyncSessionLocal() as db:
        expires_at = await db.scalar(
            text(
                "SELECT expires_at FROM onboarding.background_check_decision"
                " WHERE company_id = CAST(:c AS uuid) AND to_value = 'CLEAR'"
                " ORDER BY decided_at DESC LIMIT 1"
            ).bindparams(c=str(company_id))
        )
    assert expires_at is not None, "migration 0027 stores an expiry on every new Clear"
    return expires_at


# ── The wiring itself ────────────────────────────────────────────────────────


async def test_a_cleared_customer_with_its_paperwork_may_hand_over():
    """The baseline. If this fails, every refusal below proves nothing."""
    company_id = await _cleared_customer()
    deal_id = await _deal_ready(company_id)

    assert await _reason(deal_id) is None
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="t"
        )
    assert view.stage is DealStage.HANDED_OVER


async def test_an_expired_clear_blocks_the_handover_and_names_the_date():
    """**The gap task 2.5 closed.** Before it, `NoComplianceFacts` was injected and an
    expired Clear let a handover through — the company column still said CLEAR, so
    condition 2 passed and nothing else looked.

    Time is moved past the expiry with the shared clock rather than by rewriting the
    decision, which the database refuses (it is append-only).
    """
    company_id = await _cleared_customer()
    deal_id = await _deal_ready(company_id)
    expires_at = await _clear_expires_at(company_id)

    assert await _reason(deal_id) is None, "it should be fine before the expiry"

    with use_clock(FixedClock(expires_at + timedelta(days=1))):
        reason = await _reason(deal_id)
        assert reason == (
            f"the background check expired on {expires_at.date().isoformat()}"
        )

        with pytest.raises(Exception) as caught:
            async with db_services.AsyncSessionLocal() as db:
                await DealService(db).transition_stage(
                    deal_id, DealStage.HANDED_OVER, actor_id="t"
                )
        assert getattr(caught.value, "error_code", None) == "DEAL_HANDOVER_BLOCKED"

    # And it is fine again once "now" is back before the expiry — the gauge never
    # moved, which is P3-3b's rule.
    assert await _reason(deal_id) is None


async def test_a_failed_seller_sanctions_result_blocks():
    """Plan BQ-3, through the real reader: the seller's own failed screening stops its
    deals even though the gauge still reads CLEAR (nothing moves the gauge, P3-3b)."""
    company_id = await _cleared_customer()
    deal_id = await _deal_ready(company_id)
    # A newer SANCTIONS result, FAILED. The seam reads newest first, so this is the
    # one the facts report.
    await record_required_checks(company_id, status="FAILED", types=("SANCTIONS",))

    reason = await _reason(deal_id)
    assert reason == "the company's sanctions check has failed"


async def test_the_buyer_companys_checks_are_read_through_the_real_reader():
    """Plan BQ-4: a buyer recorded as a company must have PASSED sanctions and AML.

    A fresh buyer company has neither, so both read `MISSING` — "we have not checked"
    is not "clean", which is the whole point of requiring `PASSED` rather than
    "not FAILED".
    """
    seller_id = await _cleared_customer()
    buyer_id = await make_company()
    deal_id = await _deal_ready(seller_id, buyer_company_id=buyer_id)

    assert await _reason(deal_id) == (
        "the buyer's sanctions check is MISSING, not PASSED; "
        "the buyer's AML check is MISSING, not PASSED"
    )

    # Record them, and the condition clears.
    await record_required_checks(buyer_id, types=("SANCTIONS", "AML"))
    assert await _reason(deal_id) is None


async def test_a_legacy_deal_buyer_is_read_through_for_legacy_buyer():
    """A deal whose buyer is still a `deal_buyer` row has its checks keyed to that
    row. The guard must reach them, or every pre-migration deal would be refused for
    checks nobody can record against a company that does not exist yet."""
    company_id = await _cleared_customer()
    deal_id = await _deal_ready(company_id, check_the_legacy_buyer=False)

    # Unchecked, so MISSING on both — read through `for_legacy_buyer`, which is the
    # only way to reach a `deal_buyer` row's checks.
    assert await _reason(deal_id) == (
        "the buyer's sanctions check is MISSING, not PASSED; "
        "the buyer's AML check is MISSING, not PASSED"
    )

    # And recording them against the `deal_buyer` row clears the condition, which is
    # what keeps every pre-migration deal handover-able.
    await record_legacy_buyer_checks(deal_id)
    assert await _reason(deal_id) is None


# ── The lock order (P4-7) ────────────────────────────────────────────────────


async def test_both_parties_are_share_locked_sorted_by_customer_id():
    """P4-7's deadlock rule, read off the statement the guard actually ran.

    Asserting on `pg_locks` would be flaky; asserting the SQL carries `ORDER BY
    customer_id` with `FOR SHARE` pins the property that matters — two transactions
    locking the same pair take them in one order.
    """
    seller_id = await _cleared_customer()
    buyer_id = await make_company()
    deal_id = await _deal_ready(seller_id, buyer_company_id=buyer_id)

    seen: list[str] = []
    async with db_services.AsyncSessionLocal() as db:
        service = DealService(db)
        deal = await service._lock_deal(deal_id)  # noqa: SLF001 - pinning the statement

        original = db.scalars

        async def recording(statement, *args, **kwargs):
            # Compiled against the real dialect: `str(select)` renders the generic
            # form and silently drops `FOR SHARE`, so the plain string would make
            # this test pass even if the lock were gone.
            seen.append(str(statement.compile(dialect=postgresql.dialect())).lower())
            return await original(statement, *args, **kwargs)

        db.scalars = recording  # type: ignore[method-assign]
        await service._handover_blocked_reason(deal, lock=True)  # noqa: SLF001

    company_reads = [sql for sql in seen if "exporter_profile" in sql]
    assert company_reads, "the guard must read the company rows"
    locking = [sql for sql in company_reads if "for share" in sql]
    assert locking, "on the move the read must take FOR SHARE (D10)"
    one = locking[0]
    assert "customer_id in" in one, "both parties in one statement, so one lock order"
    assert "order by" in one and "customer_id" in one.split("order by")[1], (
        "the lock order must be by customer_id, or two handovers sharing a pair of "
        "companies can deadlock"
    )


async def test_a_handover_and_a_flag_on_the_buyer_do_not_interleave():
    """The race P4-7 closes, end to end.

    The handover is paused after its guard — holding `FOR SHARE` on both parties — and
    a `FOR UPDATE` read of the **buyer** is attempted. It must wait. Developer 1 adds
    the compliance-side version of this (flag by proposal and approval) once 2.5
    merges; this is the lock itself.
    """
    seller_id = await _cleared_customer()
    buyer_id = await make_company()
    # BQ-4, or the guard refuses and the handover never reaches the pause below.
    await record_required_checks(buyer_id, types=("SANCTIONS", "AML"))
    deal_id = await _deal_ready(seller_id, buyer_company_id=buyer_id)

    guard_passed = asyncio.Event()
    release = asyncio.Event()
    original = DealService._handover_snapshot

    async def paused(self, deal):
        guard_passed.set()
        await release.wait()
        return await original(self, deal)

    DealService._handover_snapshot = paused  # type: ignore[method-assign]
    try:

        async def hand_over():
            async with db_services.AsyncSessionLocal() as db:
                return await DealService(db).transition_stage(
                    deal_id, DealStage.HANDED_OVER, actor_id="t"
                )

        async def lock_the_buyer():
            async with db_services.AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        "SELECT customer_id FROM onboarding.exporter_profile"
                        " WHERE customer_id = CAST(:c AS uuid) FOR UPDATE"
                    ),
                    {"c": str(buyer_id)},
                )
                await db.commit()
                return "locked"

        handover = asyncio.create_task(hand_over())
        await asyncio.wait_for(guard_passed.wait(), timeout=10)

        writer = asyncio.create_task(lock_the_buyer())
        done, _ = await asyncio.wait({writer}, timeout=2)
        assert not done, "a write to the buyer ran while a handover held its share lock"

        release.set()
        view = await asyncio.wait_for(handover, timeout=10)
        assert view.stage is DealStage.HANDED_OVER
        assert await asyncio.wait_for(writer, timeout=10) == "locked"
    finally:
        DealService._handover_snapshot = original  # type: ignore[method-assign]
        release.set()


async def test_a_handover_and_a_flag_on_its_invoicing_branch_do_not_interleave():
    """R-18: the same race, for the branch rule (P6-7). A flag used to lock only the
    ``exporter_gstin`` row, so it completed while the handover held its share lock on
    the seller — and the deal went to the lending team through a branch flagged a
    moment before. The flag now takes the seller's row first, so it waits for the
    handover; the next guard reads it.
    """
    from app.modules.onboarding.application.gst_registration_service import (
        GstRegistrationService,
    )

    seller_id = await _cleared_customer()
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    pan = f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"
    async with db_services.AsyncSessionLocal() as db:
        branch, _others = await GstRegistrationService(db).add(
            seller_id, gstin=f"27{pan}1Z5", actor_id="t"
        )
    buyer_id = await make_company()
    await record_required_checks(buyer_id, types=("SANCTIONS", "AML"))
    deal_id = await _deal_ready(seller_id, buyer_company_id=buyer_id)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=branch.id, actor_id="t"
        )

    guard_passed = asyncio.Event()
    release = asyncio.Event()
    original = DealService._handover_snapshot

    async def paused(self, deal):
        guard_passed.set()
        await release.wait()
        return await original(self, deal)

    DealService._handover_snapshot = paused  # type: ignore[method-assign]
    try:

        async def hand_over():
            async with db_services.AsyncSessionLocal() as db:
                return await DealService(db).transition_stage(
                    deal_id, DealStage.HANDED_OVER, actor_id="t"
                )

        async def flag_the_branch():
            async with db_services.AsyncSessionLocal() as db:
                flagged, _others = await GstRegistrationService(db).flag(
                    branch.id, reason="Returns unfiled", actor_id="compliance-1"
                )
                return flagged.flag_status.value

        handover = asyncio.create_task(hand_over())
        await asyncio.wait_for(guard_passed.wait(), timeout=10)

        flag = asyncio.create_task(flag_the_branch())
        done, _ = await asyncio.wait({flag}, timeout=2)
        assert not done, "a branch flag committed while a handover held its share lock"

        release.set()
        view = await asyncio.wait_for(handover, timeout=10)
        assert view.stage is DealStage.HANDED_OVER
        assert await asyncio.wait_for(flag, timeout=10) == "FLAGGED"
    finally:
        DealService._handover_snapshot = original  # type: ignore[method-assign]
        release.set()
