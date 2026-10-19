"""``ExporterContact`` — a person at a company: a contact, a director, a beneficial owner.

A person is one row with roles (migration 0057): ``is_contact`` (someone we talk to),
``is_director`` and ``is_ubo``. A director who is also the main contact is one row, not
two. Every row has at least one role (``ck_exporter_contact_has_role``), and only a
contact can be the primary contact (``ck_exporter_contact_primary_is_contact``). Readers
that mean "contacts" filter on ``is_contact``; the sanctions screening and group
suggestions read directors and beneficial owners.

The person fields are optional, and each belongs to its role: ``din`` to a director,
``ownership_pct`` and ``control_type`` to a beneficial owner. The identification number
is stored **encrypted** (``identification_encrypted``, the field cipher bank accounts
use) with its last four characters for the masked view. Date of birth, DIN and the
identification number are shown in full only to a holder of
``exporters:view_full_tax_id``, like a PAN (``api/schemas/engagement.py``).

A person is **never deleted** (``trg_exporter_contact_no_delete``): leaving is a status,
and screening runs point at the row. ``uq_exporter_contact_id_customer`` exists so a
screening run's person must be a person of the run's own company
(``fk_sanctions_run_subject_person``).

``customer_id`` points at a company that exists: migration 0014 added
``fk_exporter_contact_customer_id`` (its ``_LINKED`` tuple, step 4), a real
foreign key to ``exporter_profile.customer_id`` with ``ON DELETE RESTRICT``. It
is declared on the column below so the ORM says the same thing the database
does.

This docstring used to say the opposite — "a bare, indexed UUID with no formal
FK", on the reasoning that a contact could be recorded for a Lead before any
``ExporterProfile`` row existed. That reasoning stopped applying when the
company record became the CRM's own table (``docs/contracts/company-record.md``
§1): a company *is* an ``exporter_profile`` row from the moment it is created,
Lead or not, so there is no state in which a contact has a company id but no
company. The constraint has its own direct-SQL test; the
constraint itself was already there, and 0016 does not re-add it.

At most one contact per ``customer_id`` may have ``is_primary_contact=True`` —
enforced by a partial unique index (migration ``onboarding_0005_exporter_crm``)
and, redundantly, by ``ExporterContactActivityService.add_contact`` demoting
any existing primary in the same transaction before the DB constraint is ever
reached in normal operation.
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
    FetchedValue,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

#: How a beneficial owner holds control (the old system's ``ubo_control_type_enum``).
CONTROL_TYPES = ("DIRECT_OWNERSHIP", "INDIRECT_OWNERSHIP", "VOTING_RIGHTS", "OTHER_CONTROL")
#: The document an identification number comes from.
IDENTIFICATION_TYPES = ("PASSPORT", "NATIONAL_ID", "DRIVING_LICENCE")
#: Where a row came from when it was not typed in: a copy of an old-system owner.
LEGACY_UBO_SOURCE = "LEGACY_UBO_RECORD"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class ExporterContact(AnerModel):
    __tablename__ = "exporter_contact"
    __table_args__ = (
        Index("ix_exporter_contact_customer_id", "customer_id"),
        # Partial unique index: at most one primary contact per customer_id.
        # A plain UniqueConstraint on (customer_id, is_primary_contact) would
        # also forbid a second *non*-primary contact for the same customer,
        # which is the common case — same partial-index pattern as
        # onboarding_request's uq_onboarding_request_active_customer.
        Index(
            "uq_exporter_contact_primary_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("is_primary_contact = true"),
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'LEFT_COMPANY')", name="ck_exporter_contact_status"
        ),
        # Only someone still reachable can be the person to reach.
        CheckConstraint(
            "status = 'ACTIVE' OR is_primary_contact = false",
            name="ck_exporter_contact_primary_is_active",
        ),
        # ── People (0057) ────────────────────────────────────────────────────
        CheckConstraint("is_contact OR is_director OR is_ubo", name="ck_exporter_contact_has_role"),
        CheckConstraint(
            "NOT is_primary_contact OR is_contact", name="ck_exporter_contact_primary_is_contact"
        ),
        CheckConstraint(
            "din IS NULL OR (is_director AND din ~ '^[0-9]{8}$')", name="ck_exporter_contact_din"
        ),
        CheckConstraint(
            "ownership_pct IS NULL OR (is_ubo AND ownership_pct >= 0 AND ownership_pct <= 100)",
            name="ck_exporter_contact_ownership",
        ),
        CheckConstraint(
            f"control_type IS NULL OR (is_ubo AND {_in('control_type', CONTROL_TYPES)})",
            name="ck_exporter_contact_control_type",
        ),
        CheckConstraint(
            "nationality IS NULL OR nationality ~ '^[A-Z]{2}$'",
            name="ck_exporter_contact_nationality",
        ),
        CheckConstraint(
            "residence_country IS NULL OR residence_country ~ '^[A-Z]{2}$'",
            name="ck_exporter_contact_residence",
        ),
        CheckConstraint(
            "(identification_encrypted IS NULL) = (identification_type IS NULL) "
            "AND (identification_encrypted IS NULL) = (identification_last4 IS NULL) "
            "AND (identification_type IS NULL OR "
            f"{_in('identification_type', IDENTIFICATION_TYPES)})",
            name="ck_exporter_contact_identification",
        ),
        # The target of a screening run's person: same person, same company.
        UniqueConstraint("id", "customer_id", name="uq_exporter_contact_id_customer"),
        {"schema": SCHEMA},
    )
    #: ``name`` is set by the database, so an INSERT or UPDATE must read it back
    #: (``RETURNING``): left expired, the next read of it is a lazy load, which an async
    #: session refuses (``MissingGreenlet``) — the history row for a role change reads it.
    __mapper_args__ = {"eager_defaults": True}

    #: The company. `ON DELETE RESTRICT`, so a company with contacts cannot be
    #: deleted out from under them — the same rule every other child of
    #: `exporter_profile` got in 0014.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_exporter_contact_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: A person's first and last name, kept apart (migration 0062). The last name is
    #: optional: plenty of people go by one name.
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The full name, set by the database from the two above and never written here:
    #: every reader that wants "the contact's name" reads this, and it cannot drift.
    #: Until the release after 0062 it is a plain column kept in step by
    #: ``trg_exporter_contact_sync_name`` (so the release before, which writes
    #: ``name``, keeps working during a deploy); then it becomes a computed column.
    name: Mapped[str] = mapped_column(
        String(511),
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
        nullable=False,
    )
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ``ContactStatus``: ACTIVE, INACTIVE or LEFT_COMPANY, with when and why it changed.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When someone last confirmed these details are right, and who.
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Roles ────────────────────────────────────────────────────────────────
    is_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_director: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_ubo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # ── Person fields; all optional ──────────────────────────────────────────
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: ISO-3166-1 alpha-2.
    nationality: Mapped[str | None] = mapped_column(String(2), nullable=True)
    residence_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: Director Identification Number (India): eight digits. A director's only.
    din: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: A beneficial owner's only.
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    control_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    identification_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: The number, sealed by ``platform/security/field_cipher``; never stored in clear.
    identification_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    identification_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    #: Where the row came from when not typed in (``LEGACY_UBO_SOURCE``), and its id there.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["CONTROL_TYPES", "IDENTIFICATION_TYPES", "LEGACY_UBO_SOURCE", "ExporterContact"]
