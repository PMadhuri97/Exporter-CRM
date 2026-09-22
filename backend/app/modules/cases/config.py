"""Configuration for the Cases module.

Path constants and helpers for the GitOps-managed SLA configuration, mirroring
`app.modules.onboarding.config`'s document-requirements constants.
"""

from pathlib import Path

#: Root directory of the GitOps reference data for case management SLA config.
SLA_CONFIG_DIR = (
    # <repo>/backend/app/modules/cases/config.py -> parents[4] is <repo>
    Path(__file__).resolve().parents[4]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "compliance"
    / "cases"
)

DEFAULT_SLA_CONFIG_FILENAME = "sla-config.yaml"
DEFAULT_SLA_CONFIG_PATH = SLA_CONFIG_DIR / DEFAULT_SLA_CONFIG_FILENAME
