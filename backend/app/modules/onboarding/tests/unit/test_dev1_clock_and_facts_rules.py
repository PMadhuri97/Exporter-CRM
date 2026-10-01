"""The injectable clock (plan P0-5) and the pure compliance-facts rules (F1, IQ-2,
BQ-5) — Developer 1. No database."""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.domain import compliance_facts
from app.modules.onboarding.domain.compliance_facts import (
    LEGACY_CLEAR_VALIDITY,
    ComplianceFactsReader,
    PartyComplianceFacts,
    check_state,
    is_current,
    legacy_clear_expiry,
)
from app.modules.onboarding.domain.compliance_inputs import VerificationInput
from app.shared import clock
from app.shared.clock import FixedClock, SystemClock, use_clock

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

# ── The clock ────────────────────────────────────────────────────────────────


def test_the_default_clock_is_the_system_clock_and_is_aware():
    assert isinstance(clock.current_clock(), SystemClock)
    now = clock.now()
    assert now.tzinfo is not None
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_use_clock_installs_a_fixed_clock_and_restores_the_previous_one():
    before = clock.current_clock()
    with use_clock(FixedClock(T0)) as fixed:
        assert clock.now() == T0
        fixed.advance(timedelta(days=366))
        assert clock.now() == T0 + timedelta(days=366)
        fixed.set(T0 - timedelta(days=1))
        assert clock.now() == T0 - timedelta(days=1)
    assert clock.current_clock() is before


def test_use_clock_restores_the_clock_even_when_the_block_raises():
    before = clock.current_clock()
    with pytest.raises(RuntimeError), use_clock(FixedClock(T0)):
        raise RuntimeError("boom")
    assert clock.current_clock() is before


def test_a_fixed_clock_refuses_a_naive_datetime_and_normalises_to_utc():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 10, 1, 9, 0))
    ist = timezone(timedelta(hours=5, minutes=30))
    fixed = FixedClock(datetime(2026, 10, 1, 14, 30, tzinfo=ist))
    assert fixed.now() == T0
    assert fixed.now().utcoffset() == timedelta(0)


# ── Expiry (decision E, BQ-5) ────────────────────────────────────────────────


def test_a_legacy_clear_is_current_for_one_year_from_its_decision():
    assert LEGACY_CLEAR_VALIDITY == timedelta(days=365)
    expires = legacy_clear_expiry(T0)
    assert expires == T0 + timedelta(days=365)
    assert is_current(expires, T0 + timedelta(days=364))
    assert not is_current(expires, expires)  # expired at the instant, not after it
    assert not is_current(expires, expires + timedelta(seconds=1))
    assert not is_current(None, T0)


# ── Sanctions and AML (IQ-2) ─────────────────────────────────────────────────


def _check(
    verification_type: str = "SANCTIONS",
    status: str = "PASSED",
    *,
    review: str | None = None,
    placeholder: bool = False,
    at: datetime = T0,
) -> VerificationInput:
    return VerificationInput(
        verification_result_id=uuid.uuid4(),
        verification_type=verification_type,
        entity_type="EXPORTER",
        provider="manual",
        status=status,
        risk_level=None,
        performed_at=at,
        is_placeholder=placeholder,
        latest_review_id=uuid.uuid4() if review else None,
        latest_review_status=review,
        latest_reviewed_at=at if review else None,
        evidence_document_ids=(),
    )


@pytest.mark.parametrize(
    ("status", "review", "expected"),
    [
        ("PASSED", None, "PASSED"),
        ("FAILED", None, "FAILED"),
        ("REVIEW", "ACCEPTED", "PASSED"),  # IQ-2
        ("REVIEW", "REJECTED", "FAILED"),  # this contract's reading (lead to confirm)
        ("REVIEW", "ESCALATED", "PENDING"),
        ("REVIEW", None, "PENDING"),
        ("PENDING", None, "PENDING"),
        # IQ-2's wording: a PASSED or FAILED result reads as its status.
        ("PASSED", "REJECTED", "PASSED"),
        ("FAILED", "ACCEPTED", "FAILED"),
    ],
)
def test_the_latest_result_decides_the_state(status, review, expected):
    assert check_state([_check(status=status, review=review)], "SANCTIONS") == expected


def test_no_result_of_that_type_is_missing():
    assert check_state([], "SANCTIONS") == "MISSING"
    assert check_state([_check("AML", "PASSED")], "SANCTIONS") == "MISSING"


def test_placeholders_never_count():
    """IQ-2: "placeholders never count" — neither as a result nor as the latest."""
    assert check_state([_check(status="PENDING", placeholder=True)], "SANCTIONS") == "MISSING"
    newest_first = [
        _check(status="PENDING", placeholder=True, at=T0),
        _check(status="FAILED", at=T0 - timedelta(days=1)),
    ]
    assert check_state(newest_first, "SANCTIONS") == "FAILED"


def test_the_latest_result_wins_over_an_earlier_one():
    """The seam serves results newest first; a later PASSED overrides a FAILED and the
    reverse."""
    later_pass = [_check(status="PASSED", at=T0), _check(status="FAILED", at=T0 - timedelta(1))]
    later_fail = [_check(status="FAILED", at=T0), _check(status="PASSED", at=T0 - timedelta(1))]
    assert check_state(later_pass, "SANCTIONS") == "PASSED"
    assert check_state(later_fail, "SANCTIONS") == "FAILED"


# ── The published interface (allocation F1) ──────────────────────────────────


def test_party_compliance_facts_has_exactly_the_allocation_fields():
    assert [field.name for field in dataclasses.fields(PartyComplianceFacts)] == [
        "background_check",
        "is_clear",
        "clear_expires_at",
        "is_clear_current",
        "sanctions",
        "aml",
    ]


@pytest.mark.parametrize(
    ("method", "parameters"),
    [("for_company", ["self", "company_id", "now"]), ("for_legacy_buyer", ["self", "deal_buyer_id", "now"])],
)
def test_the_service_implements_the_reader_protocol(method, parameters):
    protocol_method = getattr(ComplianceFactsReader, method)
    service_method = getattr(ComplianceFactsService, method)
    assert inspect.iscoroutinefunction(service_method)
    assert list(inspect.signature(protocol_method).parameters) == parameters
    assert list(inspect.signature(service_method).parameters) == parameters


def test_the_domain_module_is_pure():
    """Other lanes import it; it must not pull in I/O."""
    source = inspect.getsource(compliance_facts)
    for forbidden in ("sqlalchemy", "AsyncSession", "app.modules.onboarding.application"):
        assert forbidden not in source, forbidden
