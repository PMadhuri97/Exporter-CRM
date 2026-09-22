import enum
import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import Base

SCHEMA = "compliance"


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e])


def _validity_range(table: str):
    """The half-open validity window a row claims, as a daterange.

    ``effective_to`` NULL means open-ended, which ``daterange`` already renders as
    unbounded — so a currently-valid row conflicts with anything starting after it
    without needing a sentinel end date. ``table`` is schema-qualified by the
    caller so this reads correctly regardless of search_path.
    """
    return func.daterange(
        text(f"{table}.effective_from"), text(f"{table}.effective_to"), text("'[)'")
    )


class PurposeCategory(str, enum.Enum):
    TRADE = "trade"
    SERVICES = "services"
    INVESTMENT = "investment"
    PERSONAL = "personal"
    OTHER = "other"


class PurposeCodeCanonical(Base):
    """The platform's own purpose code, independent of any regulator's numbering.

    A code is not unique by itself — it is unique *at a point in time*. Retiring a
    code and later reinstating it is two rows with adjacent windows, which is why
    the table carries an exclusion constraint rather than UNIQUE (canonical_code).
    """

    __tablename__ = "purpose_code_canonical"
    __table_args__ = (
        ExcludeConstraint(
            ("canonical_code", "="),
            (_validity_range(f"{SCHEMA}.purpose_code_canonical"), "&&"),
            name="ex_purpose_code_canonical_validity",
            using="gist",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[PurposeCategory] = mapped_column(
        _enum(PurposeCategory, "purpose_category_enum"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class PurposeCodeCorridorMapping(Base):
    """What one corridor's regulator calls a canonical code, under one standard revision.

    ``canonical_code`` references :class:`PurposeCodeCanonical` but is not a
    foreign key: Postgres requires a UNIQUE constraint on a FK's target, and that
    is exactly what the canonical exclusion constraint replaces. Two triggers
    created in migration ``compliance_0002_std_versions`` enforce the same
    guarantees instead — an unknown canonical_code is rejected on write, and the
    last row for a referenced code cannot be deleted. Both raise SQLSTATE 23503,
    as the foreign key did.
    """

    __tablename__ = "purpose_code_corridor_mapping"
    __table_args__ = (
        ExcludeConstraint(
            ("canonical_code", "="),
            ("corridor_id", "="),
            ("external_standard", "="),
            ("external_standard_version", "="),
            (_validity_range(f"{SCHEMA}.purpose_code_corridor_mapping"), "&&"),
            name="ex_purpose_code_mapping_validity",
            using="gist",
        ),
        Index("ix_purpose_code_mapping_canonical_corridor", "canonical_code", "corridor_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_code: Mapped[str] = mapped_column(String(50), nullable=False)
    corridor_id: Mapped[str] = mapped_column(String(50), nullable=False)
    external_standard: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Wider than the other codes because it holds a citation, not an identifier —
    #: "RBI Purpose Code Master Circular 2025", "ISO 20022 External Code Set v11".
    external_standard_version: Mapped[str] = mapped_column(String(100), nullable=False)
    external_code: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
