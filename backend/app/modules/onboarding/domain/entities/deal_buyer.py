"""``DealBuyer`` — who the exporter is selling to on one deal.

Contract: ``docs/contracts/deal-and-buyer.md`` §3. Architecture §3.3, §3.5,
decision 9, migration 0018.

**Its own table, not columns on ``deal``.** Buyer checks attach to
*the buyer*: a verification result needs something with an id to point
at, and an ``entity_reference`` pointing at the deal would make "a check about the
buyer" and "a check about the deal" indistinguishable. A separate row gives the
buyer its own identity without pretending it is a company — it is not in
``exporter_profile``, it has no journey, and it is never screened as if it were a
client.

**One buyer per deal**, enforced by a unique constraint on ``deal_id``. A deal
with two buyers is two deals: financing one shipment for two buyers is not
something the prototype models, and a list where "the buyer" is ambiguous would
make the handover payload ambiguous too (architecture §3.6).

The buyer's problems stay here. A buyer failing a check is recorded against this
row; the company's record is unchanged (architecture §3.5).

Which company the buyer turned out to be
----------------------------------------
Buyers are companies now (``deal.buyer_company_id``), and the buyer migration
(``migrate_deal_buyers``) works out which company each legacy row was. It writes the
answer **and how it was decided** onto the row itself: ``mapped_company_id``,
``match_rule``, ``matched_by``, ``matched_at`` and ``mapping_run_id``.

``deal.buyer_company_id`` says which company a deal's buyer is. It cannot say *how we
decided*, and that is the part people will question: a machine matching a PAN and a
person agreeing that two similarly-named rows were one company are different claims.
Several rows mapping to one company is the merge, and it is deliberately **logical**:
no company-to-company merge is performed, so the rows stay.

The five columns are **set once** (``trg_deal_buyer_mapping_set_once``, migration
0056): a mapping is never changed, which is also what makes a re-run a no-op, because
the command skips a row whose ``mapped_company_id`` is set. They are filled together or
not at all (``ck_deal_buyer_mapping_complete``), apart from ``matched_by``, which an
automated run may leave empty. Until 0056 they lived in a separate one-to-one table,
``deal_buyer_company_map``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.entities.database_generated_id import DatabaseGeneratedId
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.deal import Deal

SCHEMA = "onboarding"


class BuyerMatchRule(str, enum.Enum):
    """Which identity-resolution step decided a buyer's mapping.

    The order is the order they are tried, and it is the order of confidence:
    a hard identifier first, a registration number next, a human last.
    """

    #: An Indian buyer whose `tax_id` is a PAN or GSTIN, matched to a company holding
    #: that PAN. The case that matters most: it may well be an existing *seller*.
    PAN = "PAN"
    #: A foreign buyer matched on `(country, normalised registration number)`, either
    #: to another deal buyer or to an existing company.
    REGISTRATION_NUMBER = "REGISTRATION_NUMBER"
    #: No identifier matched and no other buyer shares this identity: a new company.
    NEW = "NEW"
    #: Same `(country, normalised name)` with no identifier, **confirmed by a person**
    #: in the dry-run report. Never automatic. Also the rule a person's choice between
    #: conflicting candidates is recorded under: either way the record says a human
    #: decided, not a rule.
    NAME_CONFIRMED = "NAME_CONFIRMED"
    #: The row was already linked to this company before the migration ran — its deal
    #: names it or its BUYER results already have it as their subject — and nothing on
    #: the legacy row contradicts it (migration 0041). Both links are set once, so the
    #: legacy row can map nowhere else.
    ALREADY_LINKED = "ALREADY_LINKED"


class DealBuyer(DatabaseGeneratedId, AnerModel):
    __tablename__ = "deal_buyer"
    __table_args__ = (
        UniqueConstraint("deal_id", name="uq_deal_buyer_deal_id"),
        # Two letters, uppercase: ISO-3166-1 alpha-2, the same rule
        # `exporter_profile.country` uses, so one country is not stored three ways.
        CheckConstraint(
            "country ~ '^[A-Z]{2}$'",
            name="ck_deal_buyer_country_iso",
        ),
        # A mapping is written whole: the company, the rule that chose it, when, and
        # the run, so "what did run X do" always finds it.
        CheckConstraint(
            "(mapped_company_id IS NULL) = (match_rule IS NULL) "
            "AND (mapped_company_id IS NULL) = (matched_at IS NULL) "
            "AND (mapped_company_id IS NULL) = (mapping_run_id IS NULL)",
            name="ck_deal_buyer_mapping_complete",
        ),
        # Which deal buyers became one company: the merge, read in the useful
        # direction, and what the validation queries count.
        Index("ix_deal_buyer_mapped_company", "mapped_company_id"),
        # Everything one run did.
        Index("ix_deal_buyer_mapping_run", "mapping_run_id"),
        {"schema": SCHEMA},
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.deal.id",
            name="fk_deal_buyer_deal_id",
            # CASCADE, unlike the deal's own FK to the company: a buyer has no
            # meaning without its deal, and a deal is never deleted anyway
            # (`WITHDRAWN` is how one ends), so this only matters if a test or a
            # future cleanup removes a deal outright.
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    #: Whatever the buyer's own jurisdiction issues — not validated by shape,
    #: because a buyer is foreign by definition and India's PAN/GSTIN rules do
    #: not apply to it.
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── The buyer migration's answer: set once, all together ─────────────────
    mapped_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_deal_buyer_mapped_company",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    match_rule: Mapped[BuyerMatchRule | None] = mapped_column(
        Enum(
            BuyerMatchRule,
            name="buyer_match_rule_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=True,
    )
    #: Who ran it. A person for an `--apply`, a label for an automated run.
    matched_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The run that wrote the mapping: what "what did run X do" reads.
    mapping_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    deal: Mapped[Deal] = relationship(back_populates="buyer")
