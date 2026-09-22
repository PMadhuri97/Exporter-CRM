"""Sector taxonomy, external classification codes, and per-jurisdiction risk.

Three separate facts, three tables. What a business does is a stable
platform-owned identifier. How that activity is *coded* is the opinion of a
standards body, and differs between ISIC, NIC and NAICS. How it is *rated* is
the opinion of a regulator, and differs between FATF, a national regime and a
single corridor. Collapsing any two of them forces a schema change the first
time a corridor is onboarded — which is exactly what a column named
``isic_code`` on the registry did.
"""

import enum
import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.compliance.domain.jurisdiction import JurisdictionType
from app.platform.database.models import Base

#: Re-exported so that the historical import site keeps working. The definition
#: lives in ``domain.jurisdiction`` because the pure evaluator carries a resolved
#: jurisdiction in its result and must not import an ORM entity module to do it.
#: Two enums with identical values used to be declared here and there, which
#: compared equal only by accident of both subclassing ``str``.
__all__ = [
    "JurisdictionType",
    "RiskTier",
    "SectorCodeExternalMapping",
    "SectorCodeRegistry",
    "SectorRiskClassification",
]

SCHEMA = "compliance"

#: The half-open period a row is in force for, as Postgres sees it. Declared
#: once because both exclusion constraints below are built on it, and the two
#: must agree with ``is_effective_at`` or the database and the lookup would
#: disagree about what "in force" means on a boundary date.
_PERIOD = text("daterange(effective_from, effective_to, '[)')")


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e])


class RiskTier(str, enum.Enum):
    """Severity ladder a jurisdiction assigns to a sector.

    Ordered least to most severe. ``STANDARD`` is also the tier the lookup
    returns when nothing is in force, so callers must read the accompanying
    not-found indication rather than inferring safety from the tier alone.
    """

    STANDARD = "standard"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class SectorCodeRegistry(Base):
    """The platform's own taxonomy of business sectors.

    Carries neither an external code nor a risk rating: a sector means the same
    thing in every jurisdiction, and only the codings and ratings vary.
    """

    __tablename__ = "sector_code_registry"
    __table_args__ = (
        UniqueConstraint("sector_code", name="uq_sector_code_registry_sector_code"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_registry_period",
        ),
        # A row stored as 'precious_stones_trade' would satisfy every other
        # constraint and then never be found by an exact-match lookup, silently
        # making the sector invisible. Both child tables reach this column
        # through a foreign key, so guarding it here covers all three.
        CheckConstraint(
            "sector_code = upper(sector_code)",
            name="ck_sector_code_registry_sector_code_upper",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sector_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class SectorCodeExternalMapping(Base):
    """One sector's code in one revision of one external standard.

    ``external_standard_version`` is part of the identity, not decoration.
    Standards reassign codes between revisions — an ISIC Rev.3 code and an ISIC
    Rev.4 code may be the same string meaning different activities — so a lookup
    that names only the standard is ambiguous.
    """

    __tablename__ = "sector_code_external_mapping"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_external_mapping_period",
        ),
        CheckConstraint(
            "external_standard = upper(external_standard)",
            name="ck_sector_code_external_mapping_standard_upper",
        ),
        # Two codings of one sector under the same standard revision cannot both
        # be in force: a reporting lookup would have no basis to choose. A unique
        # key on effective_from would not catch it — two rows with different
        # start dates still overlap.
        ExcludeConstraint(
            ("sector_code", "="),
            ("external_standard", "="),
            ("external_standard_version", "="),
            (_PERIOD, "&&"),
            name="ex_sector_code_external_mapping_period",
            using="gist",
        ),
        Index(
            "ix_sector_code_external_mapping_lookup",
            "sector_code",
            "external_standard",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sector_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey(
            f"{SCHEMA}.sector_code_registry.sector_code",
            ondelete="RESTRICT",
            name="fk_sector_code_external_mapping_sector_code",
        ),
        nullable=False,
    )
    external_standard: Mapped[str] = mapped_column(String(20), nullable=False)
    external_standard_version: Mapped[str] = mapped_column(String(30), nullable=False)
    external_code: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class SectorRiskClassification(Base):
    """One authority's risk rating of one sector, valid over a date range.

    The authority is split in two: ``jurisdiction_type`` fixes the precedence,
    ``jurisdiction_value`` names the specific regime. Onboarding a regulator is
    a seed-data row, because nothing in the schema or the lookup enumerates
    which values are legal for a given type.
    """

    __tablename__ = "sector_risk_classification"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_risk_classification_period",
        ),
        # A row stored as 'fatf' would satisfy every other constraint and then
        # never be matched by the framework tier, silently dropping every
        # unmapped jurisdiction to the standard rating.
        CheckConstraint(
            "jurisdiction_value = upper(jurisdiction_value)",
            name="ck_sector_risk_classification_jurisdiction_upper",
        ),
        # The constraint the previous design got wrong. A unique key on
        # effective_from permits two rows with different start dates whose
        # periods overlap, leaving two conflicting risk tiers in force on the
        # same day — and the lookup then has to pick one arbitrarily.
        ExcludeConstraint(
            ("sector_code", "="),
            ("jurisdiction_type", "="),
            ("jurisdiction_value", "="),
            (_PERIOD, "&&"),
            name="ex_sector_risk_classification_period",
            using="gist",
        ),
        Index(
            "ix_sector_risk_classification_lookup",
            "sector_code",
            "jurisdiction_type",
            "jurisdiction_value",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sector_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey(
            f"{SCHEMA}.sector_code_registry.sector_code",
            ondelete="RESTRICT",
            name="fk_sector_risk_classification_sector_code",
        ),
        nullable=False,
    )
    jurisdiction_type: Mapped[JurisdictionType] = mapped_column(
        _enum(JurisdictionType, "jurisdiction_type_enum"), nullable=False
    )
    jurisdiction_value: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(
        _enum(RiskTier, "sector_risk_tier_enum"), nullable=False
    )
    # Null where a regime rates a sector without publishing a label for it.
    classification_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Explanatory only. Never read by rule evaluation — a caveat that changes an
    # outcome belongs in a row of its own, not in prose.
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
