"""``CheckCycle`` — one round of a company's background check.

A cycle groups the inputs one KYC/KYB round rests on — verification results,
screening answers and the decisions taken on them — so a second round (a Re-KYC or
Re-KYB) can run while the first stays readable exactly as it was. The background
check decides on the **current** cycle only: the company's cycle with
the highest ``number``.

**Append-only**, like every record a compliance decision rests on:
``trg_check_cycle_append_only`` runs ``public.prevent_mutation()`` on ``UPDATE`` and
``DELETE`` (migration ``onboarding_0025_check_cycle``), and the repository
exposes neither.

Legacy rows are never updated
-----------------------------
Inputs and decisions recorded before cycles existed carry ``cycle_id IS NULL``. By
the documented read rule they belong to the company's **cycle 1**. The migration
inserts one cycle-1 row per company that already had an
input, dated at its earliest input; it never updates an input row. A company whose
first input arrives later gets its cycle 1 then, from the writer that records the
input (``CheckCycleRepository.current_or_initial``).

Provenance
----------
Every new table carries ``created_by``, ``created_at``, ``source`` and
``source_ref``. Here ``created_by`` is who started the cycle (or the migration's
actor for a backfilled cycle 1), ``source`` the code path or ``MIGRATION``, and
``source_ref`` what caused it where there is something to name — the migration
revision, or the reopen decision a Re-KYC on a ``CLEAR`` company recorded.
``started_at`` is when the round began: the moment it was started, or the earliest
input for a backfilled cycle 1, which is why it is not simply ``created_at``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class CheckCycleKind(str, enum.Enum):
    """Why a cycle was started.

    ``INITIAL`` is cycle 1 and only cycle 1 (``ck_check_cycle_initial_first``).
    ``RE_KYC`` and ``RE_KYB`` are the two re-check buttons. ``FULL`` is reserved by
    the plan for a complete re-check; the database accepts it, the API does not offer
    it yet. Every new cycle starts empty whatever its kind (screening resets), so the
    kind is a label on the round, not a different rule set.
    """

    INITIAL = "INITIAL"
    RE_KYC = "RE_KYC"
    RE_KYB = "RE_KYB"
    FULL = "FULL"


#: ``source`` of a cycle-1 row the migration inserted for a company that already had
#: inputs, and of one a writer created on a company's first input.
CYCLE_SOURCE_MIGRATION = "MIGRATION"
CYCLE_SOURCE_FIRST_INPUT = "FIRST_INPUT"

_KINDS_SQL = ", ".join(f"'{kind.value}'" for kind in CheckCycleKind)


class CheckCycle(AppendOnlyModel):
    """One KYC/KYB round of one company's background check. Locked."""

    __tablename__ = "check_cycle"
    __table_args__ = (
        # One number per company: the current cycle is the highest.
        UniqueConstraint("company_id", "number", name="uq_check_cycle_company_number"),
        # Target of the composite foreign keys that tie a screening row or a decision
        # to a cycle **of the same company**.
        UniqueConstraint("id", "company_id", name="uq_check_cycle_id_company"),
        CheckConstraint("number >= 1", name="ck_check_cycle_number_positive"),
        CheckConstraint(f"kind IN ({_KINDS_SQL})", name="ck_check_cycle_kind"),
        CheckConstraint("(number = 1) = (kind = 'INITIAL')", name="ck_check_cycle_initial_first"),
        # A re-check says why; cycle 1 is simply the first round.
        CheckConstraint(
            "number = 1 OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_check_cycle_reason",
        ),
        CheckConstraint("btrim(created_by) <> ''", name="ck_check_cycle_created_by"),
        CheckConstraint("btrim(source) <> ''", name="ck_check_cycle_source"),
        {"schema": SCHEMA},
    )

    #: The company. `RESTRICT`: a company with a cycle cannot be deleted.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_check_cycle_company_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: 1, 2, 3 … per company. The current cycle is the highest.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: A `CheckCycleKind` value.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Why a re-check was started. Required from cycle 2 (`ck_check_cycle_reason`).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When the round began. For a backfilled cycle 1, the company's earliest input.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The Clear rules in force when the cycle started (`background_check_views`).
    #: `NULL` on a backfilled cycle 1, which the legacy read rule reads as v1.
    rules_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Who started it — from the login session — or the migration's actor.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The code path that created it, or `MIGRATION` / `FIRST_INPUT` for a cycle 1.
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    #: What caused it, where there is something to name (see the module docstring).
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = [
    "CYCLE_SOURCE_FIRST_INPUT",
    "CYCLE_SOURCE_MIGRATION",
    "CheckCycle",
    "CheckCycleKind",
]
