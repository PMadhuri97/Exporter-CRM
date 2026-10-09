"""Sanctions screening: lists, runs, the lists a run covered, hits and dispositions.

Runs, their lists, hits and dispositions are **append-only**
(``trg_*_append_only``): a changed decision on a hit is a new disposition that
supersedes the previous one. See migration ``onboarding_0052_sanctions``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

SUBJECT_TYPES = ("COMPANY", "DIRECTOR", "UBO")
DISPOSITIONS = ("OPEN", "FALSE_POSITIVE", "TRUE_MATCH_PROPOSED", "TRUE_MATCH", "ESCALATED")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class SanctionsList(AnerModel):
    """One version of a sanctions list an administrator keeps."""

    __tablename__ = "sanctions_list"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_sanctions_list_code_version"),
        Index(
            "uq_sanctions_list_current_code", "code", unique=True, postgresql_where=text("is_current")
        ),
        CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_sanctions_list_code"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: The date of the list's own published version this row describes.
    list_version_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SanctionsRun(AnerModel):
    """One screening of one subject of a company."""

    __tablename__ = "sanctions_run"
    __table_args__ = (
        Index("ix_sanctions_run_company", "company_id", "performed_at"),
        CheckConstraint(_in("subject_type", SUBJECT_TYPES), name="ck_sanctions_run_subject_type"),
        {"schema": SCHEMA},
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_sanctions_run_company",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_reference: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.check_cycle.id", name="fk_sanctions_run_cycle"),
        nullable=True,
    )
    performed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, server_default="MANUAL")
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: What was searched for: `{"name": ..., "aliases": [...], "country": ...}`.
    search_terms: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SanctionsRunList(AnerModel):
    """A list a run covered, and the version date it used."""

    __tablename__ = "sanctions_run_list"
    __table_args__ = (
        UniqueConstraint("run_id", "code", name="uq_sanctions_run_list_code"),
        {"schema": SCHEMA},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sanctions_run.id", ondelete="RESTRICT"), nullable=False
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sanctions_list.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    list_version_date: Mapped[date] = mapped_column(Date, nullable=False)


class SanctionsHit(AnerModel):
    """A possible match a run found on one list."""

    __tablename__ = "sanctions_hit"
    __table_args__ = (
        Index("ix_sanctions_hit_run", "run_id"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_sanctions_hit_score"),
        {"schema": SCHEMA},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sanctions_run.id", ondelete="RESTRICT"), nullable=False
    )
    list_code: Mapped[str] = mapped_column(String(40), nullable=False)
    matched_name: Mapped[str] = mapped_column(String(255), nullable=False)
    list_entry_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class SanctionsDisposition(AnerModel):
    """A decision about a hit. The one nothing supersedes is the hit's current one."""

    __tablename__ = "sanctions_disposition"
    __table_args__ = (
        Index("ix_sanctions_disposition_hit", "hit_id"),
        Index(
            "uq_sanctions_disposition_first",
            "hit_id",
            unique=True,
            postgresql_where=text("supersedes_id IS NULL"),
        ),
        UniqueConstraint("supersedes_id", name="uq_sanctions_disposition_supersedes"),
        CheckConstraint(_in("disposition", DISPOSITIONS), name="ck_sanctions_disposition_value"),
        CheckConstraint(
            "disposition = 'OPEN' OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_sanctions_disposition_reason",
        ),
        {"schema": SCHEMA},
    )

    hit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sanctions_hit.id", ondelete="RESTRICT"), nullable=False
    )
    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.sanctions_disposition.id", ondelete="RESTRICT"),
        nullable=True,
    )


__all__ = [
    "DISPOSITIONS",
    "SUBJECT_TYPES",
    "SanctionsDisposition",
    "SanctionsHit",
    "SanctionsList",
    "SanctionsRun",
    "SanctionsRunList",
]
