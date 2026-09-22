"""Load and locate the GitOps-managed document requirements configuration.

File I/O for the onboarding document-requirements policy lives here so that
``domain/policies/document_requirements_service.py`` stays pure: it receives an
already-parsed mapping and never reads the filesystem. This mirrors the pattern
every other GitOps-managed vocabulary on the platform uses (see
``rails/infrastructure/rail_code_loader.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]

from app.modules.onboarding.config import DEFAULT_DOCUMENT_REQUIREMENTS_PATH
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.exceptions import DocumentRequirementsConfigurationError

logger = structlog.get_logger(__name__)


def load_document_requirements_config(
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Read the document requirements YAML into a mapping.

    Args:
        config_path: Override for the configuration file location. Defaults to the
            GitOps-managed path in ``deployments/gitops/reference-data``.

    Raises:
        DocumentRequirementsConfigurationError: the file is missing, is not valid
            YAML, or does not parse to a mapping.
    """
    path = Path(config_path) if config_path else DEFAULT_DOCUMENT_REQUIREMENTS_PATH

    if not path.exists():
        raise DocumentRequirementsConfigurationError(
            f"Document requirements configuration file not found at {path}"
        )

    try:
        with open(path, encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise DocumentRequirementsConfigurationError(
            f"Failed to parse document requirements configuration at {path}: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise DocumentRequirementsConfigurationError(
            f"Invalid configuration format in {path}: expected a mapping"
        )

    logger.info("document_requirements_config_loaded", source=str(path))
    return parsed


def load_document_requirements_service(
    config_path: Path | str | None = None,
) -> DocumentRequirementsService:
    """Build a :class:`DocumentRequirementsService` from the GitOps-managed YAML.

    Composition-root entry point: reads the file here, hands the parsed mapping to
    the pure domain service, which validates its structure.
    """
    return DocumentRequirementsService(load_document_requirements_config(config_path))
