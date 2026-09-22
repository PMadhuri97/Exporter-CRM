import enum
import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Enum,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.domain.required_action import RequiredAction
from app.platform.database.models import Base

SCHEMA = "compliance"

_ASSET_CODE_LEN = 16

__all__ = ["ComplianceRule", "RequiredAction"]


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e])


class ComplianceRule(Base):
    """One rule of the compliance registry, valid over a date range."""

    __tablename__ = "compliance_rule"
    __table_args__ = (
        UniqueConstraint("rule_id", name="uq_compliance_rule_rule_id"),
        CheckConstraint(
            "(amount_threshold IS NULL) = (amount_threshold_currency IS NULL)",
            name="ck_compliance_rule_threshold_paired",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_compliance_rule_period",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)

    # ── Match conditions — NULL means "unconstrained" ─────────────────────────
    corridor_match: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sector_risk_tier_match: Mapped[RiskTier | None] = mapped_column(
        _enum(RiskTier, "sector_risk_tier_enum"), nullable=True
    )
    sector_classification_label_match: Mapped[str | None] = mapped_column(String(50), nullable=True)
    purpose_code_category_match: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amount_threshold: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount_threshold_currency: Mapped[str | None] = mapped_column(
        String(_ASSET_CODE_LEN), nullable=True
    )

    # ── Obligation ────────────────────────────────────────────────────────────
    required_action: Mapped[RequiredAction] = mapped_column(
        _enum(RequiredAction, "compliance_required_action_enum"), nullable=False
    )
    action_reason: Mapped[str] = mapped_column(String, nullable=False)

    # ── Effectivity ───────────────────────────────────────────────────────────
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
