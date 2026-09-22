"""S1T4 — KybVendorRegistryService integration tests.

All tests run against a real database. The suite owns every row whose
``vendor_id`` starts with ``s1t4_`` and wipes them before and after each test,
so tests are order-independent and survive a crashed prior run.

Acceptance criteria covered:
  AC1  Middesk registers with US as a supported country.
  AC2  Trulioo registers with India (and a set of international countries).
  AC3  US + supported entity type lookup returns the Middesk-like vendor.
  AC4  India + supported entity type lookup returns the Trulioo-like vendor.
  AC5  Unsupported country / entity type returns a manual_review result.
  AC6  register / update-health use Epic 2.3 idempotency keys (scope
       "kyb_vendor_registry"); repeated calls with the same key replay.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.onboarding.application.kyb_vendor_registry_service import (
    KybVendorRegistryService,
)
from app.modules.onboarding.infrastructure.kyb_vendor_seed_loader import (
    load_kyb_vendor_registry,
)
from app.platform.database import services as db_services
from app.platform.idempotency.services import derive_internal_key
from app.shared.contracts.kyb import KYBVendorCapabilityDeclaration
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum
from app.shared.exceptions import NotFoundError

_PREFIX = "s1t4_"


# ── helpers ───────────────────────────────────────────────────────────────────


def _vid(name: str) -> str:
    return f"{_PREFIX}{name}_{uuid.uuid4().hex[:8]}"


def _key(step: str = "register_kyb_vendor") -> str:
    """A fresh Epic 2.3 internal-derived key for one operation."""
    return derive_internal_key(str(uuid.uuid4()), step)


def _declaration(
    vendor_id: str,
    *,
    countries: list[str],
    entity_types: list[str] | None = None,
    name: str | None = None,
    mode: KYBVendorProcessingMode = KYBVendorProcessingMode.SYNCHRONOUS,
) -> KYBVendorCapabilityDeclaration:
    return KYBVendorCapabilityDeclaration(
        vendor_id=vendor_id,
        vendor_name=name or vendor_id,
        supported_countries=countries,
        supported_entity_types=["CORPORATION"] if entity_types is None else entity_types,
        processing_mode=mode,
    )


_DIRECT_INSERT_SQL = text(
    """
    INSERT INTO onboarding.kyb_vendor_registration
        (id, vendor_id, vendor_name, supported_countries, supported_entity_types,
         processing_mode, capability_declaration, created_at, updated_at)
    VALUES
        (:id, :vendor_id, :vendor_name, CAST(:countries AS jsonb), CAST(:entity_types AS jsonb),
         CAST(:mode AS onboarding.kyb_vendor_processing_mode_enum), CAST(:cap AS jsonb),
         now(), now())
    """
)


async def _direct_insert(db, vendor_id: str, *, capability_declaration: dict | None = None) -> None:
    """Insert a row with raw SQL, bypassing KybVendorRegistryService entirely.

    Used only by the BUILD.md #12 direct-SQL constraint tests below — every other
    test in this file goes through the service.
    """
    await db.execute(
        _DIRECT_INSERT_SQL,
        {
            "id": str(uuid.uuid4()),
            "vendor_id": vendor_id,
            "vendor_name": "Direct SQL Vendor",
            "countries": json.dumps(["US"]),
            "entity_types": json.dumps(["CORPORATION"]),
            "mode": KYBVendorProcessingMode.SYNCHRONOUS.value,
            "cap": json.dumps(capability_declaration or {"vendor_id": vendor_id}),
        },
    )


async def _wipe() -> None:
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM onboarding.kyb_vendor_registration WHERE vendor_id LIKE :p"),
            {"p": f"{_PREFIX}%"},
        )
        await db.commit()


@pytest.fixture(autouse=True)
async def _isolate_kyb_registry():
    await _wipe()
    yield
    await _wipe()


async def _count(vendor_id: str) -> int:
    async with db_services.AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT count(*) FROM onboarding.kyb_vendor_registration "
                "WHERE vendor_id = :v"
            ),
            {"v": vendor_id},
        )
        return int(result.scalar_one())


# ── AC1 / AC2 — registration ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_middesk_registers_with_us():
    vid = _vid("middesk")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        vendor = await svc.register_vendor(
            _declaration(vid, countries=["US"], name="Middesk"),
            idempotency_key=_key(),
        )

    assert vendor.vendor_id == vid
    assert vendor.supported_countries == ["US"]
    assert vendor.health_status == VendorHealthStatusEnum.HEALTHY
    assert vendor.processing_mode == KYBVendorProcessingMode.SYNCHRONOUS


@pytest.mark.asyncio
async def test_trulioo_registers_with_india():
    vid = _vid("trulioo")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        vendor = await svc.register_vendor(
            _declaration(vid, countries=["IN"], name="Trulioo"),
            idempotency_key=_key(),
        )

    assert vendor.supported_countries == ["IN"]


@pytest.mark.asyncio
async def test_trulioo_registers_with_international_countries():
    vid = _vid("trulioo_intl")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        vendor = await svc.register_vendor(
            _declaration(vid, countries=["IN", "gb", " DE ", "SG", "IN"], name="Trulioo"),
            idempotency_key=_key(),
        )

    # Normalised: trimmed, upper-cased, de-duplicated, order-stable.
    assert vendor.supported_countries == ["IN", "GB", "DE", "SG"]


@pytest.mark.asyncio
async def test_register_vendor_upserts_on_duplicate_vendor_id():
    vid = _vid("upsert")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(vid, countries=["US"], name="V1"), idempotency_key=_key()
        )
        updated = await svc.register_vendor(
            _declaration(vid, countries=["US", "CA"], name="V2"), idempotency_key=_key()
        )

    assert updated.vendor_name == "V2"
    assert updated.supported_countries == ["US", "CA"]
    assert await _count(vid) == 1


@pytest.mark.asyncio
async def test_register_vendor_idempotency_key_replay():
    vid = _vid("replay")
    key = _key()
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        first = await svc.register_vendor(
            _declaration(vid, countries=["US"]), idempotency_key=key
        )
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        second = await svc.register_vendor(
            _declaration(vid, countries=["US", "CA"]), idempotency_key=key
        )

    assert first.id == second.id
    # The replay returned the cached row — the second declaration was not applied.
    assert second.supported_countries == ["US"]
    assert await _count(vid) == 1


@pytest.mark.asyncio
async def test_register_vendor_preserves_health_state_on_reregistration():
    vid = _vid("preserve")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=_key())
        await svc.update_vendor_health(
            vid, status=VendorHealthStatusEnum.DOWN, idempotency_key=_key("update_kyb_vendor_health")
        )
        # Re-register with a fresh declaration + key.
        reregistered = await svc.register_vendor(
            _declaration(vid, countries=["US", "GB"], name="renamed"),
            idempotency_key=_key(),
        )

    assert reregistered.supported_countries == ["US", "GB"]
    assert reregistered.vendor_name == "renamed"
    # Operational state owned by the health monitor is NOT reset.
    assert reregistered.health_status == VendorHealthStatusEnum.DOWN
    assert reregistered.last_health_check_at is not None


@pytest.mark.asyncio
async def test_register_operation_uses_idempotency_scope():
    vid = _vid("scope")
    key = _key()
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=key)

    async with db_services.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT scope_id, operation_type, status, key_type "
                    "FROM ledger.idempotency_record WHERE key_value = :k"
                ),
                {"k": key},
            )
        ).one()

    assert row.scope_id == "kyb_vendor_registry"
    assert row.operation_type == "register_kyb_vendor"
    assert row.status == "completed"
    assert row.key_type == "internal_derived_key"


# ── AC3 / AC4 — vendor lookup ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_us_corporation_lookup_returns_middesk():
    middesk = _vid("middesk")
    trulioo = _vid("trulioo")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(middesk, countries=["US"], name="Middesk"), idempotency_key=_key()
        )
        await svc.register_vendor(
            _declaration(trulioo, countries=["IN", "GB"], name="Trulioo"), idempotency_key=_key()
        )

        result = await svc.get_vendor_for_country("US", "CORPORATION")

    assert result.is_manual_review is False
    assert result.vendor is not None
    assert result.vendor.vendor_id == middesk


@pytest.mark.asyncio
async def test_india_corporation_lookup_returns_trulioo_case_insensitive():
    middesk = _vid("middesk")
    trulioo = _vid("trulioo")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(middesk, countries=["US"], name="Middesk"), idempotency_key=_key()
        )
        await svc.register_vendor(
            _declaration(trulioo, countries=["IN", "GB", "SG"], name="Trulioo"),
            idempotency_key=_key(),
        )

        # lower-case inputs must resolve identically to upper-case.
        result = await svc.get_vendor_for_country("in", "corporation")

    assert result.vendor is not None
    assert result.vendor.vendor_id == trulioo


@pytest.mark.asyncio
async def test_international_country_lookup_returns_trulioo():
    trulioo = _vid("trulioo")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(trulioo, countries=["IN", "GB", "DE"], name="Trulioo"),
            idempotency_key=_key(),
        )
        result = await svc.get_vendor_for_country("DE", "CORPORATION")

    assert result.vendor is not None
    assert result.vendor.vendor_id == trulioo


# ── AC5 — manual review ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_country_returns_manual_review():
    middesk = _vid("middesk")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(middesk, countries=["US"]), idempotency_key=_key()
        )
        result = await svc.get_vendor_for_country("FR", "CORPORATION")

    assert result.is_manual_review is True
    assert result.vendor is None
    assert "FR" in (result.reason or "")


@pytest.mark.asyncio
async def test_unsupported_entity_type_returns_manual_review():
    vid = _vid("corp_only")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(vid, countries=["US"], entity_types=["CORPORATION"]),
            idempotency_key=_key(),
        )
        result = await svc.get_vendor_for_country("US", "TRUST")

    assert result.is_manual_review is True
    assert result.vendor is None


@pytest.mark.asyncio
async def test_empty_supported_entity_types_matches_nothing():
    vid = _vid("any_entity")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(
            _declaration(vid, countries=["US"], entity_types=[]),
            idempotency_key=_key(),
        )
        result = await svc.get_vendor_for_country("US", "FUND")

    # An empty supported_entity_types list is not a wildcard — it matches no type.
    assert result.is_manual_review is True
    assert result.vendor is None


@pytest.mark.asyncio
async def test_manual_review_maps_to_requires_manual_review_enum():
    from app.modules.onboarding.domain.entities.orchestration_enums import KybNormalisedResult
    from app.modules.onboarding.domain.kyb_vendor_selection import (
        MANUAL_REVIEW_NORMALISED_RESULT,
    )

    assert MANUAL_REVIEW_NORMALISED_RESULT is KybNormalisedResult.REQUIRES_MANUAL_REVIEW


# ── Health / selection behaviour ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_vendor_health_changes_status():
    vid = _vid("health")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=_key())
        updated = await svc.update_vendor_health(
            vid,
            status=VendorHealthStatusEnum.DEGRADED,
            idempotency_key=_key("update_kyb_vendor_health"),
        )

    assert updated.health_status == VendorHealthStatusEnum.DEGRADED


@pytest.mark.asyncio
async def test_update_vendor_health_sets_last_health_check_at():
    vid = _vid("health_ts")
    checked_at = datetime.now(UTC) - timedelta(minutes=5)
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        registered = await svc.register_vendor(
            _declaration(vid, countries=["US"]), idempotency_key=_key()
        )
        assert registered.last_health_check_at is None

        updated = await svc.update_vendor_health(
            vid,
            status=VendorHealthStatusEnum.HEALTHY,
            idempotency_key=_key("update_kyb_vendor_health"),
            checked_at=checked_at,
        )

    assert updated.last_health_check_at is not None
    assert abs((updated.last_health_check_at - checked_at).total_seconds()) < 1


@pytest.mark.asyncio
async def test_update_vendor_health_idempotency_replay():
    vid = _vid("health_replay")
    key = _key("update_kyb_vendor_health")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=_key())
        first = await svc.update_vendor_health(
            vid, status=VendorHealthStatusEnum.DOWN, idempotency_key=key
        )
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        # Same key, different requested status — must replay, not re-apply.
        second = await svc.update_vendor_health(
            vid, status=VendorHealthStatusEnum.HEALTHY, idempotency_key=key
        )

    assert first.id == second.id
    assert second.health_status == VendorHealthStatusEnum.DOWN


@pytest.mark.asyncio
async def test_update_vendor_health_unknown_vendor_raises():
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        with pytest.raises(NotFoundError):
            await svc.update_vendor_health(
                _vid("ghost"),
                status=VendorHealthStatusEnum.DOWN,
                idempotency_key=_key("update_kyb_vendor_health"),
            )


@pytest.mark.asyncio
async def test_down_vendor_is_excluded_from_lookup():
    vid = _vid("down")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=_key())
        await svc.update_vendor_health(
            vid,
            status=VendorHealthStatusEnum.DOWN,
            idempotency_key=_key("update_kyb_vendor_health"),
        )
        result = await svc.get_vendor_for_country("US", "CORPORATION")

    assert result.is_manual_review is True


@pytest.mark.asyncio
async def test_degraded_vendor_is_still_selected():
    vid = _vid("degraded")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(vid, countries=["US"]), idempotency_key=_key())
        await svc.update_vendor_health(
            vid,
            status=VendorHealthStatusEnum.DEGRADED,
            idempotency_key=_key("update_kyb_vendor_health"),
        )
        result = await svc.get_vendor_for_country("US", "CORPORATION")

    assert result.vendor is not None
    assert result.vendor.vendor_id == vid


@pytest.mark.asyncio
async def test_selection_prefers_healthy_then_oldest_when_several_match():
    first = _vid("a_first")
    second = _vid("b_second")
    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        await svc.register_vendor(_declaration(first, countries=["US"]), idempotency_key=_key())
        await svc.register_vendor(_declaration(second, countries=["US"]), idempotency_key=_key())

        # Both HEALTHY -> earliest-registered wins.
        r1 = await svc.get_vendor_for_country("US", "CORPORATION")
        assert r1.vendor is not None and r1.vendor.vendor_id == first

        # Degrade the first -> the HEALTHY one wins despite being newer.
        await svc.update_vendor_health(
            first,
            status=VendorHealthStatusEnum.DEGRADED,
            idempotency_key=_key("update_kyb_vendor_health"),
        )
        r2 = await svc.get_vendor_for_country("US", "CORPORATION")
        assert r2.vendor is not None and r2.vendor.vendor_id == second


# ── Startup seed loader ──────────────────────────────────────────────────────


class _FakeMiddeskAdapter:
    """Structural KYB adapter fake — S1T4 does not ship the real Middesk adapter."""

    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        return _declaration(f"{_PREFIX}middesk_seed", countries=["US"], name="Middesk")


class _FakeTruliooAdapter:
    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        return _declaration(
            f"{_PREFIX}trulioo_seed", countries=["IN", "GB", "SG"], name="Trulioo"
        )


@pytest.mark.asyncio
async def test_seed_loader_registers_adapters_and_is_idempotent():
    async with db_services.AsyncSessionLocal() as db:
        registered = await load_kyb_vendor_registry(
            db, adapters=[_FakeMiddeskAdapter, _FakeTruliooAdapter]
        )
    assert {r.vendor_id for r in registered} == {
        f"{_PREFIX}middesk_seed",
        f"{_PREFIX}trulioo_seed",
    }

    # Re-run on a fresh session: the content-derived key short-circuits, no dupes.
    async with db_services.AsyncSessionLocal() as db:
        await load_kyb_vendor_registry(
            db, adapters=[_FakeMiddeskAdapter, _FakeTruliooAdapter]
        )

    assert await _count(f"{_PREFIX}middesk_seed") == 1
    assert await _count(f"{_PREFIX}trulioo_seed") == 1

    async with db_services.AsyncSessionLocal() as db:
        svc = KybVendorRegistryService(db)
        us = await svc.get_vendor_for_country("US", "CORPORATION")
        india = await svc.get_vendor_for_country("IN", "CORPORATION")

    assert us.vendor is not None and us.vendor.vendor_id == f"{_PREFIX}middesk_seed"
    assert india.vendor is not None and india.vendor.vendor_id == f"{_PREFIX}trulioo_seed"


@pytest.mark.asyncio
async def test_concurrent_registration_of_same_vendor_creates_one_row():
    vid = _vid("concurrent")

    async def _register() -> uuid.UUID:
        async with db_services.AsyncSessionLocal() as db:
            svc = KybVendorRegistryService(db)
            vendor = await svc.register_vendor(
                _declaration(vid, countries=["US"]), idempotency_key=_key()
            )
            return vendor.id

    ids = await asyncio.gather(_register(), _register())

    assert ids[0] == ids[1]
    assert await _count(vid) == 1


@pytest.mark.asyncio
async def test_concurrent_registration_with_the_same_idempotency_key_executes_once():
    """Two register_vendor() calls sharing ONE idempotency key (not two, unlike the
    vendor_id-uniqueness test above).

    Epic 2.3's established contract for N concurrent register_key() calls on the same
    (key_value, scope_id) is: exactly one gets "new", the rest get "duplicate" — see
    app/platform/idempotency/tests/test_key_registration_service.py::
    test_concurrent_registrations_10_runs. The loser's INSERT blocks on the winner's
    uncommitted idempotency row (Postgres's documented ON CONFLICT wait-for-conflicting-
    transaction behaviour) and, once the winner commits, observes it as COMPLETED and
    replays its cached response — it never re-runs the vendor upsert. This test proves
    that contract holds through KybVendorRegistryService.register_vendor(): both calls
    return the identical row, and exactly one row exists in each of
    kyb_vendor_registration and the idempotency ledger for this key. No new behaviour is
    invented — this only exercises the existing platform guarantee.
    """
    vid = _vid("same_key")
    key = _key()

    async def _register() -> uuid.UUID:
        async with db_services.AsyncSessionLocal() as db:
            svc = KybVendorRegistryService(db)
            vendor = await svc.register_vendor(
                _declaration(vid, countries=["US"]), idempotency_key=key
            )
            return vendor.id

    ids = await asyncio.gather(_register(), _register())

    # The operation executed exactly once: both callers observe the same row.
    assert ids[0] == ids[1]
    assert await _count(vid) == 1

    async with db_services.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT count(*), "
                    "count(*) FILTER (WHERE status = 'completed') "
                    "FROM ledger.idempotency_record "
                    "WHERE key_value = :k AND scope_id = :s"
                ),
                {"k": key, "s": "kyb_vendor_registry"},
            )
        ).one()

    # Exactly one idempotency record for this key — no duplicate registration row —
    # and it settled to completed, not left dangling active.
    assert row[0] == 1
    assert row[1] == 1


# ── BUILD.md #12 — direct-SQL constraint tests ────────────────────────────────
#
# Each test bypasses KybVendorRegistryService entirely and writes raw SQL via
# SQLAlchemy text(), so the assertion is against the database constraint itself —
# not against the application's ON CONFLICT / upsert path, which would swallow the
# very violation these tests exist to observe.


@pytest.mark.asyncio
async def test_direct_sql_duplicate_vendor_id_violates_unique_constraint():
    """uq_kyb_vendor_registration_vendor_id rejects a second row for the same vendor_id."""
    vid = _vid("direct_unique")

    async with db_services.AsyncSessionLocal() as db:
        await _direct_insert(db, vid)
        await db.commit()

        with pytest.raises(IntegrityError) as exc:
            await _direct_insert(db, vid)
        assert "uq_kyb_vendor_registration_vendor_id" in str(exc.value)
        await db.rollback()


@pytest.mark.asyncio
async def test_direct_sql_oversized_capability_declaration_violates_check_constraint():
    """ck_kyb_vendor_registration_cap_decl_size rejects capability_declaration over 64KB.

    The oversized payload is inserted directly via SQL, never passed through
    KYBVendorCapabilityDeclaration/Pydantic — this proves the database CHECK
    constraint itself, not application-level validation.
    """
    vid = _vid("direct_check")
    # octet_length(capability_declaration::text) must exceed 65536 bytes.
    oversized = {"padding": "x" * 70_000}
    assert len(json.dumps(oversized)) > 65536

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(IntegrityError) as exc:
            await _direct_insert(db, vid, capability_declaration=oversized)
        assert "ck_kyb_vendor_registration_cap_decl_size" in str(exc.value)
        await db.rollback()

    assert await _count(vid) == 0


@pytest.mark.asyncio
async def test_direct_sql_vendor_id_update_violates_immutability_trigger():
    """trg_kyb_vendor_registration_field_immutability rejects changing vendor_id.

    The trigger raises a PL/pgSQL exception (not a constraint violation), so
    SQLAlchemy/asyncpg wrap it as DBAPIError rather than IntegrityError — the same
    distinction test_s1t1_orchestration_schema.py draws between RaiseException and
    ForeignKeyViolation/UniqueViolation for this project's other immutability
    triggers. Asserting IntegrityError here would silently accept an exception the
    trigger does not actually raise.
    """
    vid = _vid("direct_trigger")

    async with db_services.AsyncSessionLocal() as db:
        await _direct_insert(db, vid)
        await db.commit()

        with pytest.raises(DBAPIError) as exc:
            await db.execute(
                text(
                    "UPDATE onboarding.kyb_vendor_registration "
                    "SET vendor_id = :new_id WHERE vendor_id = :old_id"
                ),
                {"new_id": f"{vid}_mutated", "old_id": vid},
            )
        assert "immutable" in str(exc.value)
        assert "vendor_id" in str(exc.value)
        await db.rollback()

    # The row survived unchanged under its original vendor_id.
    assert await _count(vid) == 1
    assert await _count(f"{vid}_mutated") == 0
