"""Qualification records — **owner: Developer 2** (L2-09, L2-10,
``docs/contracts/criterion-result.md``).

Four tables, from migration 0017:

* ``qualification_criterion`` — one row per **version** of a criterion. A
  row is never changed: editing a criterion adds the next version, so a result
  recorded against version 2 keeps pointing at exactly the rule it was judged
  by. Append-only in the database (``prevent_mutation()``).
* ``qualification_reason_code`` — the settings list a ``NOT_QUALIFIED``
  outcome's reason codes are checked against.
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
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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
from app.platform.database.models import AnerModel, AppendOnlyModel

SCHEMA = "onboarding"


def _enum(enum_cls, name: str) -> Enum:
    return Enum(enum_cls, name=name, schema=SCHEMA)


class QualificationCriterion(AppendOnlyModel):
    """One version of one criterion. Immutable once written."""

    __tablename__ = "qualification_criterion"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_qualification_criterion_key_version"),
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


class QualificationReasonCode(AnerModel):
    """A code a `NOT_QUALIFIED` outcome may give (contract §5.2)."""

    __tablename__ = "qualification_reason_code"
    __table_args__ = (
        UniqueConstraint("code", name="uq_qualification_reason_code_code"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    #: `other` needs a note alongside it.
    requires_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class QualificationResult(AppendOnlyModel):
    """One criterion, at one version, checked against one company."""

    __tablename__ = "qualification_result"
    __table_args__ = {"schema": SCHEMA}

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
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
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
    __table_args__ = {"schema": SCHEMA}

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.exporter_profile.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    outcome: Mapped[QualificationOutcomeValue] = mapped_column(
        _enum(QualificationOutcomeValue, "qualification_outcome_value_enum"), nullable=False
    )
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the server suggested at the moment of decision — kept apart from
    #: `outcome`, which is the person's call.
    suggested_outcome: Mapped[QualificationOutcomeValue] = mapped_column(
        _enum(QualificationOutcomeValue, "qualification_outcome_value_enum"), nullable=False
    )
    #: The results the decision rested on: the current result for every
    #: active criterion when it was made. Later results do not change it.
    result_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
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
    "QualificationReasonCode",
    "QualificationResult",
]
