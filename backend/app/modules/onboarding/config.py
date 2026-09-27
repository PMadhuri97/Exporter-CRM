"""Configuration for the Onboarding module.

This module provides path constants and helpers for GitOps-managed onboarding configurations.
"""

from pathlib import Path

#: Root directory of the GitOps reference data for compliance documents
DOCUMENT_REQUIREMENTS_CONFIG_DIR = (
    # <repo>/backend/app/modules/onboarding/config.py -> parents[4] is <repo>
    Path(__file__).resolve().parents[4]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "compliance"
    / "documents"
)

DEFAULT_DOCUMENT_REQUIREMENTS_FILENAME = "document-requirements.yaml"
DEFAULT_DOCUMENT_REQUIREMENTS_PATH = DOCUMENT_REQUIREMENTS_CONFIG_DIR / DEFAULT_DOCUMENT_REQUIREMENTS_FILENAME

#: Root directory of the GitOps reference data for the S5T2 risk rating calculation
RISK_RATING_CONFIG_DIR = (
    # <repo>/backend/app/modules/onboarding/config.py -> parents[4] is <repo>
    Path(__file__).resolve().parents[4]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "compliance"
    / "risk-rating"
)

DEFAULT_RISK_RATING_CONFIG_FILENAME = "risk-rating-config.yaml"
DEFAULT_RISK_RATING_CONFIG_PATH = RISK_RATING_CONFIG_DIR / DEFAULT_RISK_RATING_CONFIG_FILENAME


#: Root directory of the GitOps reference data for CRM document types
#: (architecture §3.4: categories are fixed, types are settings) — owner:
#: Developer 3B, L3-09.
CRM_DOCUMENT_CONFIG_DIR = (
    # <repo>/backend/app/modules/onboarding/config.py -> parents[4] is <repo>
    Path(__file__).resolve().parents[4]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "crm"
    / "documents"
)

DEFAULT_DOCUMENT_TYPES_FILENAME = "document-types.yaml"
DEFAULT_DOCUMENT_TYPES_PATH = CRM_DOCUMENT_CONFIG_DIR / DEFAULT_DOCUMENT_TYPES_FILENAME
