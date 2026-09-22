"""Load and locate the GitOps-managed risk rating configuration (ANER-4.1-S5T2).

File I/O for the risk-rating policy lives here so that
``domain/policies/risk_rating_service.py`` stays pure: it receives an
already-parsed mapping and never reads the filesystem. This mirrors
``document_requirements_loader.py`` exactly — same shape, same module split
between infrastructure (I/O) and domain (pure policy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]

from app.modules.onboarding.config import DEFAULT_RISK_RATING_CONFIG_PATH
from app.modules.onboarding.domain.policies.risk_rating_service import RiskRatingService
from app.modules.onboarding.exceptions import RiskRatingConfigurationError

logger = structlog.get_logger(__name__)


def load_risk_rating_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Read the risk rating YAML into a mapping.

    Args:
        config_path: Override for the configuration file location. Defaults to
            the GitOps-managed path in ``deployments/gitops/reference-data``.

    Raises:
        RiskRatingConfigurationError: the file is missing, is not valid YAML,
            or does not parse to a mapping.
    """
    path = Path(config_path) if config_path else DEFAULT_RISK_RATING_CONFIG_PATH

    if not path.exists():
        raise RiskRatingConfigurationError(f"Risk rating configuration file not found at {path}")

    try:
        with open(path, encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise RiskRatingConfigurationError(
            f"Failed to parse risk rating configuration at {path}: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RiskRatingConfigurationError(f"Invalid configuration format in {path}: expected a mapping")

    logger.info("risk_rating_config_loaded", source=str(path))
    return parsed


def load_risk_rating_service(config_path: Path | str | None = None) -> RiskRatingService:
    """Build a :class:`RiskRatingService` from the GitOps-managed YAML.

    Composition-root entry point: reads the file here, hands the parsed
    mapping to the pure domain service, which validates its structure.
    """
    return RiskRatingService(load_risk_rating_config(config_path))


__all__ = ["load_risk_rating_config", "load_risk_rating_service"]
