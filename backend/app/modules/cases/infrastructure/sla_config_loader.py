"""Load the SLA configuration from its GitOps-managed YAML.

Two things read this file, for different reasons and at different layers,
mirroring the split `onboarding`'s document-requirements config uses between
`document_requirements_loader.py` (I/O) and `document_requirements_service.py`
(pure domain logic):

- `load_sla_config_mapping` parses the YAML into an in-memory mapping of
  `(case_type, severity) -> SlaTarget`. `SlaCalculationService`
  (`application/sla_service.py`) is built from this mapping and never touches
  the filesystem or the database itself — `calculate_sla_deadline` is a pure
  function of `(case_type, severity, created_at)` plus this mapping.
- `load_sla_config_table` writes the same parsed data into
  `cases.case_sla_config`, following the exact reload pattern
  `compliance.sector_code_registry` uses (see
  `app/modules/compliance/infrastructure/sector_registry_seed_loader.py`): a
  Postgres advisory lock so concurrent replicas queue instead of racing each
  other's DELETE + re-insert, and the whole reload in one transaction so no
  reader ever observes an empty table between the DELETE and the re-insert.

**Redeploying the config never touches an existing case.** `sla_deadline` and
`sla_breached` are computed once, at case creation, and stored on
`compliance_case` — reloading `case_sla_config` (or the in-memory mapping this
module hands to `SlaCalculationService`) changes what a *future* case gets,
never a case already open. Nothing in this module reads or writes
`compliance_case`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.application.sla_service import SlaCalculationService, SlaTarget
from app.modules.cases.config import DEFAULT_SLA_CONFIG_PATH
from app.modules.cases.domain.entities.case_sla_config import CaseSlaConfig
from app.modules.cases.exceptions import SlaConfigurationError

logger = structlog.get_logger(__name__)

#: Postgres advisory lock key for the SLA config seed reload (BUILD.md #6).
#: Advisory lock keys are global to the database, so every key the platform
#: takes is declared next to the work it guards and must stay unique across
#: modules — checked against every other module's declared key, not just the
#: nearest-looking one: 4440001 is already claimed by both
#: ``LEDGER_INTEGRITY_CHECK_LOCK_KEY`` (app/modules/ledger/application/integrity.py)
#: and ``COMPLIANCE_RULE_SEED_LOCK_KEY``
#: (app/modules/compliance/infrastructure/compliance_rule_seed_loader.py) — see
#: tests/contract/test_advisory_lock_keys.py's KNOWN_COLLISIONS map. 4460001 is
#: the cases module's first unclaimed key (4450001 belongs to
#: settlement's leg-signal relay).
SLA_CONFIG_SEED_LOCK_KEY = 4460001

#: case_types the config must cover. Deliberately not the full
#: `CaseType` enum: `MANUAL` has no originating event to derive an urgency
#: from and is excluded from the SLA policy by design (see sla-config.yaml's
#: trailing comment) — checking completeness against the full enum would make
#: every deploy fail until a policy is invented for a case_type that may never
#: need one. `ONBOARDING_INTAKE` (ANER-4.3-S2) is excluded for the same class
#: of reason: it is a holding state for RXIL/counterparty document collection
#: with no originating event of its own, nobody internal is accountable for
#: how long that takes, and `compliance_case.sla_deadline` stays NULL for the
#: entire time a case is `ONBOARDING_INTAKE` (enforced by
#: `ck_compliance_case_intake_has_no_sla_deadline`). It only gets an SLA once
#: it transitions to `ONBOARDING_REVIEW` — which does appear below — via
#: `application/case_transition_service.py`'s `transition_case_to_review`.
EXPECTED_CASE_TYPES = frozenset({
    "SCREENING_REVIEW",
    "TRANSACTION_FLAG",
    "RECONCILIATION_BREAK",
    "RECONCILIATION_TIMEOUT",
    "ONBOARDING_REVIEW",
    "TRAVEL_RULE_REVIEW",
    "ON_CHAIN_ESCALATION",
    "WEBHOOK_DELIVERY_FAILURE",
})
EXPECTED_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})


def load_sla_config_mapping(
    config_path: Path | str | None = None,
) -> dict[tuple[str, str], SlaTarget]:
    """Read the SLA configuration YAML into a `(case_type, severity) -> SlaTarget` mapping.

    Keys are upper-cased on load regardless of the YAML's casing (the file is
    written lower_snake_case for readability), so a lookup by
    `compliance_case.case_type.value` / `.severity.value` always matches — the
    same normalisation `sector_registry_seed_loader._code()` applies for the
    same reason: Postgres string comparison is case-sensitive, and a rating
    seeded as `fatf` would satisfy every constraint and then never be matched.

    Raises:
        SlaConfigurationError: the file is missing, is not valid YAML, does not
            parse to the expected structure, or is missing a required
            case_type/severity combination (`EXPECTED_CASE_TYPES` x
            `EXPECTED_SEVERITIES`).
    """
    path = Path(config_path) if config_path else DEFAULT_SLA_CONFIG_PATH

    if not path.exists():
        raise SlaConfigurationError(f"SLA configuration file not found at {path}")

    try:
        with open(path, encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise SlaConfigurationError(f"Failed to parse SLA configuration at {path}: {exc}") from exc

    if not isinstance(parsed, dict) or not isinstance(parsed.get("sla_targets"), dict):
        raise SlaConfigurationError(
            f"Invalid configuration format in {path}: expected a mapping with a "
            f"top-level 'sla_targets' key"
        )

    mapping: dict[tuple[str, str], SlaTarget] = {}
    for case_type_raw, severities in parsed["sla_targets"].items():
        case_type = _upper(case_type_raw)
        if not isinstance(severities, dict):
            raise SlaConfigurationError(
                f"Invalid configuration format in {path}: 'sla_targets.{case_type_raw}' "
                f"must map severities to targets"
            )
        for severity_raw, target in severities.items():
            severity = _upper(severity_raw)
            try:
                sla_hours = int(target["sla_hours"])
                auto_escalate_at_pct = int(target["auto_escalate_at_pct"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SlaConfigurationError(
                    f"Invalid SLA target for case_type='{case_type}', "
                    f"severity='{severity}' in {path}: {exc}"
                ) from exc
            mapping[(case_type, severity)] = SlaTarget(
                case_type=case_type,
                severity=severity,
                sla_hours=sla_hours,
                auto_escalate_at_pct=auto_escalate_at_pct,
            )

    _assert_complete(mapping, path)

    logger.info("sla_config_loaded", source=str(path), pair_count=len(mapping))
    return mapping


def _assert_complete(mapping: dict[tuple[str, str], Any], path: Path) -> None:
    expected = {(ct, sev) for ct in EXPECTED_CASE_TYPES for sev in EXPECTED_SEVERITIES}
    missing = expected - set(mapping.keys())
    if missing:
        raise SlaConfigurationError(
            f"SLA configuration at {path} is missing targets for: "
            f"{sorted(missing)}"
        )


def _upper(val: Any) -> str:
    if not isinstance(val, str) or not val.strip():
        raise SlaConfigurationError(f"Expected a non-empty string key, got {val!r}")
    return val.strip().upper()


async def load_sla_config_table(
    session: AsyncSession, config_path: Path | str | None = None
) -> dict[tuple[str, str], SlaTarget]:
    """Replace `cases.case_sla_config` with the contents of the GitOps YAML.

    Runs on every boot, in every replica — see the module docstring for why the
    advisory lock and single-transaction reload make that safe under
    concurrent replicas. Returns the parsed mapping so a caller that also needs
    to (re)build an in-memory `SlaCalculationService` does not have to parse
    the file a second time.
    """
    mapping = load_sla_config_mapping(config_path)

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": SLA_CONFIG_SEED_LOCK_KEY}
    )

    await session.execute(delete(CaseSlaConfig))

    for target in mapping.values():
        session.add(
            CaseSlaConfig(
                case_type=target.case_type,
                severity=target.severity,
                sla_hours=target.sla_hours,
                auto_escalate_at_pct=target.auto_escalate_at_pct,
            )
        )

    await session.commit()
    logger.info("sla_config_seed_load_completed", pair_count=len(mapping))
    return mapping


def build_sla_calculation_service(config_path: Path | str | None = None) -> SlaCalculationService:
    """Build an `SlaCalculationService` from the GitOps-managed YAML.

    Composition-root entry point, mirroring
    `onboarding.infrastructure.document_requirements_loader.
    load_document_requirements_service`: reads the file here, hands the parsed
    mapping to the pure application-layer service, which does not touch the
    filesystem or the database.
    """
    return SlaCalculationService(load_sla_config_mapping(config_path))
