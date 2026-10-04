"""``ExporterProfile`` — the enduring exporter/customer relationship record
(EXP-1, Exporter CRM Phase 1).

Not a facet of any single ``OnboardingRequest``: a profile may exist before an
onboarding journey ever starts (a Lead entered by Sales, nothing verified
yet), and a customer keeps exactly one profile across every historical
``OnboardingRequest`` row for its ``customer_id`` (re-verification, renewed
KYB, a second financing product each start a new ``OnboardingRequest``, never
a new ``ExporterProfile``). ``customer_id`` is therefore unique here, and
deliberately not a foreign key to ``onboarding_request``.

``gstin``/``pan``/``iec`` are India-specific identifiers not already covered
by ``OnboardingRequest.registration_number``: confirmed against that column
(CIN-equivalent — the country-generic company-registration number captured at
onboarding-request creation), which is a different identifier from all three
of GSTIN (tax registration), PAN (income-tax id) and IEC (import-export
code). None of the three duplicate anything ``OnboardingRequest`` already
stores, so they live here rather than being derived.

The company's identity — ``name``, ``country``, ``cin`` — lives on this
record (``docs/contracts/company-record.md`` §2.1, migration 0014), as do its
``pan`` (unique across companies), its GSTINs (``ExporterGstin``, several per
company) and its commercial ``marker``. No CRM code reads a company's identity
from the legacy ``onboarding_request`` table.

Each gauge's **current** value is carried here so lists and filters need no join
(architecture §3.8), and each is written by exactly one service, which writes the
history row in the same transaction. ``journey`` and ``qualification`` are
Developer 2's; ``conversation`` and ``conversation_check_back_on`` (0016) are
Developer 3's and are written only by ``ConversationService``; ``background_check``
(0015) is Developer 4A's.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    pass

SCHEMA = "onboarding"


class ExporterProfile(AnerModel):
    """One enduring profile per exporter/customer identity.

    ``source`` is immutable once set — enforced both here at the service
    layer (``ExporterProfileService.update_profile`` refuses to touch it) and
    by ``trg_exporter_profile_source_immutability`` at the database level
    (migration ``onboarding_0005_exporter_crm``, reusing the existing
    ``onboarding.prevent_field_mutation_when_set`` function rather than
    defining a second copy of it).

    ``date_added`` is likewise immutable (``server_default=now()``, never
    written to after insert) — it records when the relationship began, which
    must not silently move if the row is later edited.
    """

    __tablename__ = "exporter_profile"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_exporter_profile_customer_id"),
        # A check-back date exactly when the conversation is `NOT_NOW`, never
        # otherwise (migration 0016, `docs/contracts/engagement.md` §2.3). Same
        # shape as `ck_exporter_profile_marker_reason`, and for the same reason:
        # a value that is only meaningful alongside another must not outlive it.
        CheckConstraint(
            "(conversation = 'NOT_NOW' AND conversation_check_back_on IS NOT NULL)"
            " OR (conversation <> 'NOT_NOW' AND conversation_check_back_on IS NULL)",
            name="ck_exporter_profile_conversation_check_back",
        ),
        # Declared so the metadata matches the migrations that created them. Without
        # these, `alembic revision --autogenerate` proposes dropping them — decision
        # 4's PAN rule above all (`test_orm_matches_the_onboarding_schema.py`).
        UniqueConstraint("pan", name="uq_exporter_profile_pan"),  # 0014, decision 4
        Index("ix_exporter_profile_marker", "marker"),  # 0014
        Index("ix_exporter_profile_journey", "journey"),  # 0017
        Index("ix_exporter_profile_qualification", "qualification"),  # 0017
        Index("ix_exporter_profile_background_check", "background_check"),  # 0015
        Index("ix_exporter_profile_conversation", "conversation"),  # 0016
        Index(  # 0016
            "ix_exporter_profile_conversation_check_back",
            "conversation_check_back_on",
            postgresql_where=text("conversation_check_back_on IS NOT NULL"),
        ),
        Index(  # 0023 — Developer 1 (F1): the "Re-KYC due" list
            "ix_exporter_profile_background_check_expires_at",
            "background_check_expires_at",
            postgresql_where=text("background_check_expires_at IS NOT NULL"),
        ),
        # ── 0032 — Developer 3 (F3): identity and pipeline (plan P4-1) ───────
        #
        # `NOT_IN_PIPELINE` means the journey has not started. Enforced here and not
        # only in the service, because the buyer migration writes these rows directly
        # and a buyer that leaked into the pipeline counts would be invisible until
        # somebody noticed the numbers.
        # Ten letters or digits, the same rule `IEC_RE` enforces in the service
        # (migration 0040). Every other identifier on this table has had its format
        # checked by the database since 0014; the IEC was the one that did not.
        CheckConstraint(
            "iec IS NULL OR iec ~ '^[A-Z0-9]{10}$'",
            name="ck_exporter_profile_iec_format",
        ),
        CheckConstraint(
            "pipeline_status <> 'NOT_IN_PIPELINE'"
            " OR (journey = 'LEAD'"
            "     AND qualification = 'NOT_YET_REVIEWED'"
            "     AND conversation = 'NOT_CONTACTED')",
            name="ck_exporter_profile_not_in_pipeline_start",
        ),
        # A foreign registration number identifies one company per country. Normalised
        # (upper-cased, inner whitespace and punctuation stripped) so "KVK 1234-56" and
        # "kvk123456" collide, which is the whole point. Partial: most rows are NULL,
        # and two companies with no number are not duplicates.
        Index(
            "uq_exporter_profile_country_registration_number",
            "country",
            text("upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))"),
            unique=True,
            postgresql_where=text(
                "registration_number IS NOT NULL AND country IS NOT NULL"
            ),
        ),
        # "Which companies did this deal's buyer become?" — the buyer migration's own
        # read, and the company page's "created from deal X" link.
        Index(
            "ix_exporter_profile_created_via_deal_id",
            "created_via_deal_id",
            postgresql_where=text("created_via_deal_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # ── India-specific identifiers (not covered by OnboardingRequest) ────────
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    iec: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── Origin (immutable once set — see class docstring) ────────────────────
    source: Mapped[ExporterSource] = mapped_column(
        Enum(ExporterSource, name="exporter_source_enum", schema=SCHEMA), nullable=False
    )

    relationship_manager: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Which `auth.users` row this display string refers to, when known —
    #: added in `onboarding_0009_relationship_manager_user` specifically so
    #: the frontend's ownership-scoped PII-reveal check (`OPERATIONS` may
    #: reveal on exporters they own) has something reliable to compare
    #: against. No FK to `auth.users` — see that migration's docstring for
    #: why (matches this codebase's `assigned_to`/`actor_id` convention).
    #: Nothing sets this yet; a future "assign relationship manager" action
    #: is expected to validate it against a real, active user before
    #: writing it.
    relationship_manager_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── Identity (L2-03, columns from migration 0014) ──────────────────────
    #: Nullable only while the API's unnamed create path exists; the database
    #: refuses a blank name (`ck_exporter_profile_name_not_blank`).
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: ISO 3166-1 alpha-2, upper case (`ck_exporter_profile_country_format`).
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: Company registration number (`ck_exporter_profile_cin_format`).
    cin: Mapped[str | None] = mapped_column(String(21), nullable=True)

    #: The company's GST registrations, one row each (`ExporterGstin`), newest last.
    #: Loaded with the profile (`selectin`), so async code never lazy-loads it.
    #:
    #: **No `delete-orphan`** since task 3.12. A registration is a branch the company
    #: really traded through: a handed-over deal records which one it invoiced from
    #: (`deal.seller_gst_registration_id`), so deleting the row would either break
    #: that FK's `RESTRICT` or destroy the record. Dropping one is a *deactivation*
    #: (`active = false`), and `trg_exporter_gstin_no_delete` refuses a DELETE outright
    #: — including one the ORM would otherwise emit from this relationship.
    gstin_rows: Mapped[list[ExporterGstin]] = relationship(
        lazy="selectin",
        order_by="ExporterGstin.created_at, ExporterGstin.gstin",
    )

    # ── Marker (L2-08): commercial pause or ending, not a journey stage ─────
    marker: Mapped[ExporterMarker] = mapped_column(
        Enum(ExporterMarker, name="exporter_marker_enum", schema=SCHEMA),
        nullable=False,
        server_default=ExporterMarker.NONE.value,
        default=ExporterMarker.NONE,
    )
    #: The current marker's reason; `NULL` exactly when the marker is `NONE`
    #: (`ck_exporter_profile_marker_reason`). Every change, with its reason,
    #: is also in the history log.
    marker_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Journey and qualification gauge (migration 0017) ────────────────────
    #: LEAD -> PROSPECT -> CUSTOMER, forward only, never set by hand
    #: (company-record contract §3.1). Replaced the ten-status
    #: `lifecycle_status`, retired in L2-04 (migration 0020).
    journey: Mapped[ExporterJourney] = mapped_column(
        Enum(ExporterJourney, name="exporter_journey_enum", schema=SCHEMA),
        nullable=False,
        server_default=ExporterJourney.LEAD.value,
        default=ExporterJourney.LEAD,
    )
    #: The qualification gauge's current value; only `QualificationService`
    #: writes it, from a recorded outcome (criterion-result contract §4).
    qualification: Mapped[QualificationState] = mapped_column(
        Enum(QualificationState, name="qualification_state_enum", schema=SCHEMA),
        nullable=False,
        server_default=QualificationState.NOT_YET_REVIEWED.value,
        default=QualificationState.NOT_YET_REVIEWED,
    )

    # ── Conversation gauge (migration 0016) — Developer 3 ───────────────────
    #
    # The two columns below are the only part of this entity Developer 3 owns
    # (`docs/contracts/company-record.md` §2.4, `engagement.md` §2.1). Everything
    # else on this table is Developer 2's, and Developer 2 reviewed 0016 because
    # it adds a column to their table.
    #
    #: How the sales conversation is going. Only `ConversationService` writes it,
    #: and every change writes a `conversation` history row in the same
    #: transaction. **Applies from `PROSPECT` onward** (assumption A4): a `LEAD`
    #: reads `NOT_CONTACTED` because the column is `NOT NULL`, not because anyone
    #: judged it, and the service refuses a move on a `LEAD`.
    conversation: Mapped[ExporterConversation] = mapped_column(
        Enum(ExporterConversation, name="exporter_conversation_enum", schema=SCHEMA),
        nullable=False,
        server_default=ExporterConversation.NOT_CONTACTED.value,
        default=ExporterConversation.NOT_CONTACTED,
    )
    #: When to pick a `NOT_NOW` conversation back up. `NULL` exactly when the
    #: conversation is not `NOT_NOW` (`ck_exporter_profile_conversation_check_back`).
    #: A date, not a timestamp: "check back in the new year" is a day, and a time
    #: of day would be invented precision. Phase 2's Follow-ups list **reads** this
    #: and never writes it — a check-back date moves only through
    #: `ConversationService`.
    conversation_check_back_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Background-check gauge (migration 0015) — Developer 4A ──────────────
    #
    # The one column below is the only part of this entity Developer 4A owns
    # (`docs/contracts/company-record.md` §2.4, `background-check.md` §2). Developer 2
    # reviews it because it is on their table, as they reviewed 0016.
    #
    #: Is it safe and lawful to work with them? Only `BackgroundCheckService` writes it,
    #: together with a locked decision, its evidence snapshot and a `background_check`
    #: history row, in one transaction. There is **no** company-level risk column: risk
    #: is on the decision, and whether it is also carried here is D5, open.
    background_check: Mapped[BackgroundCheckState] = mapped_column(
        Enum(BackgroundCheckState, name="background_check_enum", schema=SCHEMA),
        nullable=False,
        server_default=BackgroundCheckState.NOT_STARTED.value,
        default=BackgroundCheckState.NOT_STARTED,
    )
    #: When the current `CLEAR` stops being current (decision E, one year) — the
    #: current value, carried here like the gauge so a "Re-KYC due" list needs no join.
    #: **Developer 1's one column on this table** (allocation §2.2, F1, migration
    #: `onboarding_0023_dev1_foundation`). `NULL` until plan P3-3a writes it on CLEAR,
    #: clears it on any move away and backfills the companies already CLEAR (BQ-5);
    #: until then `ComplianceFactsReader` derives expiry from the legacy rule (the
    #: clearing decision + one year) and nothing reads this column.
    background_check_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    export_markets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    year_established: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    date_added: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Identity and pipeline (migration 0032, F3 — plan P4-1) ───────────────
    #
    # A company is no longer always an exporter we went looking for: it may exist only
    # because it was somebody's buyer. These five columns are what tell the two apart.

    #: Which registration identifies this company — PAN for an Indian one, a foreign
    #: registration number for the rest. `NULL` on every company created before F3:
    #: the question did not exist then, and guessing from "has a PAN?" would read a
    #: migrated buyer with neither as foreign.
    identity_type: Mapped[CompanyIdentityType | None] = mapped_column(
        Enum(
            CompanyIdentityType,
            name="company_identity_type_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=True,
    )
    #: Whatever the company's own jurisdiction issues, for a company that is not
    #: identified by a PAN. Required on a foreign create path (IQ-7) except for buyers
    #: the migration made, which may have nothing but a name and a country. Unique per
    #: country once normalised — a partial index, because most rows are `NULL`.
    #: Masked like CIN (task 3.8).
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: Whether this company is in the sales pipeline at all (plan P4-2). `NOT NULL`
    #: with a server default, so every existing company reads `IN_PIPELINE` without a
    #: backfill. `ck_exporter_profile_not_in_pipeline_start` holds the implication that
    #: `NOT_IN_PIPELINE` means the journey has not started.
    pipeline_status: Mapped[CompanyPipelineStatus] = mapped_column(
        Enum(
            CompanyPipelineStatus,
            name="company_pipeline_status_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
        server_default=CompanyPipelineStatus.IN_PIPELINE.value,
        default=CompanyPipelineStatus.IN_PIPELINE,
    )

    #: How the record came to exist, as a channel rather than a sales story —
    #: `ExporterSource` mixes "how we found them" with "which channel", and the
    #: creation channel was previously recoverable only from the first history row's
    #: `event_metadata.source` (audit §3.1). Task 3.8 backfills it from there.
    created_via: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The deal whose buyer this company was, when that is why it exists. A real deal
    #: since 0042 (R-17), ``ON DELETE RESTRICT``: deals are never deleted (``WITHDRAWN``
    #: is how one ends), so the company is never lost and the link never dangles.
    created_via_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.deal.id",
            name="fk_exporter_profile_created_via_deal_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    @property
    def gstins(self) -> list[str]:
        """The company's **active** GSTINs as plain strings, in `gstin_rows` order.

        Active only, since task 3.12: a deactivated branch is part of the record but
        not part of the company's current identity, and every caller of this property
        — the duplicate warning, the PAN/GSTIN consistency check, the responses —
        means "the GSTINs this company trades under now". `gstin_rows` is still every
        row, for the screen that shows the history.
        """
        return [row.gstin for row in self.gstin_rows if row.active]

    @property
    def flagged_branch_count(self) -> int:
        """How many active branches compliance has flagged (task 3.14) — what the
        company page's warning chip counts."""
        return sum(1 for row in self.gstin_rows if row.active and row.is_flagged)


__all__ = ["ExporterProfile"]
