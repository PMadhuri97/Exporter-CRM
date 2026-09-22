"""Integration tests for S7T1: the onboarding service API (`OnboardingRequestService`).

Follows `test_s1t4_kyb_vendor_registry.py`'s conventions: real Postgres, no
per-test rollback, each test opens its own `AsyncSessionLocal()` session(s)
directly. Isolation here comes from every test minting its own fresh
`tenant_id` / `customer_id` / `onboarding_id` (UUIDs), not from a shared
prefix + wipe fixture — none of these tests query "all rows of a table", only
rows reachable from ids the test itself created, so cross-test data never
overlaps.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.onboarding.application.onboarding_request_service import (
    OnboardingRequestService,
)
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingDocumentType,
    OnboardingEntityType,
    OnboardingRequestStatus,
    UboControlType,
)
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.domain.policies.onboarding_next_action import (
    NEXT_REQUIRED_ACTION,
)
from app.modules.onboarding.infrastructure.repositories import (
    OnboardingRequestRepository,
    UboRecordRepository,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


def _tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _idem_key() -> str:
    """A fresh Epic 2.3 customer key. `validate_customer_key` requires UUIDv4."""
    return str(uuid.uuid4())


def _address() -> dict:
    return {"street": "1 Test St", "city": "Testville", "state": "CA", "postal_code": "00000", "country": "US"}


def _empty_document_requirements() -> DocumentRequirementsService:
    """A minimal, structurally valid config with no profiles/rules — keeps the
    document-requirements calculation out of tests that aren't about it."""
    return DocumentRequirementsService(
        {"version": "1.0", "profiles": [], "conditional_rules": [], "validity_periods": {}}
    )


async def _initiate(
    svc: OnboardingRequestService,
    *,
    idempotency_key: str | None = None,
    legal_name: str = "Test Corp",
    initial_user_email: str = "founder@testcorp.example",
) -> tuple[OnboardingRequest, bool]:
    return await svc.initiate_onboarding(
        tenant_id=_tenant_id(),
        entity_type=OnboardingEntityType.CORPORATION,
        legal_name=legal_name,
        registration_number=f"REG-{uuid.uuid4().hex[:8]}",
        incorporation_country="US",
        registered_address=_address(),
        initial_user_email=initial_user_email,
        idempotency_key=idempotency_key or _idem_key(),
    )


# ── Initiate onboarding: idempotency ─────────────────────────────────────────


async def test_initiate_onboarding_creates_draft_request():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, created = await _initiate(svc)

    assert created is True
    assert request.status == OnboardingRequestStatus.DRAFT
    assert request.customer_id is not None
    assert request.initial_user_id == "founder@testcorp.example"


async def test_initiate_onboarding_duplicate_idempotency_key_returns_existing_record():
    tenant_id = _tenant_id()
    idem_key = _idem_key()

    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        first, first_created = await svc.initiate_onboarding(
            tenant_id=tenant_id,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="Dup Corp",
            registration_number="REG-DUP-1",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_email="founder@dupcorp.example",
            idempotency_key=idem_key,
        )

    # A second call, same idempotency_key, different session — proves the
    # replay is read from the committed row/idempotency record, not an
    # in-memory cache on the first session.
    async with db_services.AsyncSessionLocal() as db:
        svc2 = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        second, second_created = await svc2.initiate_onboarding(
            tenant_id=tenant_id,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="Dup Corp — Different Name On Retry",
            registration_number="REG-DUP-DIFFERENT",
            incorporation_country="IN",
            registered_address={"country": "IN"},
            initial_user_email="someone-else@example.com",
            idempotency_key=idem_key,
        )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    # The replay returns the ORIGINAL record — the differing fields on the
    # second call were never applied.
    assert second.legal_name == "Dup Corp"
    assert second.registration_number == "REG-DUP-1"

    # Exactly one row exists for this (tenant, idempotency_key) pair.
    async with db_services.AsyncSessionLocal() as db:
        requests_repo = OnboardingRequestRepository(db)
        by_key = await requests_repo.get_by_tenant_and_idempotency_key(tenant_id, idem_key)
        assert by_key is not None
        assert by_key.id == first.id
        all_for_customer = await requests_repo.list_by_customer(first.customer_id)
        assert len(all_for_customer) == 1


# ── Submit entity details ────────────────────────────────────────────────────


async def test_submit_entity_details_transitions_draft_to_entity_verification():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)

        updated = await svc.submit_entity_details(
            request.id,
            sector_code="DNFBP",
            corridor_intent=["US_IN"],
            declared_monthly_volume_usd=750_000,
        )

    assert updated.status == OnboardingRequestStatus.ENTITY_VERIFICATION_IN_PROGRESS
    assert updated.industry_code == "DNFBP"
    assert updated.corridor_intent == ["US_IN"]
    assert updated.declared_monthly_volume_usd == 750_000


async def test_submit_entity_details_rejects_when_not_in_draft():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        await svc.submit_entity_details(request.id, sector_code="STANDARD")

        with pytest.raises(ValidationError):
            await svc.submit_entity_details(request.id, sector_code="STANDARD_AGAIN")


# ── Submit document ───────────────────────────────────────────────────────────


async def test_submit_document_creates_record_and_updates_tracking():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        activity_before = request.last_activity_at

        document = await svc.submit_document(
            request.id,
            document_type=OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
            storage_path="s3://docs/cert.pdf",
            file_name="cert.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
        )

        status_view = await svc.get_onboarding_status(request.id)

    assert document.document_type == OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION
    assert document.storage_path == "s3://docs/cert.pdf"
    assert document.onboarding_request_id == request.id

    received_types = {d.document_type for d in status_view.documents.received}
    assert "CERTIFICATE_OF_INCORPORATION" in received_types

    async with db_services.AsyncSessionLocal() as db:
        refreshed = await db.get(OnboardingRequest, request.id)
        assert refreshed is not None
        assert activity_before is not None
        assert refreshed.last_activity_at >= activity_before


async def test_submit_document_tracking_accumulates_across_multiple_submissions():
    """Each `submit_document` call adds one row — tracking accumulates, nothing merges."""
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)

        await svc.submit_document(
            request.id,
            document_type=OnboardingDocumentType.CERTIFICATE_OF_INCORPORATION,
            storage_path="s3://docs/cert-v1.pdf",
            file_name="cert-v1.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        status_after_one = await svc.get_onboarding_status(request.id)

        await svc.submit_document(
            request.id,
            document_type=OnboardingDocumentType.PROOF_OF_ADDRESS,
            storage_path="s3://docs/poa.pdf",
            file_name="poa.pdf",
            mime_type="application/pdf",
            size_bytes=256,
        )
        status_after_two = await svc.get_onboarding_status(request.id)

    assert len(status_after_one.documents.received) == 1
    assert len(status_after_two.documents.received) == 2
    assert {d.document_type for d in status_after_two.documents.received} == {
        "CERTIFICATE_OF_INCORPORATION",
        "PROOF_OF_ADDRESS",
    }


# ── Submit UBO declaration ────────────────────────────────────────────────────


async def test_submit_ubo_declaration_creates_correct_number_of_records():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)

        created = await svc.submit_ubo_declaration(
            request.id,
            ubo_details=[
                {
                    "first_name": "Alice",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    "ownership_percentage": "40.00",
                },
                {
                    "first_name": "Bob",
                    "last_name": "Owner",
                    "control_type": UboControlType.INDIRECT_OWNERSHIP,
                    "ownership_percentage": "35.00",
                },
                {
                    "first_name": "Carla",
                    "last_name": "Owner",
                    "control_type": "VOTING_RIGHTS",
                    "ownership_percentage": "25.00",
                },
            ],
        )

    assert len(created) == 3
    assert {u.first_name for u in created} == {"Alice", "Bob", "Carla"}

    async with db_services.AsyncSessionLocal() as db:
        ubo_repo = UboRecordRepository(db)
        stored = await ubo_repo.list_by_onboarding_request(request.id)
    assert len(stored) == 3


async def test_submit_ubo_declaration_requires_at_least_one_entry():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)

        with pytest.raises(ValidationError):
            await svc.submit_ubo_declaration(request.id, ubo_details=[])


# ── Get status: next required action across states ──────────────────────────


async def test_get_status_next_required_action_for_draft():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        status_view = await svc.get_onboarding_status(request.id)

    assert status_view.status == OnboardingRequestStatus.DRAFT
    assert status_view.next_required_action == NEXT_REQUIRED_ACTION[OnboardingRequestStatus.DRAFT]
    assert status_view.next_required_action == "submit_entity_details"


async def test_get_status_next_required_action_for_entity_verification_in_progress():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        await svc.submit_entity_details(request.id, sector_code="STANDARD")
        status_view = await svc.get_onboarding_status(request.id)

    assert status_view.status == OnboardingRequestStatus.ENTITY_VERIFICATION_IN_PROGRESS
    assert status_view.next_required_action == "await_kyb_vendor_result"


async def test_get_status_next_required_action_for_pending_compliance_approval():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        request.status = OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL
        await db.commit()

        status_view = await svc.get_onboarding_status(request.id)

    assert status_view.next_required_action == "await_compliance_officer_decision"


async def test_get_status_pending_review_reason_populated_for_under_review():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        request.status = OnboardingRequestStatus.UNDER_REVIEW
        request.rejection_reason = "Potential sanctions list match requires investigation"
        await db.commit()

        status_view = await svc.get_onboarding_status(request.id)

    assert status_view.next_required_action == "await_manual_review_resolution"
    assert status_view.pending_review_reason == "Potential sanctions list match requires investigation"


async def test_get_status_ubo_progress_counts():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        await svc.submit_ubo_declaration(
            request.id,
            ubo_details=[
                {
                    "first_name": "Verified",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    "kyc_result": "VERIFIED",
                },
                {
                    "first_name": "Pending",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    "kyc_result": "PENDING",
                },
                {
                    "first_name": "NotStarted",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    # kyc_result omitted -> defaults to NOT_STARTED
                },
            ],
        )
        status_view = await svc.get_onboarding_status(request.id)

    progress = status_view.ubo_progress
    assert progress.total_ubos == 3
    assert progress.verified_count == 1
    assert progress.pending_count == 1
    assert progress.not_started_count == 1
    assert progress.complete is False


# ── Get detail: role-based field redaction ───────────────────────────────────


async def test_get_detail_redacts_sensitive_fields_for_non_compliance_role():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await svc.initiate_onboarding(
            tenant_id=_tenant_id(),
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="Sensitive Corp",
            registration_number="REG-SENSITIVE-1",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_email="founder@sensitive.example",
            idempotency_key=_idem_key(),
            tax_identification_number="12-3456789",
        )
        await svc.submit_ubo_declaration(
            request.id,
            ubo_details=[
                {
                    "first_name": "Secret",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    "identification_type": "PASSPORT",
                    "identification_number": "P1234567",
                }
            ],
        )

        redacted_view = await svc.get_onboarding_detail(
            request.id, requesting_role=UserRole.API_USER
        )
        full_view = await svc.get_onboarding_detail(
            request.id, requesting_role=UserRole.COMPLIANCE
        )

    assert redacted_view.sensitive_fields_redacted is True
    assert redacted_view.tax_identification_number is None
    assert redacted_view.ubo_records[0].identification_number is None

    assert full_view.sensitive_fields_redacted is False
    assert full_view.tax_identification_number == "12-3456789"
    assert full_view.ubo_records[0].identification_number == "P1234567"

    # Non-sensitive fields are identical either way.
    assert redacted_view.legal_name == full_view.legal_name == "Sensitive Corp"
    assert redacted_view.ubo_records[0].first_name == full_view.ubo_records[0].first_name == "Secret"


async def test_get_detail_includes_events_and_documents():
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await _initiate(svc)
        await svc.submit_document(
            request.id,
            document_type=OnboardingDocumentType.PROOF_OF_ADDRESS,
            storage_path="s3://docs/poa.pdf",
            file_name="poa.pdf",
            mime_type="application/pdf",
            size_bytes=512,
        )

        detail = await svc.get_onboarding_detail(request.id, requesting_role=UserRole.COMPLIANCE)

    assert len(detail.documents) == 1
    assert detail.documents[0].document_type == "PROOF_OF_ADDRESS"
    # initiation event + document_received event
    assert len(detail.events) == 2
    assert detail.events[0].event_type == "state_transition"
    assert detail.events[1].event_type == "document_received"


# ── Get history ───────────────────────────────────────────────────────────────


async def test_get_history_returns_reverse_chronological_order():
    customer_id = uuid.uuid4()
    base = datetime(2021, 1, 1, tzinfo=UTC)

    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())

        oldest = OnboardingRequest(
            tenant_id=_tenant_id(),
            idempotency_key=_idem_key(),
            customer_id=customer_id,
            status=OnboardingRequestStatus.REJECTED,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="History Corp Attempt 1",
            registration_number="REG-H1",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_id="founder@history.example",
            created_at=base,
            initiated_at=base,
        )
        middle = OnboardingRequest(
            tenant_id=_tenant_id(),
            idempotency_key=_idem_key(),
            customer_id=customer_id,
            status=OnboardingRequestStatus.ABANDONED,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="History Corp Attempt 2",
            registration_number="REG-H2",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_id="founder@history.example",
            created_at=base + timedelta(days=1),
            initiated_at=base + timedelta(days=1),
        )
        newest = OnboardingRequest(
            tenant_id=_tenant_id(),
            idempotency_key=_idem_key(),
            customer_id=customer_id,
            status=OnboardingRequestStatus.DRAFT,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="History Corp Attempt 3",
            registration_number="REG-H3",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_id="founder@history.example",
            created_at=base + timedelta(days=2),
            initiated_at=base + timedelta(days=2),
        )
        for row in (oldest, middle, newest):
            db.add(row)
        await db.commit()

        history = await svc.get_onboarding_history(customer_id)

    assert [h.legal_name for h in history] == [
        "History Corp Attempt 3",
        "History Corp Attempt 2",
        "History Corp Attempt 1",
    ]
    assert history[0].status == OnboardingRequestStatus.DRAFT
    assert history[-1].status == OnboardingRequestStatus.REJECTED
