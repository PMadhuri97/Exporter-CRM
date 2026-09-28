"""Polling safety — **owner: Developer 4B** (4B-3; ``docs/dev4/4b-task.md`` §5.2, L4-02).

Invariant: a reviewed result is never silently changed by a later provider answer.

* service: a reviewed result is unchanged by ``get_verification_status`` and the
  ignored answer is logged with the provider's new values;
* service: an unreviewed result still updates, and its status change is recorded in
  history;
* database: ``trg_verification_result_outcome_freeze`` refuses the write however it
  arrives (the direct-SQL cases are in ``test_l4b_verification_schema.py``; here the
  ORM path that bypasses the service is refused too).

Uses an asynchronous vendor double registered for the test, as
``test_exp2_verification_service.py`` does — polling has no production caller, and no
scheduler is added.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

import app.modules.onboarding.application.verification_service as verification_service_module
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.workflow_dependencies import (
    VERIFICATION_ADAPTER_REGISTRY,
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    register_adapter,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._l4b_support import history_rows, pg
from app.platform.database import services as db_services
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum

pytestmark = pytest.mark.asyncio


class _PollableVendor:
    PROVIDER = "l4b_pollable_vendor"
    STATE: dict[str, VerificationOutcome] = {}

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=self.PROVIDER,
            supported_verification_types=tuple(VerificationType),
            supported_entity_types=tuple(VerificationEntityType),
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request) -> VerificationOutcome:
        ref = request.payload["provider_reference"]
        outcome = VerificationOutcome(
            provider=self.PROVIDER,
            provider_reference=ref,
            status=VerificationResultStatus(request.payload.get("status", "PENDING")),
            normalized_result={"stage": "first"},
        )
        self.STATE[ref] = outcome
        return outcome

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        return self.STATE[provider_reference]

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=1)


@pytest.fixture
def vendor():
    register_adapter(_PollableVendor.PROVIDER, _PollableVendor)
    yield _PollableVendor
    VERIFICATION_ADAPTER_REGISTRY.pop(_PollableVendor.PROVIDER, None)


async def _trigger(company_id: uuid.UUID, reference: str, status: str) -> VerificationResult:
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).trigger_verification(
            VerificationType.KYB,
            VerificationEntityType.EXPORTER,
            company_id,
            provider=_PollableVendor.PROVIDER,
            payload={"provider_reference": reference, "status": status},
            actor_id="tester",
        )


def _provider_now_says(reference: str) -> VerificationOutcome:
    outcome = VerificationOutcome(
        provider=_PollableVendor.PROVIDER,
        provider_reference=reference,
        status=VerificationResultStatus.FAILED,
        normalized_result={"stage": "late", "hit": "sanctions list"},
        risk_level=VerificationRiskLevel.HIGH,
    )
    _PollableVendor.STATE[reference] = outcome
    return outcome


async def _poll(reference: str) -> VerificationResult:
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).get_verification_status(reference)


async def _stored(result_id: uuid.UUID) -> VerificationResult:
    async with db_services.AsyncSessionLocal() as db:
        return await db.get(VerificationResult, result_id)


class _RecordingLogger:
    def __init__(self, real):
        self._real = real
        self.events: list[dict] = []

    def __getattr__(self, level):
        def log(event, **fields):
            self.events.append({"event": event, "level": level, **fields})
            return getattr(self._real, level)(event, **fields)

        return log


async def test_a_reviewed_result_is_unchanged_by_polling_and_the_update_is_logged(
    vendor, monkeypatch
):
    """L4-02's "done when": a reviewed result is unchanged by polling."""
    company_id = await make_company()
    reference = f"poll-{uuid.uuid4().hex[:10]}"
    result = await _trigger(company_id, reference, "PASSED")
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by="c1", review_status=VerificationReviewStatus.ACCEPTED
        )
    _provider_now_says(reference)

    recorder = _RecordingLogger(verification_service_module.logger)
    monkeypatch.setattr(verification_service_module, "logger", recorder)
    polled = await _poll(reference)
    logs = recorder.events

    stored = await _stored(result.id)
    for row in (polled, stored):
        assert row.status is VerificationResultStatus.PASSED
        assert row.risk_level is None
        assert row.normalized_result == {"stage": "first"}
        assert row.valid_until is None

    [ignored] = [e for e in logs if e["event"] == "verification.status_polled.ignored_reviewed"]
    assert ignored["level"] == "warning"
    assert ignored["verification_result_id"] == str(result.id)
    assert ignored["provider_status"] == "FAILED"
    assert ignored["provider_risk_level"] == "HIGH"
    assert ignored["provider_normalized_result"] == {"stage": "late", "hit": "sanctions list"}

    with pg() as cur:  # no status-change history row either
        assert [row[0] for row in history_rows(cur, company_id)] == [
            "verification_initial",
            "verification_reviewed",
        ]


async def test_an_unreviewed_result_still_updates_and_records_the_change(vendor):
    company_id = await make_company()
    reference = f"poll-{uuid.uuid4().hex[:10]}"
    result = await _trigger(company_id, reference, "PENDING")
    _provider_now_says(reference)

    polled = await _poll(reference)

    stored = await _stored(result.id)
    for row in (polled, stored):
        assert row.status is VerificationResultStatus.FAILED
        assert row.risk_level is VerificationRiskLevel.HIGH
        assert row.normalized_result == {"stage": "late", "hit": "sanctions list"}

    with pg() as cur:
        rows = history_rows(cur, company_id)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("verification_initial", None, "PENDING", "tester"),
        ("verification_transition", "PENDING", "FAILED", None),  # the provider, not a person
    ]


async def test_a_poll_with_no_new_answer_writes_nothing(vendor):
    company_id = await make_company()
    reference = f"poll-{uuid.uuid4().hex[:10]}"
    result = await _trigger(company_id, reference, "PENDING")
    before = await _stored(result.id)

    await _poll(reference)

    after = await _stored(result.id)
    assert after.updated_at == before.updated_at
    with pg() as cur:
        assert len(history_rows(cur, company_id)) == 1


async def test_the_database_refuses_a_reviewed_outcome_change_that_bypasses_the_service(vendor):
    """Defence in depth: an ORM write straight to the row, not via polling."""
    company_id = await make_company()
    reference = f"poll-{uuid.uuid4().hex[:10]}"
    result = await _trigger(company_id, reference, "PASSED")
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by="c1", review_status=VerificationReviewStatus.REJECTED
        )

    async with db_services.AsyncSessionLocal() as db:
        row = await db.get(VerificationResult, result.id)
        row.status = VerificationResultStatus.FAILED
        with pytest.raises(DBAPIError, match="has been reviewed"):
            await db.commit()

    assert (await _stored(result.id)).status is VerificationResultStatus.PASSED
