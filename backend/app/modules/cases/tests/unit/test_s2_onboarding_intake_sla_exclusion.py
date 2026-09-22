"""ANER-4.3-S2: ONBOARDING_INTAKE is excluded from the SLA policy.

Mirrors the same class of exclusion `MANUAL` already has (see
`infrastructure/sla_config_loader.py`'s `EXPECTED_CASE_TYPES` docstring and
`sla-config.yaml`'s trailing comment): a holding state with no originating
event to derive an urgency from is deliberately left out of the completeness
check, not silently missing from it. Split into its own test module (rather
than folded into test_s1t2_sla_calculation.py) since it is specifically about
proving an *absence*, which is easy to lose track of among tests proving
presence.
"""
from __future__ import annotations

from app.modules.cases.domain.entities.enums import CaseType
from app.modules.cases.infrastructure.sla_config_loader import (
    EXPECTED_CASE_TYPES,
    load_sla_config_mapping,
)


def test_onboarding_intake_is_not_in_expected_case_types():
    """AC: ONBOARDING_INTAKE is excluded from the SLA policy, same as MANUAL."""
    assert "ONBOARDING_INTAKE" not in EXPECTED_CASE_TYPES
    assert "MANUAL" not in EXPECTED_CASE_TYPES


def test_onboarding_intake_is_a_real_case_type_despite_the_exclusion():
    """The exclusion is deliberate, not an oversight: ONBOARDING_INTAKE is a
    real, valid CaseType member, just not one the SLA config has to cover."""
    assert CaseType.ONBOARDING_INTAKE.value == "ONBOARDING_INTAKE"
    assert CaseType.ONBOARDING_INTAKE not in {
        CaseType(ct) for ct in EXPECTED_CASE_TYPES
    }


def test_config_file_has_no_entry_for_onboarding_intake():
    """AC: sla-config.yaml must not have an entry for onboarding_intake — only
    for onboarding_review (already covered by
    test_s1t2_sla_calculation.EXPECTED_SLA_HOURS)."""
    mapping = load_sla_config_mapping()
    case_types_present = {case_type for case_type, _severity in mapping}
    assert "ONBOARDING_INTAKE" not in case_types_present
    assert "ONBOARDING_REVIEW" in case_types_present


def test_config_completeness_check_does_not_require_onboarding_intake():
    """A regression that added ONBOARDING_INTAKE to EXPECTED_CASE_TYPES
    without also adding it to sla-config.yaml would fail
    test_config_file_has_all_case_type_severity_combinations in
    test_s1t2_sla_calculation.py; this test instead pins the exclusion
    itself, independent of whatever the YAML currently contains."""
    mapping = load_sla_config_mapping()
    assert not any(case_type == "ONBOARDING_INTAKE" for case_type, _sev in mapping)
