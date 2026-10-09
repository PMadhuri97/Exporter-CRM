"""``PaymentTerm`` — one version of a payment term administrators keep in Settings.

A term is its ``code``; each edit or retirement writes a new version and marks the old
one superseded (``is_current`` false), so a deal and a company default keep pointing at
the exact wording they were agreed on. ``active`` false on the current version means the
term is retired: still readable on old deals, no longer offered.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

KINDS = ("ADVANCE", "LC_SIGHT", "LC_USANCE", "DP", "DA", "OPEN_ACCOUNT")
#: The kinds that run for a number of days, which they must state.
DAYS_KINDS = frozenset({"LC_USANCE", "DA", "OPEN_ACCOUNT"})


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in sorted(values)) + ")"


class PaymentTerm(AnerModel):
    __tablename__ = "payment_term"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_payment_term_code_version"),
        Index(
            "uq_payment_term_current_code",
            "code",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint(_in("kind", KINDS), name="ck_payment_term_kind"),
        CheckConstraint(
            f"(({_in('kind', DAYS_KINDS)}) AND days IS NOT NULL AND days > 0) "
            f"OR (NOT ({_in('kind', DAYS_KINDS)}) AND days IS NULL)",
            name="ck_payment_term_days",
        ),
        CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_payment_term_code"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["DAYS_KINDS", "KINDS", "PaymentTerm"]
