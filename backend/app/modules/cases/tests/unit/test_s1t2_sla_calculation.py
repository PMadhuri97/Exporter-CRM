"""Unit tests for ANER-4.3-S1T2: SLA configuration and deadline calculation.

`SlaCalculationService.calculate_sla_deadline` is pure — no filesystem, no
database — and is tested here against a hand-built config for isolation, and
against the real GitOps YAML for the acceptance-criteria case. `is_sla_breached`
and `calculate_auto_escalate_at` need a `compliance_case` row to read and are
covered in tests/integration/test_s1t2_sla_seed_loading.py instead, following
the same unit/integration split
onboarding/tests/unit/test_s1t2_document_requirements.py and
onboarding/tests/integration/test_s1t1_orchestration_schema.py use.
"""
from datetime import UTC, datetime

import pytest

from app.modules.cases.application.sla_service import SlaCalculationService, SlaTarget
from app.modules.cases.exceptions import SlaConfigurationError, SlaTargetNotFoundError
from app.modules.cases.infrastructure.sla_config_loader import (
    EXPECTED_CASE_TYPES,
    EXPECTED_SEVERITIES,
    load_sla_config_mapping,
)

# The exact Walk-phase SLA targets from the ticket, reproduced here so a
# regression in the YAML (a wrong number, a swapped pair) fails a test that
# names the expected value directly rather than only failing the loader's
# completeness check.
EXPECTED_SLA_HOURS = {
    ("SCREENING_REVIEW", "CRITICAL"): 2,
    ("SCREENING_REVIEW", "HIGH"): 4,
    ("SCREENING_REVIEW", "MEDIUM"): 24,
    ("SCREENING_REVIEW", "LOW"): 48,
    ("TRANSACTION_FLAG", "CRITICAL"): 1,
    ("TRANSACTION_FLAG", "HIGH"): 2,
    ("TRANSACTION_FLAG", "MEDIUM"): 8,
    ("TRANSACTION_FLAG", "LOW"): 24,
    ("RECONCILIATION_BREAK", "CRITICAL"): 4,
    ("RECONCILIATION_BREAK", "HIGH"): 8,
    ("RECONCILIATION_BREAK", "MEDIUM"): 48,
    ("RECONCILIATION_BREAK", "LOW"): 72,
    ("RECONCILIATION_TIMEOUT", "CRITICAL"): 8,
    ("RECONCILIATION_TIMEOUT", "HIGH"): 24,
    ("RECONCILIATION_TIMEOUT", "MEDIUM"): 48,
    ("RECONCILIATION_TIMEOUT", "LOW"): 72,
    ("ONBOARDING_REVIEW", "CRITICAL"): 4,
    ("ONBOARDING_REVIEW", "HIGH"): 8,
    ("ONBOARDING_REVIEW", "MEDIUM"): 48,
    ("ONBOARDING_REVIEW", "LOW"): 96,
    ("TRAVEL_RULE_REVIEW", "CRITICAL"): 2,
    ("TRAVEL_RULE_REVIEW", "HIGH"): 4,
    ("TRAVEL_RULE_REVIEW", "MEDIUM"): 24,
    ("TRAVEL_RULE_REVIEW", "LOW"): 48,
    ("ON_CHAIN_ESCALATION", "CRITICAL"): 1,
    ("ON_CHAIN_ESCALATION", "HIGH"): 4,
    ("ON_CHAIN_ESCALATION", "MEDIUM"): 24,
    ("ON_CHAIN_ESCALATION", "LOW"): 48,
    ("WEBHOOK_DELIVERY_FAILURE", "CRITICAL"): 48,
    ("WEBHOOK_DELIVERY_FAILURE", "HIGH"): 72,
    ("WEBHOOK_DELIVERY_FAILURE", "MEDIUM"): 96,
    ("WEBHOOK_DELIVERY_FAILURE", "LOW"): 120,
}
EXPECTED_AUTO_ESCALATE_PCT = {"CRITICAL": 75, "HIGH": 75, "MEDIUM": 90, "LOW": 90}


# ── The real GitOps config file ─────────────────────────────────────────────────


def test_config_file_has_all_case_type_severity_combinations():
    """AC: config file has all case_type/severity combinations."""
    mapping = load_sla_config_mapping()
    expected_keys = {(ct, sev) for ct in EXPECTED_CASE_TYPES for sev in EXPECTED_SEVERITIES}
    assert set(mapping.keys()) == expected_keys


def test_config_file_matches_the_walk_phase_sla_targets():
    mapping = load_sla_config_mapping()
    for key, expected_hours in EXPECTED_SLA_HOURS.items():
        assert mapping[key].sla_hours == expected_hours, f"sla_hours mismatch for {key}"
        assert mapping[key].auto_escalate_at_pct == EXPECTED_AUTO_ESCALATE_PCT[key[1]], (
            f"auto_escalate_at_pct mismatch for {key}"
        )


def test_default_config_file_exists_and_parses():
    mapping = load_sla_config_mapping()
    assert len(mapping) == len(EXPECTED_CASE_TYPES) * len(EXPECTED_SEVERITIES)


# ── load_sla_config_mapping: malformed input ────────────────────────────────────


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(SlaConfigurationError):
        load_sla_config_mapping(tmp_path / "does-not-exist.yaml")


def test_incomplete_config_raises(tmp_path):
    incomplete = tmp_path / "sla-config.yaml"
    incomplete.write_text(
        "sla_targets:\n"
        "  transaction_flag:\n"
        "    critical: {sla_hours: 1, auto_escalate_at_pct: 75}\n"
    )
    with pytest.raises(SlaConfigurationError):
        load_sla_config_mapping(incomplete)


def test_config_missing_the_sla_targets_key_raises(tmp_path):
    malformed = tmp_path / "sla-config.yaml"
    malformed.write_text("version: '1.0'\n")
    with pytest.raises(SlaConfigurationError):
        load_sla_config_mapping(malformed)


def test_config_keys_are_upper_cased_regardless_of_yaml_casing(tmp_path):
    """Written lower_snake_case in the YAML; matched against upper-cased
    compliance_case.case_type/.severity values at lookup time."""
    minimal = tmp_path / "sla-config.yaml"
    lines = ["sla_targets:"]
    for case_type in sorted(EXPECTED_CASE_TYPES):
        lines.append(f"  {case_type.lower()}:")
        for severity in sorted(EXPECTED_SEVERITIES):
            lines.append(f"    {severity.lower()}: {{sla_hours: 1, auto_escalate_at_pct: 75}}")
    minimal.write_text("\n".join(lines) + "\n")

    mapping = load_sla_config_mapping(minimal)
    assert ("TRANSACTION_FLAG", "CRITICAL") in mapping
    assert ("transaction_flag", "critical") not in mapping


# ── SlaCalculationService.calculate_sla_deadline: pure ──────────────────────────


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


def test_calculate_sla_deadline_for_a_critical_transaction_flag_is_one_hour_later(service):
    """AC: calculate_sla_deadline for a critical transaction_flag case returns
    created_at + 1 hour."""
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    deadline = service.calculate_sla_deadline("TRANSACTION_FLAG", "CRITICAL", created_at)
    assert deadline == datetime(2026, 9, 17, 11, 0, 0, tzinfo=UTC)


def test_calculate_sla_deadline_is_case_insensitive_on_lookup(service):
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    deadline = service.calculate_sla_deadline("transaction_flag", "critical", created_at)
    assert deadline == datetime(2026, 9, 17, 11, 0, 0, tzinfo=UTC)


def test_calculate_sla_deadline_for_screening_review_low_is_forty_eight_hours_later(service):
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    deadline = service.calculate_sla_deadline("SCREENING_REVIEW", "LOW", created_at)
    assert deadline == datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)


def test_calculate_sla_deadline_for_an_unconfigured_pair_raises(service):
    with pytest.raises(SlaTargetNotFoundError):
        service.calculate_sla_deadline("MANUAL", "CRITICAL", datetime.now(UTC))


def test_get_target_returns_the_configured_target(service):
    target = service.get_target("TRANSACTION_FLAG", "CRITICAL")
    assert target.sla_hours == 1
    assert target.auto_escalate_at_pct == 75


# ── Built against the real GitOps config, end to end (still pure) ──────────────


def test_calculate_sla_deadline_against_the_real_config_for_critical_transaction_flag():
    real_service = SlaCalculationService(load_sla_config_mapping())
    created_at = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    deadline = real_service.calculate_sla_deadline("TRANSACTION_FLAG", "CRITICAL", created_at)
    assert deadline == datetime(2026, 9, 17, 11, 0, 0, tzinfo=UTC)
