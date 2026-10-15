"""``ExporterGstin`` — one GST registration held by a company, grown into a full
branch record.

A company holds one GSTIN per state, so several rows per
company; the same GSTIN twice on one company is refused
(``uq_exporter_gstin_customer_gstin``). The same GSTIN on two *different* companies
is allowed by the database on purpose: it is a warning the service reports, never a
constraint (architecture decision 4).

The format is checked twice — by ``domain/tax_identifiers.py`` for a clean 422, and
by ``ck_exporter_gstin_format`` so nothing malformed can be written around the
service. That a GSTIN embeds its company's PAN is the service's rule: it spans two
tables.

A GSTIN is a branch
-------------------
The CRM needs a per-branch record, because a company trading from Maharashtra and
Karnataka has two addresses, two statuses and possibly a problem in one of them.
Rather than a new ``gst_registration`` table and a copy, the row grew in place:
every existing row, FK and repository stays, and nothing
has to be moved.

Three facts that are easy to confuse, kept apart:

* ``status`` — what the **GST portal** says (live, cancelled, suspended, or nobody
  has checked). Not ours to decide.
* ``active`` — whether **we** still use this branch. A soft deactivation, because a
  deal handed over last year invoiced through it and that record must stay
  readable.
* ``flag_status`` — whether **compliance** has a problem with it.

A row is **never deleted.** ``trg_exporter_gstin_no_delete`` refuses ``DELETE``, and
``gstin_rows`` no longer cascades ``delete-orphan``. Before branches, an edit that
dropped a GSTIN from the list deleted its row — which, once a deal records its
invoicing branch (``deal.seller_gst_registration_id``), would hit that
FK's ``RESTRICT`` and fail; and where it succeeded it destroyed the record of a
branch the company really did trade through. Deactivation replaces it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.exporter_enums import (
    GstRegistrationFlag,
    GstRegistrationStatus,
)
from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class ExporterGstin(AnerModel):
    __tablename__ = "exporter_gstin"
    __table_args__ = (
        UniqueConstraint("customer_id", "gstin", name="uq_exporter_gstin_customer_gstin"),
        # `(id, customer_id)` so a deal's invoicing branch can be tied to its seller by
        # a **composite** FK: the database then refuses a deal
        # pointing at another company's branch, rather than relying on the service to
        # check. Redundant on its own — `id` is already the primary key — and that is
        # the point: it exists to be referenced.
        UniqueConstraint("id", "customer_id", name="uq_exporter_gstin_id_customer_id"),
        # Migration 0014: the duplicate-GSTIN warning looks a GSTIN up across companies.
        Index("ix_exporter_gstin_gstin", "gstin"),
        # The GSTIN's shape (0014): a two-digit state code, the holder's PAN, an entity
        # number, `Z`, and a check character.
        CheckConstraint(
            "gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'",
            name="ck_exporter_gstin_format",
        ),
        # `state_code` is derived from the GSTIN, so it may not contradict it (0054).
        CheckConstraint(
            "state_code IS NULL OR state_code = left(gstin, 2)",
            name="ck_exporter_gstin_state_code",
        ),
        # A flag must say why. Enforced here and not only in the service
        # because the reason is the whole value of the flag to whoever reads the block
        # it causes.
        CheckConstraint(
            "flag_status <> 'FLAGGED' OR (flag_reason IS NOT NULL AND length(btrim(flag_reason)) > 0)",
            name="ck_exporter_gstin_flag_reason",
        ),
        # A deactivated row says when and by whom; an active one says neither.
        CheckConstraint(
            "(active AND deactivated_at IS NULL AND deactivated_by IS NULL)"
            " OR (NOT active AND deactivated_at IS NOT NULL)",
            name="ck_exporter_gstin_deactivation",
        ),
        # The address this branch trades from, which must be its own company's.
        # `use_alter`: an address names its GST registration too, so the two tables
        # refer to each other.
        ForeignKeyConstraint(
            ["address_id", "customer_id"],
            [f"{SCHEMA}.company_address.id", f"{SCHEMA}.company_address.customer_id"],
            name="fk_exporter_gstin_address",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        # Retired, and deliberately **not mapped** (`__mapper_args__` below): declared so the
        # table still matches the database, while the ORM never names it in an INSERT,
        # UPDATE or SELECT. `deferred` is not enough — the ORM still inserts an explicit
        # NULL into every mapped nullable column with no default — and an instance of this
        # release must keep working once a later migration drops the column.
        # The branch's old free-text address: `convert_gst_addresses` reads it through
        # `__table__.c` and turns it into a linked company address.
        Column("address", Text, nullable=True),
        {"schema": SCHEMA},
    )
    __mapper_args__ = {"exclude_properties": ["address"]}

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.exporter_profile.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)

    # ── The branch ───────────────────────────────────────────────────────────

    #: Characters 1–2 of the GSTIN, the GST Network's state code. Derived, never
    #: entered: a typed state could contradict the GSTIN it sits beside.
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: The state's name for that code (``domain/gst_states.py``). ``NULL`` for a code
    #: not in that list — recorded as unknown rather than guessed, since the format
    #: check accepts any two digits.
    state_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: What the GST portal says. ``UNVERIFIED`` until somebody checks (see the enum:
    #: it is deliberately not ``ACTIVE``).
    status: Mapped[GstRegistrationStatus] = mapped_column(
        Enum(
            GstRegistrationStatus,
            name="gst_registration_status_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
        server_default=GstRegistrationStatus.UNVERIFIED.value,
        default=GstRegistrationStatus.UNVERIFIED,
    )
    #: The company address this branch trades from, when one has been linked — the
    #: branch's only address.
    address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    #: Compliance's flag on this branch. ``FLAGGED`` needs a reason.
    flag_status: Mapped[GstRegistrationFlag] = mapped_column(
        Enum(
            GstRegistrationFlag,
            name="gst_registration_flag_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
        server_default=GstRegistrationFlag.NONE.value,
        default=GstRegistrationFlag.NONE,
    )
    flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Whether we still use this branch. A soft deactivation — the row stays, because
    #: a handed-over deal invoiced through it.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Who deactivated it. A plain string, like every other ``actor_id`` in this
    #: module: a migration or a script is not a user.
    deactivated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    @property
    def is_flagged(self) -> bool:
        return self.flag_status is GstRegistrationFlag.FLAGGED


__all__ = ["ExporterGstin"]
