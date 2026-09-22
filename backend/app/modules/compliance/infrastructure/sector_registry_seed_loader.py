"""Load the sector registry from its GitOps-managed YAML."""

from datetime import date
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.sector_registry import (
    JurisdictionType,
    RiskTier,
    SectorCodeExternalMapping,
    SectorCodeRegistry,
    SectorRiskClassification,
)

logger = structlog.get_logger(__name__)

#: Postgres advisory lock key for the sector-registry seed reload (BUILD.md #6).
#: Advisory lock keys are global to the database, so every key the platform takes
#: is declared next to the work it guards and must stay unique across modules.
#: 4420001 belongs to the purpose-code reload.
SECTOR_REGISTRY_SEED_LOCK_KEY = 4430001

#: GitOps-managed seed directory. Both the startup loader and the tests that have
#: to restore the shared reference data resolve the path through here rather than
#: rebuilding it from ``__file__`` offsets in two places.
SEED_DATA_DIR = (
    # <repo>/backend/app/modules/compliance/infrastructure/<this file>
    Path(__file__).resolve().parents[5]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "compliance"
    / "sectors"
)


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val)
    raise ValueError(f"Cannot parse date: {val}")


def _text(val: Any) -> Any:
    """Trim incidental whitespace so a stray space cannot break a code match."""
    return val.strip() if isinstance(val, str) else val


def _code(val: Any) -> Any:
    """Normalise an identifier that is later matched exactly.

    Sector codes, jurisdiction values and standard names are compared with ``=``,
    and Postgres string comparison is case-sensitive. A row seeded as ``fatf``
    would load cleanly, satisfy every constraint, and then never be matched by
    the framework tier — silently dropping every unmapped jurisdiction to the
    standard rating. Casing is settled once, here, rather than at each comparison.
    """
    return val.strip().upper() if isinstance(val, str) else val


def _external_value(val: Any) -> Any:
    """Preserve an external code or version verbatim, but force it to text.

    YAML reads a bare ``4649`` as an integer and the column is VARCHAR, so an
    unquoted ISIC code would otherwise fail deep in the driver. Casing is *not*
    normalised: ``ISIC Rev.4`` is a published revision label, and upper-casing it
    would change what the platform reports to a regulator.
    """
    return None if val is None else str(val).strip()


async def load_sector_registry(session: AsyncSession, base_dir: str | Path) -> None:
    """Replace the sector registry with the contents of ``base_dir``.

    Runs on every boot, in every replica. The reload is a DELETE of all three
    tables followed by a re-insert, so two replicas doing it at once would race:
    each deletes rows the other cannot yet see, then both insert, and the second
    commit dies on ``uq_sector_code_registry_sector_code``. BUILD.md #6 puts
    one-time boot work behind a Postgres advisory lock — a transaction-scoped
    lock is taken here so replicas queue instead of colliding, and it is released
    by the commit or rollback below without any explicit unlock.

    Everything runs in one transaction, so a screening request never observes the
    window between the DELETE and the re-insert and reads an empty registry.
    """
    base_path = Path(base_dir)

    logger.info("sector_registry_seed_load_started", seed_dir=str(base_path))

    with open(base_path / "sector-codes.yaml") as f:
        sector_data = yaml.safe_load(f) or []

    with open(base_path / "external-mappings.yaml") as f:
        mapping_data = yaml.safe_load(f) or []

    with open(base_path / "risk-classifications.yaml") as f:
        classification_data = yaml.safe_load(f) or []

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": SECTOR_REGISTRY_SEED_LOCK_KEY}
    )

    # Both children go first: their FKs to sector_code_registry are ON DELETE
    # RESTRICT, so a parent row cannot be removed while either points at it.
    await session.execute(delete(SectorRiskClassification))
    await session.execute(delete(SectorCodeExternalMapping))
    await session.execute(delete(SectorCodeRegistry))

    for item in sector_data:
        session.add(
            SectorCodeRegistry(
                sector_code=_code(item["sector_code"]),
                description=item.get("description"),
                effective_from=_parse_date(item.get("effective_from")),
                effective_to=_parse_date(item.get("effective_to")),
            )
        )

    # Both children reference sector_code, which is not the parent's primary
    # key. SQLAlchemy's unit of work orders inserts by mapper relationships, and
    # these tables declare none — only column-level foreign keys — so nothing
    # guarantees the parents land first. Flushing here makes the ordering
    # explicit instead of relying on it.
    await session.flush()

    for item in mapping_data:
        session.add(
            SectorCodeExternalMapping(
                sector_code=_code(item["sector_code"]),
                external_standard=_code(item["external_standard"]),
                external_standard_version=_external_value(item["external_standard_version"]),
                external_code=_external_value(item["external_code"]),
                effective_from=_parse_date(item.get("effective_from")),
                effective_to=_parse_date(item.get("effective_to")),
            )
        )

    for item in classification_data:
        session.add(
            SectorRiskClassification(
                sector_code=_code(item["sector_code"]),
                # Both converted here rather than left to the column so a mistyped
                # value names itself at boot instead of surfacing as a driver error.
                jurisdiction_type=JurisdictionType(item.get("jurisdiction_type")),
                jurisdiction_value=_code(item["jurisdiction_value"]),
                risk_tier=RiskTier(item.get("risk_tier")),
                classification_label=_text(item.get("classification_label")),
                notes=item.get("notes"),
                effective_from=_parse_date(item.get("effective_from")),
                effective_to=_parse_date(item.get("effective_to")),
            )
        )

    await session.commit()
    logger.info(
        "sector_registry_seed_load_completed",
        sector_count=len(sector_data),
        external_mapping_count=len(mapping_data),
        classification_count=len(classification_data),
    )
