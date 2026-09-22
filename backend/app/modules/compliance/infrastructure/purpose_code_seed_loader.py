import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.registry import (
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)

logger = logging.getLogger(__name__)

#: Postgres advisory lock key for the purpose-code seed reload (BUILD.md #6).
#: Advisory lock keys are global to the database, so every key the platform takes
#: is declared next to the work it guards and must stay unique across modules.
PURPOSE_CODE_SEED_LOCK_KEY = 4420001

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
    / "purpose-codes"
)


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val)
    raise ValueError(f"Cannot parse date: {val}")


def _strip_in_place(item: dict[str, Any], *fields: str) -> None:
    """Trim surrounding whitespace from the named string fields, if present."""
    for field in fields:
        value = item.get(field)
        if isinstance(value, str):
            item[field] = value.strip()


async def load_purpose_codes(session: AsyncSession, base_dir: str | Path):
    """Replace the purpose-code registry with the contents of ``base_dir``.

    Runs on every boot, in every replica. The reload is a DELETE of both tables
    followed by a re-insert, so two replicas doing it at once would race: each
    deletes rows the other cannot yet see, then both insert, and the second
    commit dies on ``ex_purpose_code_canonical_validity``. BUILD.md #6 puts
    one-time boot work behind a Postgres advisory lock — a transaction-scoped
    lock is taken here so replicas queue instead of colliding, and it is released
    by the commit or rollback below without any explicit unlock.

    Everything runs in one transaction, so readers never observe the window
    between the DELETE and the re-insert.
    """
    base_path = Path(base_dir)
    canonical_file = base_path / "canonical.yaml"
    mappings_file = base_path / "corridor-mappings.yaml"

    logger.info("Loading purpose codes from %s", base_path)

    with open(canonical_file) as f:
        canonical_data = yaml.safe_load(f) or []

    with open(mappings_file) as f:
        mappings_data = yaml.safe_load(f) or []

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": PURPOSE_CODE_SEED_LOCK_KEY}
    )

    # Clear existing data for idempotent loading. The mappings go first: the
    # purpose_code_canonical_delete_restrict trigger refuses to remove the last
    # canonical row for a code while a mapping still names it.
    await session.execute(delete(PurposeCodeCorridorMapping))
    await session.execute(delete(PurposeCodeCanonical))

    for item in canonical_data:
        _strip_in_place(item, "canonical_code")
        item["effective_from"] = _parse_date(item.get("effective_from"))
        if "effective_to" in item:
            item["effective_to"] = _parse_date(item.get("effective_to"))
        canonical = PurposeCodeCanonical(**item)
        session.add(canonical)

    for item in mappings_data:
        # Every identifying column is stripped, not just some: a trailing space in
        # the YAML would otherwise make a mapping that looks correct in review but
        # never matches a lookup, and the exclusion constraint would not catch it
        # either — " RBI" and "RBI" are different keys.
        _strip_in_place(
            item,
            "canonical_code",
            "corridor_id",
            "external_code",
            "external_standard",
            "external_standard_version",
        )

        item["effective_from"] = _parse_date(item.get("effective_from"))
        item["effective_to"] = _parse_date(item.get("effective_to"))
        mapping = PurposeCodeCorridorMapping(**item)
        session.add(mapping)

    await session.commit()
    logger.info(
        "Successfully loaded %d canonical codes and %d mappings",
        len(canonical_data),
        len(mappings_data),
    )
