"""``DealBuyerCompanyMap`` — which company each legacy deal buyer turned out to be.

One row per ``deal_buyer``, written by the buyer migration. It is the migration's
**record of its own reasoning**, and it is why the migration is re-runnable: a
second run finds the mapping already there and creates nothing.

Why a table and not just ``deal.buyer_company_id``
--------------------------------------------------
``deal.buyer_company_id`` says which company a deal's buyer is. It cannot say *how
we decided*, and for this migration that is the part people will question. Several
``deal_buyer`` rows map to one company — that is the merge, and it is deliberately
**logical**: no company-to-company merge is performed (§17.2), so the rows stay and
the map records that they were the same company all along.

``match_rule`` is the reason in one word: which of §17.2's identity-resolution steps
produced this row. A row created on a human's confirmation of a name-only duplicate
is marked as such, because six months later "the machine matched these" and "a
person agreed to merge these" are different claims about the same data.

Append-only
-----------
``trg_deal_buyer_company_map_append_only`` refuses ``UPDATE`` and ``DELETE``. A
mapping that turns out to be wrong is corrected by rolling the run back (§17.2's
logical rollback) and running again — not by editing the record of what the last run
decided.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class BuyerMatchRule(str, enum.Enum):
    """Which of §17.2's identity-resolution steps decided this mapping.

    The order is the order they are tried, and it is the order of confidence:
    a hard identifier first, a registration number next, a human last.
    """

    #: Step 2 — an Indian buyer whose `tax_id` is a PAN or GSTIN, matched to a company
    #: holding that PAN. The case that matters most: it may well be an existing *seller*.
    PAN = "PAN"
    #: Step 3 — a foreign buyer matched on `(country, normalised registration number)`,
    #: either to another deal buyer or to an existing company.
    REGISTRATION_NUMBER = "REGISTRATION_NUMBER"
    #: Steps 2–3 found nothing and no other buyer shares this identity: a new company.
    NEW = "NEW"
    #: Step 4 — same `(country, normalised name)` with no identifier, **confirmed by a
    #: person** in the dry-run report. Never automatic. Also the rule a
    #: person's choice between conflicting candidates is recorded under: either way the
    #: record says a human decided, not a rule.
    NAME_CONFIRMED = "NAME_CONFIRMED"
    #: The row was already linked to this company before the migration ran — its deal
    #: names it or its BUYER results already have it as their subject
    #: — and nothing on the legacy row contradicts it (migration 0041). Both
    #: links are set once, so the legacy row can map nowhere else.
    ALREADY_LINKED = "ALREADY_LINKED"


class DealBuyerCompanyMap(AppendOnlyModel):
    __tablename__ = "deal_buyer_company_map"
    __table_args__ = (
        # Which deal buyers became one company — the merge, read in the useful
        # direction, and what the validation queries count.
        Index("ix_deal_buyer_company_map_company", "company_id"),
        # Everything one run did, for §17.2's logical rollback.
        Index("ix_deal_buyer_company_map_run", "run_id"),
        {"schema": SCHEMA},
    )

    #: The legacy row this mapping is about. **The primary key**: one mapping per deal
    #: buyer, forever, which is what makes a re-run a no-op rather than a second
    #: company.
    deal_buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.deal_buyer.id",
            name="fk_deal_buyer_company_map_deal_buyer",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_deal_buyer_company_map_company",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    match_rule: Mapped[BuyerMatchRule] = mapped_column(
        Enum(
            BuyerMatchRule,
            name="buyer_match_rule_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
    )
    #: Who ran it. A person for an `--apply`, a label for an automated run.
    matched_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: The run that wrote this row. Required, because §17.2's rollback is "undo this
    #: run" and a row with no run cannot be undone.
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)


__all__ = ["BuyerMatchRule", "DealBuyerCompanyMap"]
