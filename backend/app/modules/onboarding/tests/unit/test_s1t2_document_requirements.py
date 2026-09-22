"""Unit tests for S1T2: Document Requirements Configuration and Engine."""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.modules.onboarding import DocumentRequirementsService as FacadeDocumentRequirementsService
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.exceptions import DocumentRequirementsConfigurationError
from app.modules.onboarding.infrastructure.document_requirements_loader import (
    load_document_requirements_config,
    load_document_requirements_service,
)


def _valid_config() -> dict:
    """A minimal, structurally valid configuration for negative-case mutation."""
    return {
        "version": "1.0",
        "validity_periods": {
            "certificate_of_incorporation": {"max_age_days": None},
            "latest_audited_accounts": {"max_age_days": 365},
        },
        "profiles": [
            {
                "profile_id": "US_CORP",
                "entity_type": "CORPORATION",
                "registration_country": "US",
                "sector_code": "DNFBP",
                "corridor_intent": "US-IN",
                "required_documents": ["certificate_of_incorporation"],
            }
        ],
        "conditional_rules": [
            {
                "rule_id": "HIGH_VOLUME",
                "field": "declared_monthly_volume_usd",
                "operator": "gt",
                "value": 500000,
                "additional_documents": ["bank_statement"],
            }
        ],
    }


def test_default_config_file_exists_and_parseable():
    """Verify that the GitOps document requirements configuration file exists and is parseable."""
    service = load_document_requirements_service()
    assert service.config is not None
    assert service.config.get("version") == "1.0"
    assert len(service.config.get("profiles", [])) >= 2


def test_us_corporation_dnfbp_profile_requirements():
    """Verify the US corporation DNFBP profile returns the correct required document list."""
    service = load_document_requirements_service()
    docs = service.get_required_documents(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="DNFBP",
        corridor_intent="US-IN",
        declared_monthly_volume_usd=100000,
    )

    expected_docs = {
        "certificate_of_incorporation",
        "memorandum_of_association",
        "proof_of_registered_address",
        "latest_audited_accounts",
        "ubo_declaration",
        "source_of_funds_declaration",
    }
    assert set(docs) == expected_docs


def test_indian_corporation_dnfbp_profile_requirements():
    """Verify the Indian corporation DNFBP profile returns the correct required document list."""
    service = load_document_requirements_service()
    docs = service.get_required_documents(
        entity_type="CORPORATION",
        registration_country="IN",
        sector_code="DNFBP",
        corridor_intent="US-IN",
        declared_monthly_volume_usd=250000,
    )

    expected_docs = {
        "certificate_of_incorporation",
        "memorandum_of_association",
        "proof_of_registered_address",
        "latest_audited_accounts",
        "ubo_declaration",
        "source_of_funds_declaration",
    }
    assert set(docs) == expected_docs


def test_high_volume_triggers_bank_statement_conditional_requirement():
    """Verify declared monthly volume > $500,000 triggers the bank statement requirement."""
    service = load_document_requirements_service()

    # Below threshold -> no bank statement
    docs_low = service.get_required_documents(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="DNFBP",
        corridor_intent="US-IN",
        declared_monthly_volume_usd=500000,
    )
    assert "bank_statement" not in docs_low

    # Above threshold -> triggers bank statement requirement
    docs_high = service.get_required_documents(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="DNFBP",
        corridor_intent="US-IN",
        declared_monthly_volume_usd=500001,
    )
    assert "bank_statement" in docs_high


def test_audited_accounts_validity_period_expiration():
    """Verify an audited accounts document older than 12 months (365 days) is flagged as invalid."""
    service = load_document_requirements_service()
    today = date.today()

    # Valid: 6 months old (180 days)
    valid_issue_date = today - timedelta(days=180)
    assert service.validate_document_age("latest_audited_accounts", issue_date=valid_issue_date, reference_date=today) is True

    # Expired: 13 months old (395 days)
    expired_issue_date = today - timedelta(days=395)
    assert service.validate_document_age("latest_audited_accounts", issue_date=expired_issue_date, reference_date=today) is False


def test_other_document_validity_periods():
    """Verify validity rules for certificate of incorporation and proof of address."""
    service = load_document_requirements_service()
    today = date.today()

    # Certificate of incorporation: unlimited age limit
    old_cert_date = today - timedelta(days=3650)  # ~10 years old
    assert service.validate_document_age("certificate_of_incorporation", issue_date=old_cert_date, reference_date=today) is True

    # Proof of registered address: max 90 days
    recent_address = today - timedelta(days=60)
    assert service.validate_document_age("proof_of_registered_address", issue_date=recent_address, reference_date=today) is True

    old_address = today - timedelta(days=100)
    assert service.validate_document_age("proof_of_registered_address", issue_date=old_address, reference_date=today) is False


def test_validity_periods_use_single_canonical_field():
    """The GitOps config must express validity with max_age_days only (no redundant max_age_months)."""
    config = load_document_requirements_config()
    for doc_type, rule in config.get("validity_periods", {}).items():
        assert "max_age_days" in rule, f"{doc_type} missing max_age_days"
        assert "max_age_months" not in rule, f"{doc_type} still declares redundant max_age_months"


def test_adding_new_profile_via_config_without_code_changes():
    """Verify adding a new profile to configuration works dynamically without code modifications."""
    dynamic_config = {
        "version": "1.0",
        "validity_periods": {},
        "profiles": [
            {
                "profile_id": "SG_FUND_TEST",
                "entity_type": "FUND",
                "registration_country": "SG",
                "sector_code": "ASSET_MANAGEMENT",
                "corridor_intent": "SG-US",
                "required_documents": [
                    "fund_prospectus",
                    "license_certificate",
                    "ubo_declaration",
                ],
            }
        ],
        "conditional_rules": [],
    }

    service = DocumentRequirementsService(dynamic_config)
    docs = service.get_required_documents(
        entity_type="FUND",
        registration_country="SG",
        sector_code="ASSET_MANAGEMENT",
        corridor_intent="SG-US",
    )

    assert docs == ["fund_prospectus", "license_certificate", "ubo_declaration"]


def test_missing_config_file_raises_structured_exception(tmp_path):
    """Verify missing config file raises DocumentRequirementsConfigurationError."""
    non_existent = tmp_path / "does_not_exist.yaml"
    with pytest.raises(DocumentRequirementsConfigurationError):
        load_document_requirements_config(config_path=non_existent)


def test_non_mapping_config_file_raises_structured_exception(tmp_path):
    """Verify a config file that does not parse to a mapping raises a structured error."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(DocumentRequirementsConfigurationError):
        load_document_requirements_config(config_path=bad)


def test_service_exported_from_module_facade():
    """DocumentRequirementsService must be importable from app.modules.onboarding."""
    assert FacadeDocumentRequirementsService is DocumentRequirementsService


# ── Malformed configuration is rejected explicitly (no silent wildcard) ───────


def test_profile_typo_in_match_field_raises_instead_of_matching_everything():
    """A typo'd profile field (e.g. 'eneity_type') must raise, not silently wildcard-match."""
    config = _valid_config()
    profile = config["profiles"][0]
    del profile["entity_type"]
    profile["eneity_type"] = "CORPORATION"
    with pytest.raises(DocumentRequirementsConfigurationError, match="unknown key"):
        DocumentRequirementsService(config)


def test_profile_missing_required_documents_raises():
    config = _valid_config()
    del config["profiles"][0]["required_documents"]
    with pytest.raises(DocumentRequirementsConfigurationError, match="missing required key"):
        DocumentRequirementsService(config)


def test_profile_missing_profile_id_raises():
    config = _valid_config()
    del config["profiles"][0]["profile_id"]
    with pytest.raises(DocumentRequirementsConfigurationError, match="missing required key"):
        DocumentRequirementsService(config)


def test_profile_empty_required_documents_raises():
    config = _valid_config()
    config["profiles"][0]["required_documents"] = []
    with pytest.raises(DocumentRequirementsConfigurationError, match="non-empty list"):
        DocumentRequirementsService(config)


def test_profile_match_field_wrong_type_raises():
    config = _valid_config()
    config["profiles"][0]["entity_type"] = 123
    with pytest.raises(DocumentRequirementsConfigurationError, match="non-empty string"):
        DocumentRequirementsService(config)


def test_rule_unknown_key_raises():
    config = _valid_config()
    config["conditional_rules"][0]["fild"] = "sector_code"
    with pytest.raises(DocumentRequirementsConfigurationError, match="unknown key"):
        DocumentRequirementsService(config)


def test_rule_missing_required_key_raises():
    config = _valid_config()
    del config["conditional_rules"][0]["operator"]
    with pytest.raises(DocumentRequirementsConfigurationError, match="missing required key"):
        DocumentRequirementsService(config)


def test_rule_unknown_field_raises():
    config = _valid_config()
    config["conditional_rules"][0]["field"] = "not_a_real_context_field"
    with pytest.raises(DocumentRequirementsConfigurationError, match="'field' must be one of"):
        DocumentRequirementsService(config)


def test_rule_unknown_operator_raises():
    config = _valid_config()
    config["conditional_rules"][0]["operator"] = "approximately"
    with pytest.raises(DocumentRequirementsConfigurationError, match="'operator' must be one of"):
        DocumentRequirementsService(config)


def test_profiles_not_a_list_raises():
    config = _valid_config()
    config["profiles"] = {"profile_id": "X"}
    with pytest.raises(DocumentRequirementsConfigurationError, match="'profiles' must be a list"):
        DocumentRequirementsService(config)


def test_valid_matching_behavior_is_unchanged_by_validation():
    """Validation must not weaken valid matching: a wildcard (field omitted) still matches."""
    config = _valid_config()
    # Deliberately omit sector_code / corridor_intent -> intentional wildcards.
    config["profiles"] = [
        {
            "profile_id": "ANY_CORP",
            "entity_type": "CORPORATION",
            "required_documents": ["certificate_of_incorporation"],
        }
    ]
    config["conditional_rules"] = []
    service = DocumentRequirementsService(deepcopy(config))
    docs = service.get_required_documents(
        entity_type="CORPORATION",
        registration_country="anywhere",
        sector_code="anything",
        corridor_intent="any-any",
    )
    assert docs == ["certificate_of_incorporation"]
