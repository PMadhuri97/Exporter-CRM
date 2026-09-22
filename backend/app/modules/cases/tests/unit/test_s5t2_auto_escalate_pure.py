"""Unit test for `SlaCalculationService.calculate_auto_escalate_at_from_fields`
— the pure sibling added for ANER-4.3-S5T2's `CaseSlaMonitoringService` (see
that module's docstring for why a pure, no-DB variant was needed).

Mirrors `test_s1t2_sla_calculation.py`'s style for `calculate_sla_deadline`:
a hand-built config, no database, testing the formula in isolation.
`calculate_auto_escalate_at` (the pre-existing DB-backed method this one now
sits behind) keeps its own database-backed coverage in
tests/integration/test_s1t2_sla_seed_loading.py — unaffected, since its public
contract did not change.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases.application.sla_service import SlaCalculationService, SlaTarget
from app.modules.cases.exceptions import SlaTargetNotFoundError


@pytest.fixture
def service() -> SlaCalculationService:
    return SlaCalculationService(
        {
            ("TRANSACTION_FLAG", "CRITICAL"): SlaTarget(
                case_type="TRANSACTION_FLAG", severity="CRITICAL",
                sla_hours=1, auto_escalate_at_pct=75,
            ),
            ("SCREENING_REVIEW", "LOW"): SlaTarget(
                case_type="SCREENING_REVIEW", severity="LOW",
                sla_hours=48, auto_escalate_at_pct=90,
            ),
        }
    )


def test_auto_escalate_at_for_a_critical_transaction_flag_is_forty_five_minutes_after_creation(
    service,
):
    """AC (doc, S5T2): "A case at 75% of its critical SLA (45 minutes for a
    transaction_flag critical) is auto-escalated"."""
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    escalate_at = service.calculate_auto_escalate_at_from_fields(
        "TRANSACTION_FLAG", "CRITICAL", created_at
    )
    assert escalate_at == datetime(2026, 9, 17, 10, 45, 0, tzinfo=UTC)


def test_auto_escalate_at_is_case_insensitive_on_lookup(service):
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    escalate_at = service.calculate_auto_escalate_at_from_fields(
        "transaction_flag", "critical", created_at
    )
    assert escalate_at == datetime(2026, 9, 17, 10, 45, 0, tzinfo=UTC)


def test_auto_escalate_at_for_screening_review_low_is_ninety_percent_of_forty_eight_hours(
    service,
):
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    escalate_at = service.calculate_auto_escalate_at_from_fields(
        "SCREENING_REVIEW", "LOW", created_at
    )
    # 90% of 48 hours = 43.2 hours = 43h12m
    assert escalate_at == datetime(2026, 9, 19, 5, 12, 0, tzinfo=UTC)


def test_auto_escalate_at_for_an_unconfigured_pair_raises(service):
    with pytest.raises(SlaTargetNotFoundError):
        service.calculate_auto_escalate_at_from_fields("MANUAL", "CRITICAL", datetime.now(UTC))


def test_auto_escalate_at_from_fields_matches_the_db_backed_formula_shape(service):
    """Same formula, pure vs. what `calculate_auto_escalate_at` computes from
    a loaded row — pinned here so a future refactor of one cannot silently
    diverge from the other."""
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    target = service.get_target("TRANSACTION_FLAG", "CRITICAL")
    expected = created_at + timedelta(hours=target.sla_hours * target.auto_escalate_at_pct / 100)
    assert (
        service.calculate_auto_escalate_at_from_fields("TRANSACTION_FLAG", "CRITICAL", created_at)
        == expected
    )
