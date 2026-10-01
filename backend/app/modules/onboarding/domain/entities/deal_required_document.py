"""``DealRequiredDocument`` — which paperwork a deal must have before it may be
handed over — **owner: Developer 2** (plan P2-5a, migration 0027).

Contract: ``docs/contracts/deal-and-buyer.md`` §6.1 condition 3. Answers R7
("verify each deal with evidence before handover") together with the evidence
pinned to each compliance check.

**Versioned, append-only — the same shape as ``qualification_criterion``.** A
requirement is never edited or deleted: adding one writes version *n+1* with
``active=True``, removing one writes version *n+1* with ``active=False``. The
current rule is the highest version per key, and the whole history of what was
required when is still readable — which is the point, because a deal handed over
last month was judged against the rule as it stood then.

**The key is ``(category, document_type)``.** ``document_type`` is ``''`` for "any
document in this category", which is what the seeded ``PRE_SHIPMENT`` requirement
uses: a proforma invoice, a purchase order, a sales contract or a letter of credit
all satisfy it (architecture §3.4's PRE_SHIPMENT types). A sentinel rather than
``NULL`` so ``uq_deal_required_document_key_version`` is a plain unique constraint
— in Postgres two rows with a ``NULL`` ``document_type`` would not collide, so a
nullable column would let the same requirement be added twice at one version. The
API maps ``''`` to ``null`` in both directions, so no caller sees the sentinel.

**Not the legacy ``document_requirements_service.py``.** That policy serves the
``onboarding_request`` state machine (assumption A6, not built on) and knows
nothing about deals.

**A category a deal cannot hold is refused by the service**, not by a check
constraint: which owner a category belongs to is ``DocumentCategory.owner_kind``,
a rule that never varies per row, and copying its table into SQL would give it a
second home to go stale in.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.document_enums import DocumentCategory
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"

#: ``document_type`` for "any document in this category".
ANY_DOCUMENT_TYPE = ""


class DealRequiredDocument(AppendOnlyModel):
    """One version of one requirement. Immutable once written."""

    __tablename__ = "deal_required_document"
    __table_args__ = (
        UniqueConstraint(
            "category",
            "document_type",
            "version",
            name="uq_deal_required_document_key_version",
        ),
        # `''` means "any type"; anything else must be a real type name, never
        # whitespace that only looks like one.
        CheckConstraint(
            "document_type = '' OR btrim(document_type) = document_type",
            name="ck_deal_required_document_type_clean",
        ),
        CheckConstraint("version >= 1", name="ck_deal_required_document_version"),
        {"schema": SCHEMA},
    )

    category: Mapped[DocumentCategory] = mapped_column(
        Enum(
            DocumentCategory,
            name="crm_document_category_enum",
            schema=SCHEMA,
            # Created by migration 0019; this table reuses it rather than
            # declaring a second list of the same ten values.
            create_type=False,
        ),
        nullable=False,
    )
    #: A seeded settings value (architecture §3.4), so a plain string — and
    #: ``''`` for "any type in the category". See the module docstring.
    document_type: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default=ANY_DOCUMENT_TYPE
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Whether this version requires the document or stops requiring it. A removal
    #: is a new version with ``False``, never a delete.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # ── Provenance on every new table (plan BQ-7) ────────────────────────────
    #: Who wrote this version, from the session. ``NULL`` for the seeded v1.
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: How it arrived: ``settings_api`` for the route, ``migration_0027_seed`` for
    #: the seed.
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    #: What it came from, when that means anything — ``NULL`` for a hand-made
    #: change, which is every change today.
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["ANY_DOCUMENT_TYPE", "DealRequiredDocument"]
