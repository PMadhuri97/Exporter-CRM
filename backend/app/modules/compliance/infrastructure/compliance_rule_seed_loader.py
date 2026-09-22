"""Load the compliance rule registry from its GitOps-managed YAML."""

from datetime import date
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.domain.entities.compliance_rule import (
    ComplianceRule,
    RequiredAction,
)
from app.modules.compliance.domain.entities.registry import PurposeCategory
from app.modules.compliance.domain.entities.sector_registry import RiskTier

logger = structlog.get_logger(__name__)
COMPLIANCE_RULE_SEED_LOCK_KEY = 4440001
SEED_DATA_DIR = (
    Path(__file__).resolve().parents[5]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "compliance"
    / "rules"
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
    """Trim incidental whitespace so a stray space cannot break a match."""
    return val.strip() if isinstance(val, str) else val


def _code(val: Any) -> Any:
    return val.strip().upper() if isinstance(val, str) else val


def _enum(enum_cls: type, val: Any) -> Any:
    if val is None:
        return None
    return enum_cls(_text(val))


def _category(val: Any) -> Any:
    """Check the value against the purpose registry's vocabulary, store the string.

    The column is a plain String rather than the enum, because rules carry no
    foreign key to the other registries (§10.5) — but a typo should still fail at
    boot the way an unknown risk tier does, rather than loading cleanly and then
    never matching. ``PurposeCategory`` is the live vocabulary, so validating
    against it here keeps a renamed category from silently disarming a rule.

    The plain value is stored rather than the member: the column's type is
    String, and going through the enum is a check, not a change of storage.
    """
    if val is None:
        return None
    return PurposeCategory(_text(val)).value


async def load_compliance_rules(session: AsyncSession, base_dir: str | Path) -> None:
    base_path = Path(base_dir)

    logger.info("compliance_rule_seed_load_started", seed_dir=str(base_path))

    with open(base_path / "compliance-rules.yaml") as f:
        rule_data = yaml.safe_load(f) or []

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": COMPLIANCE_RULE_SEED_LOCK_KEY}
    )

    await session.execute(delete(ComplianceRule))

    for item in rule_data:
        session.add(
            ComplianceRule(
                rule_id=_code(item["rule_id"]),
                description=_text(item.get("description")),
                corridor_match=_code(item.get("corridor_match")),
                sector_risk_tier_match=_enum(RiskTier, item.get("sector_risk_tier_match")),
                sector_classification_label_match=_text(
                    item.get("sector_classification_label_match")
                ),
                purpose_code_category_match=_category(item.get("purpose_code_category_match")),
                amount_threshold=item.get("amount_threshold"),
                amount_threshold_currency=_code(item.get("amount_threshold_currency")),
                required_action=_enum(RequiredAction, item["required_action"]),
                action_reason=_text(item.get("action_reason")),
                effective_from=_parse_date(item.get("effective_from")),
                effective_to=_parse_date(item.get("effective_to")),
            )
        )

    await session.commit()
    logger.info("compliance_rule_seed_load_completed", rule_count=len(rule_data))
