"""``convert_gst_addresses``: a GST branch's free-text address becomes a linked company
address, so nothing typed in is lost before the text column goes.

The text is staged with raw SQL: no route writes it any more.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.gst_registration_service import GstRegistrationService
from app.modules.onboarding.convert_gst_addresses import (
    CITY_NOT_RECORDED,
    apply,
    resolve,
    split_lines,
    validate,
)
from app.modules.onboarding.domain.entities.company_address import CompanyAddress
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.tests.integration._verification_support import pg
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


async def _company_with_branches(*states: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            name=f"Convert Co {uuid.uuid4().hex[:8]}",
            country="IN",
            pan=pan,
        )
    ids = []
    for state in states:
        async with db_services.AsyncSessionLocal() as db:
            registration, _ = await GstRegistrationService(db).add(
                customer_id, gstin=f"{state}{pan}1Z5", actor_id="tester"
            )
            ids.append(registration.id)
    return customer_id, ids


def _set_text(branch_id: uuid.UUID, text: str) -> None:
    with pg() as cur:
        cur.execute(
            "UPDATE onboarding.exporter_gstin SET address = %s WHERE id = %s",
            (text, str(branch_id)),
        )


async def _run() -> dict[str, int]:
    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    async with db_services.AsyncSessionLocal() as db:
        return await apply(db, report, run_id="test", actor_id="convert:test")


async def _branch(branch_id: uuid.UUID) -> ExporterGstin:
    async with db_services.AsyncSessionLocal() as db:
        return await db.get(ExporterGstin, branch_id)


async def _address(address_id: uuid.UUID) -> CompanyAddress:
    async with db_services.AsyncSessionLocal() as db:
        return await db.get(CompanyAddress, address_id)


async def test_a_branch_text_becomes_its_linked_correspondence_address():
    _company, [branch_id] = await _company_with_branches("27")
    _set_text(branch_id, "  Unit 12,   Industrial Estate, Pune ")

    counts = await _run()

    assert counts["addresses_created"] >= 1
    branch = await _branch(branch_id)
    assert branch.address_id is not None
    address = await _address(branch.address_id)
    assert address.address_type == "CORRESPONDENCE"
    assert (address.line1, address.line2) == ("Unit 12, Industrial Estate, Pune", None)
    assert (address.city, address.state, address.country) == (
        CITY_NOT_RECORDED,
        "Maharashtra",
        "IN",
    )


async def test_branches_of_one_company_with_the_same_text_share_one_address():
    _company, [first, second] = await _company_with_branches("27", "29")
    _set_text(first, "5 Dockyard Road, Mumbai")
    _set_text(second, "5 dockyard road,  MUMBAI")

    await _run()

    one, two = await _branch(first), await _branch(second)
    assert one.address_id is not None and one.address_id == two.address_id


async def test_a_second_run_creates_nothing():
    _company, [branch_id] = await _company_with_branches("07")
    _set_text(branch_id, "Plot 4, Okhla, Delhi")
    await _run()
    linked = (await _branch(branch_id)).address_id

    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    assert branch_id not in {b for group in report.groups for b in group.branch_ids}
    assert (await _branch(branch_id)).address_id == linked


async def test_text_too_long_for_two_lines_is_reported_and_left():
    _company, [branch_id] = await _company_with_branches("24")
    _set_text(branch_id, "x" * 600)

    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    assert branch_id in {row[0] for row in report.too_long}
    await _run()
    assert (await _branch(branch_id)).address_id is None
    async with db_services.AsyncSessionLocal() as db:
        [(label, left)] = await validate(db)
    assert left >= 1, label
    # Leave nothing behind for the next test's validation count.
    with pg() as cur:
        cur.execute(
            "UPDATE onboarding.exporter_gstin SET address = NULL WHERE id = %s", (str(branch_id),)
        )


async def test_a_long_text_runs_into_line_two():
    text = "A" * 255 + " Block B"
    assert split_lines(text) == ("A" * 255, "Block B")


async def test_validation_counts_branches_still_unconverted():
    _company, [branch_id] = await _company_with_branches("33")
    _set_text(branch_id, "Guindy, Chennai")
    async with db_services.AsyncSessionLocal() as db:
        before = (await validate(db))[0][1]
    await _run()
    async with db_services.AsyncSessionLocal() as db:
        after = (await validate(db))[0][1]
    assert before >= 1 and after < before
    async with db_services.AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(ExporterGstin.address_id).where(ExporterGstin.id == branch_id)
            )
        ) is not None
