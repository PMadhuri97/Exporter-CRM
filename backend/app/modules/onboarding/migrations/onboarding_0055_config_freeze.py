"""An old version of a payment term or a sanctions list never changes.

Revision ID: onboarding_0055_config_freeze
Revises: onboarding_0054_integrity_fks

Why
---
A deal keeps the payment term it was agreed on (``deal.payment_term_id``), and a
sanctions run keeps the list versions it screened (``sanctions_run_list.list_id``).
Both tables are versioned for exactly that reason: every change through settings writes
the next version and only flips the old row's ``is_current`` to false
(``PaymentTermService.revise``, ``SanctionsListService.revise``). But nothing stopped a
direct ``UPDATE`` from rewriting an old version in place, and with it what every deal
or run that used it appears to have used.

``qualification_criterion`` and ``deal_required_document`` already cannot change —
they are fully append-only. These two keep a mutable ``is_current`` flag, so they get
the column-level freeze ``exporter_profile.source`` and ``trade_invoice`` use:
``prevent_field_mutation_when_set`` on every column except ``is_current`` and
``updated_at``. ``active`` is frozen too: retiring a term or a list writes a new
version.

The function allows ``NULL`` → a value once (``database.md`` trap 8), so a nullable
column (``days``, ``authority``, ``created_by``) left empty on an old version could
still be filled in once. Nothing does that.

Data
----
None.

Rollback
--------
The downgrade drops both triggers.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0055_config_freeze"
down_revision: str | None = "onboarding_0054_integrity_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: (table, trigger, the columns fixed once written)
FREEZES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "payment_term",
        "trg_payment_term_version_immutability",
        ("code", "version", "label", "kind", "days", "active", "created_by", "created_at"),
    ),
    (
        "sanctions_list",
        "trg_sanctions_list_version_immutability",
        (
            "code",
            "version",
            "name",
            "authority",
            "active",
            "mandatory",
            "list_version_date",
            "created_by",
            "created_at",
        ),
    ),
)


def upgrade() -> None:
    for table, trigger, columns in FREEZES:
        arguments = ", ".join(f"'{column}'" for column in columns)
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE ON {SCHEMA}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set({arguments});
            """
        )


def downgrade() -> None:
    for table, trigger, _columns in reversed(FREEZES):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {SCHEMA}.{table}")
