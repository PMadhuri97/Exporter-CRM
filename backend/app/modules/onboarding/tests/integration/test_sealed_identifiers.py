"""Migration 0064 against the real database: the identifier and address columns hold a
ciphertext from now on, rows written before stay plain, and the constraints and
lookups behave as they did.

Raw SQL (psycopg2) is what looks at the stored bytes, and what writes a row the old
way: neither goes through ``SealedString``.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.onboarding.application.gst_registration_service import (
    GstRegistrationService,
)
from app.modules.onboarding.domain.entities.company_address import CompanyAddress
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.gst_states import state_code_of
from app.modules.onboarding.infrastructure.repositories.exporter_profile_repository import (
    ExporterProfileRepository,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.platform.security.sealed_type import looks_keyed, looks_sealed

pytestmark = pytest.mark.asyncio


def _pan() -> str:
    """A PAN nothing else uses: the suite's database persists between runs."""
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str) -> str:
    return f"27{pan}1Z5"


def _raw_sql():
    return psycopg2.connect(
        get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    )


def _stored(sql: str, *params: object) -> object:
    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]
    finally:
        connection.close()


def _execute(sql: str, *params: object) -> None:
    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


async def _set_identifiers(company_id: uuid.UUID, **values: str | None) -> None:
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        for field, value in values.items():
            setattr(profile, field, value)
        await db.commit()


# ── Identifiers ─────────────────────────────────────────────────────────────


async def test_a_pan_iec_and_cin_are_stored_sealed_and_read_back_plain():
    company_id = await make_company()
    pan = _pan()
    await _set_identifiers(
        company_id,
        pan=pan,
        iec="AABCU9603R",
        cin="U12345MH2020PTC123456",
        identity_type="IN_PAN",
    )

    for column in ("pan", "iec", "cin"):
        stored = _stored(
            f"SELECT {column} FROM onboarding.exporter_profile WHERE customer_id = %s",  # noqa: S608
            str(company_id),
        )
        assert looks_sealed(stored), (column, stored)

    async with db_services.AsyncSessionLocal() as db:
        profile = await ExporterProfileRepository(db).get_by_pan(pan)
        assert profile is not None and profile.customer_id == company_id
        assert (profile.pan, profile.iec, profile.cin) == (
            pan,
            "AABCU9603R",
            "U12345MH2020PTC123456",
        )


async def test_a_pan_written_before_sealing_is_still_found():
    """Existing rows are not re-written, so a lookup has to find the plain form too."""
    company_id = await make_company()
    pan = _pan()
    _execute(
        "UPDATE onboarding.exporter_profile SET pan = %s, identity_type = 'IN_PAN'"
        " WHERE customer_id = %s",
        pan,
        str(company_id),
    )

    async with db_services.AsyncSessionLocal() as db:
        profile = await ExporterProfileRepository(db).get_by_pan(pan)
        assert profile is not None and profile.customer_id == company_id
        assert profile.pan == pan


async def test_the_database_still_refuses_a_second_company_with_the_same_pan():
    """`uq_exporter_profile_pan` over two sealed copies of one PAN."""
    pan = _pan()
    await _set_identifiers(await make_company(), pan=pan, identity_type="IN_PAN")
    with pytest.raises(IntegrityError, match="uq_exporter_profile_pan"):
        await _set_identifiers(await make_company(), pan=pan, identity_type="IN_PAN")


async def test_a_malformed_pan_is_still_refused_by_its_check():
    """`SealedString` leaves a malformed value unsealed, so the check sees it as it
    always did."""
    with pytest.raises(IntegrityError, match="ck_exporter_profile_pan_format"):
        await _set_identifiers(await make_company(), pan="abcde1234f", identity_type="IN_PAN")


async def test_the_database_accepts_only_the_shape_of_a_sealed_value():
    """The format checks gained one alternative, not a hole: `d1.` alone is refused."""
    company_id = await make_company()
    connection = _raw_sql()
    try:
        with connection.cursor() as cursor, pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "UPDATE onboarding.exporter_profile SET iec = 'd1. not a ciphertext'"
                " WHERE customer_id = %s",
                (str(company_id),),
            )
    finally:
        connection.close()


# ── GSTINs ──────────────────────────────────────────────────────────────────


async def test_a_gstin_is_stored_sealed_and_found_by_the_duplicate_warning():
    pan = _pan()
    gstin = _gstin(pan)
    first, second = await make_company(), await make_company()
    async with db_services.AsyncSessionLocal() as db:
        for company_id in (first, second):
            db.add(
                ExporterGstin(
                    customer_id=company_id, gstin=gstin, state_code=state_code_of(gstin)
                )
            )
        await db.commit()

    stored = _stored(
        "SELECT gstin FROM onboarding.exporter_gstin WHERE customer_id = %s", str(first)
    )
    assert looks_sealed(stored)

    async with db_services.AsyncSessionLocal() as db:
        service = GstRegistrationService(db)
        assert await service.other_holders(gstin, excluding=first) == [second]
        rows = await service.list_for_company(first)
        assert [row.gstin for row in rows] == [gstin]


async def test_the_same_gstin_twice_on_one_company_is_still_refused():
    pan = _pan()
    company_id = await make_company()
    with pytest.raises(IntegrityError, match="uq_exporter_gstin_customer_gstin"):
        async with db_services.AsyncSessionLocal() as db:
            for _ in range(2):
                db.add(ExporterGstin(customer_id=company_id, gstin=_gstin(pan)))
                await db.flush()


async def test_gstins_added_together_keep_their_alphabetical_order():
    """They share a `created_at`; the tie used to be broken by SQL on the plain value."""
    pan = _pan()
    company_id = await make_company()
    gstins = [f"{code}{pan}1Z5" for code in ("33", "07", "27")]
    async with db_services.AsyncSessionLocal() as db:
        for gstin in gstins:
            db.add(ExporterGstin(customer_id=company_id, gstin=gstin))
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert profile.gstins == sorted(gstins)


# ── Addresses ───────────────────────────────────────────────────────────────


async def test_an_address_is_stored_sealed_and_read_back_plain():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        address = CompanyAddress(
            customer_id=company_id,
            address_type="REGISTERED",
            line1="12 Marine Drive",
            line2="",
            city="Mumbai",
            postal_code="400002",
            country="IN",
        )
        db.add(address)
        await db.commit()
        address_id = address.id

    for column in ("line1", "line2", "city", "postal_code"):
        stored = _stored(
            f"SELECT {column} FROM onboarding.company_address WHERE id = %s",  # noqa: S608
            str(address_id),
        )
        assert looks_sealed(stored), (column, stored)
    assert _stored("SELECT state FROM onboarding.company_address WHERE id = %s", str(address_id)) is None

    async with db_services.AsyncSessionLocal() as db:
        address = await db.get(CompanyAddress, address_id)
        assert (address.line1, address.line2, address.city, address.postal_code) == (
            "12 Marine Drive",
            "",
            "Mumbai",
            "400002",
        )


# ── Registration numbers (0065) ─────────────────────────────────────────────


def _registration() -> str:
    """A registration number nothing else uses: the suite's database persists."""
    return f"KVK {uuid.uuid4().hex[:4].upper()}.{uuid.uuid4().int % 10**5:05d}"


async def _foreign(company_id: uuid.UUID, registration_number: str) -> None:
    await _set_identifiers(
        company_id,
        country="NL",
        registration_number=registration_number,
        identity_type="FOREIGN_REG",
    )


async def _holder(registration_number: str) -> uuid.UUID | None:
    async with db_services.AsyncSessionLocal() as db:
        profile = await ExporterProfileRepository(db).get_by_registration_number(
            country="nl", registration_number=registration_number
        )
        return profile.customer_id if profile is not None else None


async def test_a_registration_number_is_sealed_and_reads_back_as_typed():
    company_id = await make_company()
    registration = _registration()
    await _foreign(company_id, registration)

    stored = _stored(
        "SELECT registration_number FROM onboarding.exporter_profile WHERE customer_id = %s",
        str(company_id),
    )
    assert looks_keyed(stored)
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert profile.registration_number == registration


async def test_a_sealed_registration_is_found_under_another_spelling():
    company_id = await make_company()
    registration = _registration()
    await _foreign(company_id, registration)
    assert await _holder(registration.lower().replace(" ", "-").replace(".", "")) == company_id


async def test_a_registration_written_before_sealing_is_still_found():
    company_id = await make_company()
    registration = _registration()
    _execute(
        "UPDATE onboarding.exporter_profile SET country = 'NL', registration_number = %s,"
        " identity_type = 'FOREIGN_REG' WHERE customer_id = %s",
        registration,
        str(company_id),
    )
    assert await _holder(registration.lower().replace(" ", "")) == company_id


async def test_the_database_refuses_one_registration_twice_in_a_country():
    """Two spellings of one number, both sealed: `uq_..._registration_key`."""
    registration = _registration()
    await _foreign(await make_company(), registration)
    with pytest.raises(IntegrityError, match="uq_exporter_profile_country_registration_key"):
        await _foreign(await make_company(), registration.lower().replace(".", "-"))


async def test_the_same_registration_in_another_country_is_allowed():
    registration = _registration()
    await _foreign(await make_company(), registration)
    await _set_identifiers(
        await make_company(),
        country="DE",
        registration_number=registration,
        identity_type="FOREIGN_REG",
    )
