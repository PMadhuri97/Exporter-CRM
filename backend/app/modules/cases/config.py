"""Configuration for the Cases module.

Path constants and helpers for the GitOps-managed SLA configuration, mirroring
`app.modules.onboarding.config`'s document-requirements constants.
"""

import os
from pathlib import Path

#: The two-person rule on case resolution: when on, `CaseLifecycleService.
#: decide_resolution` refuses a checker who is also the proposer
#: (`SelfApprovalNotAllowedError`). Off by decision — one COMPLIANCE or ADMIN
#: reviewer records a rationale and decides. Kept as a flag, not removed, so
#: turning it back on is configuration: `CASES_REQUIRE_TWO_PERSON_RESOLUTION=true`.
REQUIRE_TWO_PERSON_RESOLUTION: bool = (
    os.getenv("CASES_REQUIRE_TWO_PERSON_RESOLUTION", "false").strip().lower() == "true"
)

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
