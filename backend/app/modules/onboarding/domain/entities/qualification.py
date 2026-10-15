"""Qualification records (``docs/contracts/criterion-result.md``).

Four tables, from migration 0017:

* ``qualification_criterion`` — one row per **version** of a criterion. A
  row is never changed: editing a criterion adds the next version, so a result
  recorded against version 2 keeps pointing at exactly the rule it was judged
  by. Append-only in the database (``prevent_mutation()``).
* ``qualification_result`` — one criterion checked against one company,
  once. Append-only: checking again adds a row.
* ``qualification_outcome`` — a person's overall decision. Append-only; a
  re-review is a new outcome that ``supersedes`` the previous one, and the
  database keeps each company's outcomes a single chain.

None of this reuses the screening checklist, the background check or
``verification_result`` (contract §1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
    ThresholdComparison,
)
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


def _enum(enum_cls, name: str) -> Enum:
    return Enum(enum_cls, name=name, schema=SCHEMA)


class QualificationCriterion(AppendOnlyModel):
    """One version of one criterion. Immutable once written."""

    __tablename__ = "qualification_criterion"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_qualification_criterion_key_version"),
        # Migration 0017's checks: a snake_case key, versions from 1, and the columns a
        # kind needs — present for it and absent otherwise.
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*$'", name="ck_qualification_criterion_key"),
        CheckConstraint("version >= 1", name="ck_qualification_criterion_version"),
        CheckConstraint(
            "(kind = 'NUMBER_THRESHOLD' AND comparison IS NOT NULL AND threshold IS NOT NULL"
            " AND allowed_values IS NULL)"
            " OR (kind = 'YES_NO' AND comparison IS NULL AND threshold IS NULL"
            " AND allowed_values IS NULL)"
            " OR (kind = 'ALLOWED_VALUES' AND comparison IS NULL AND threshold IS NULL"
            " AND jsonb_typeof(allowed_values) = 'array' AND jsonb_array_length(allowed_values) > 0)",
            name="ck_qualification_criterion_kind_shape",
        ),
        CheckConstraint(
            "auto_source IS NULL OR auto_source IN ('IEC_VERIFICATION', 'YEARS_ESTABLISHED', "
            "'INDUSTRY', 'EXPORT_MARKETS', 'TRADE_HISTORY', 'DEAL_VALUE')",
            name="ck_qualification_criterion_auto_source",
        ),
        {"schema": SCHEMA},
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[CriterionKind] = mapped_column(
        _enum(CriterionKind, "qualification_criterion_kind_enum"), nullable=False
    )
    comparison: Mapped[ThresholdComparison | None] = mapped_column(
        _enum(ThresholdComparison, "qualification_threshold_comparison_enum"), nullable=True
    )
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: SQL NULL, not JSON null, when absent (`none_as_null`): the kind-shape
    #: check tests `allowed_values IS NULL`.
    allowed_values: Mapped[list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Who wrote this version, from the session. `NULL` for the seeded v1s.
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Where an automatic result comes from (``domain/qualification_auto.py``), if any.
    auto_source: Mapped[str | None] = mapped_column(String(24), nullable=True)


class QualificationResult(AppendOnlyModel):
    """One criterion, at one version, checked against one company."""

    __tablename__ = "qualification_result"
    __table_args__ = (
        # Migration 0017; declared so autogenerate does not propose dropping it.
        Index(
            "ix_qualification_result_customer_recent",
            "customer_id",
            text("recorded_at DESC"),
            text("id DESC"),
        ),
        # Migration 0017: anything but UNKNOWN shows its evidence, and only an
        # automated result carries a confidence, between 0 and 1.
        CheckConstraint(
            "result = 'UNKNOWN' OR btrim(COALESCE(evidence_note, '')) <> ''"
            " OR jsonb_array_length(evidence_refs) > 0",
            name="ck_qualification_result_evidence",
        ),
        CheckConstraint(
            "confidence IS NULL OR (decided_by_kind = 'AUTOMATED'"
            " AND confidence >= 0 AND confidence <= 1)",
            name="ck_qualification_result_confidence",
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.exporter_profile.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.qualification_criterion.id", ondelete="RESTRICT"),
        nullable=False,
    )
    result: Mapped[CriterionResultValue] = mapped_column(
        _enum(CriterionResultValue, "qualification_result_value_enum"), nullable=False
    )
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[QualificationSource] = mapped_column(
        _enum(QualificationSource, "qualification_source_enum"), nullable=False
    )
    decided_by_kind: Mapped[DecidedByKind] = mapped_column(
        _enum(DecidedByKind, "qualification_decided_by_kind_enum"), nullable=False
    )
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `[{"type": "document" | "verification_result" | "url", "ref": str}]`.
    evidence_refs: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    #: The signed-in user; `NULL` only when the platform recorded it.
    recorded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    criterion: Mapped[QualificationCriterion] = relationship(lazy="joined")


class QualificationOutcome(AppendOnlyModel):
    """A reviewer's overall decision, never edited — a re-review supersedes it."""

    __tablename__ = "qualification_outcome"
    __table_args__ = (
        # The outcome chain's integrity, from migration 0017: each outcome is
        # superseded at most once, and a company has exactly one first outcome.
        # Declared so autogenerate does not propose dropping either.
        UniqueConstraint(
            "supersedes_outcome_id", name="uq_qualification_outcome_supersedes_once"
        ),
        Index(
            "uq_qualification_outcome_first_per_company",
            "customer_id",
            unique=True,
            postgresql_where=text("supersedes_outcome_id IS NULL"),
        ),
        Index(
            "ix_qualification_outcome_customer_recent",
            "customer_id",
            text("decided_at DESC"),
            text("id DESC"),
        ),
        # Migration 0017: every outcome but QUALIFIED gives at least one reason code.
        CheckConstraint(
            "outcome = 'QUALIFIED' OR jsonb_array_length(reason_codes) >= 1",
            name="ck_qualification_outcome_reason_codes",
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.exporter_profile.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    outcome: Mapped[QualificationOutcomeValue] = mapped_column(
        _enum(QualificationOutcomeValue, "qualification_outcome_value_enum"), nullable=False
    )
    reason_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the server suggested at the moment of decision — kept apart from
    #: `outcome`, which is the person's call.
    suggested_outcome: Mapped[QualificationOutcomeValue] = mapped_column(
        _enum(QualificationOutcomeValue, "qualification_outcome_value_enum"), nullable=False
    )
    #: The results the decision rested on: the current result for every
    #: active criterion when it was made. Later results do not change it.
    result_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source: Mapped[QualificationSource] = mapped_column(
        _enum(QualificationSource, "qualification_source_enum"), nullable=False
    )
    decided_by_kind: Mapped[DecidedByKind] = mapped_column(
        _enum(DecidedByKind, "qualification_decided_by_kind_enum"), nullable=False
    )
    supersedes_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.qualification_outcome.id", ondelete="RESTRICT"),
        nullable=True,
    )
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "QualificationCriterion",
    "QualificationOutcome",
    "QualificationResult",
]
