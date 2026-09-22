"""EXP-1: Exporter CRM Profile, Contacts, and Activities.

Three new tables in the existing ``onboarding`` schema (this ticket extends
``onboarding`` in place, per the confirmed plan — no new module/schema):

  onboarding.exporter_profile   — one enduring profile per exporter/customer
                                   identity (``customer_id`` unique, not FK'd
                                   to ``onboarding_request`` — a profile may
                                   predate any onboarding journey).
  onboarding.exporter_contact   — contact people for that relationship; at
                                   most one primary contact per customer_id.
  onboarding.exporter_activity  — append-only relationship-history log
                                   (calls, meetings, emails, notes, tasks).

Chains onto ``onboarding_0004_screening_fix``, the onboarding sub-chain's own
current head *in this worktree* (not the repo-wide Alembic head,
``2807a84d72ba``, which already merged ``onboarding_0004_screening_fix`` with
``gateway_0001_baseline`` — see that revision). A sibling ticket (EXP-2) also
chains its own migration onto ``onboarding_0004_screening_fix`` independently
in a parallel worktree, so this revision creates a second fork off that same
parent — the exact situation ``2807a84d72ba`` and
``e849a8d1c41e_merge_al_669_with_develop_heads`` already document precedent
for in this codebase's history. Reconciling the resulting multi-head graph
(a no-op merge revision, once both forks exist in one tree) is out of scope
here.

Design decisions worth stating once, not rediscovered per reviewer:

* ``exporter_profile.source`` is immutable once set. Rather than defining a
  second copy of the write-once trigger function, this migration reuses
  ``onboarding.prevent_field_mutation_when_set`` verbatim (created by
  ``onboarding_0002_orchestration_schema``, still present after
  ``onboarding_0004_screening_fix``'s drop-and-recreate of its *trigger*,
  which never touched the function itself) — the same reuse
  ``onboarding_0003_kyb_vendors`` already established for
  ``kyb_vendor_registration.vendor_id``.

* ``exporter_contact``'s "at most one primary contact per customer_id" rule
  is a partial unique index (``postgresql_where=is_primary_contact = true``),
  not a plain ``UniqueConstraint`` on ``(customer_id, is_primary_contact)`` —
  a plain constraint would also cap *non*-primary contacts at one per
  customer, which is not the rule. Same pattern as
  ``onboarding_request``'s ``uq_onboarding_request_active_customer``.

* ``exporter_activity`` is whole-table append-only via the shared
  ``public.prevent_mutation()`` function, ``FOR EACH STATEMENT`` — the exact
  trigger shape ``onboarding_event`` already uses in this schema
  (``onboarding_0002_orchestration_schema``), not the row-level pattern used
  for column-level immutability elsewhere in this migration.

* ``exporter_profile.raw`` India-specific identifiers (``gstin``/``pan``/
  ``iec``) and CRM free-text fields carry no PII-encryption annotation: unlike
  ``onboarding_request.tax_identification_number``, none of these are treated
  as sensitive-at-rest in the approved plan, so no documented-gap comment is
  needed here (contrast ``verification_result.raw_result`` in the EXP-2
  ticket, which does carry one).

Revision ID: onboarding_0005_exporter_crm
Revises: onboarding_0004_screening_fix
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0005_exporter_crm"
down_revision: str | None = "onboarding_0004_screening_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

# ── Enums ─────────────────────────────────────────────────────────────────────
# Stored labels are the uppercase Python member names, matching every other
# enum in this schema: these models do not pass values_callable, so
# SQLAlchemy persists `.name`.

exporter_source_enum = postgresql.ENUM(
    "MANUAL", "SALES", "REFERRAL", "RXIL", "PARTNER", "API", "BROKER", "EVENT",
    "EXISTING_CUSTOMER",
    name="exporter_source_enum", schema=SCHEMA, create_type=False,
)
exporter_lifecycle_status_enum = postgresql.ENUM(
    "LEAD", "CONTACTED", "DATA_COLLECTION", "VERIFICATION_IN_PROGRESS",
    "COMPLIANCE_REVIEW", "ONBOARDED", "FINANCING_ELIGIBLE", "ACTIVE",
    "SUSPENDED", "OFFBOARDED",
    name="exporter_lifecycle_status_enum", schema=SCHEMA, create_type=False,
)
exporter_activity_type_enum = postgresql.ENUM(
    "CALL", "MEETING", "EMAIL", "NOTE", "TASK", "FOLLOW_UP",
    name="exporter_activity_type_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    exporter_source_enum,
    exporter_lifecycle_status_enum,
    exporter_activity_type_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    for e in _ENUMS:
        e.create(bind, checkfirst=False)

    # ── exporter_profile ───────────────────────────────────────────────────
    op.create_table(
        "exporter_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("iec", sa.String(length=10), nullable=True),
        sa.Column("source", exporter_source_enum, nullable=False),
        sa.Column("relationship_manager", sa.String(length=255), nullable=True),
        sa.Column("lifecycle_status", exporter_lifecycle_status_enum, nullable=False),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("export_markets", postgresql.JSONB(), nullable=True),
        sa.Column("products", postgresql.JSONB(), nullable=True),
        sa.Column("year_established", sa.Integer(), nullable=True),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column(
            "date_added", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exporter_profile"),
        sa.UniqueConstraint("customer_id", name="uq_exporter_profile_customer_id"),
        schema=SCHEMA,
    )

    # ── exporter_contact ───────────────────────────────────────────────────
    op.create_table(
        "exporter_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column(
            "is_primary_contact", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exporter_contact"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_contact_customer_id", "exporter_contact", ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "uq_exporter_contact_primary_per_customer",
        "exporter_contact",
        ["customer_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_primary_contact = true"),
    )

    # ── exporter_activity (append-only) ────────────────────────────────────
    op.create_table(
        "exporter_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", exporter_activity_type_enum, nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_exporter_activity"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_activity_customer_id", "exporter_activity", ["customer_id"], schema=SCHEMA
    )

    # ── Triggers ─────────────────────────────────────────────────────────────

    # source is immutable once set — reuses onboarding.prevent_field_mutation_when_set,
    # defined by onboarding_0002_orchestration_schema and still present.
    op.execute(f"""
    CREATE TRIGGER trg_exporter_profile_source_immutability
    BEFORE UPDATE ON {SCHEMA}.exporter_profile
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('source');
    """)

    # exporter_activity is fully append-only, same shape as
    # trg_onboarding_event_append_only (FOR EACH STATEMENT, shared function).
    op.execute(f"""
    CREATE TRIGGER trg_exporter_activity_append_only
    BEFORE UPDATE OR DELETE ON {SCHEMA}.exporter_activity
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.prevent_mutation();
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_exporter_activity_append_only "
        f"ON {SCHEMA}.exporter_activity;"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_exporter_profile_source_immutability "
        f"ON {SCHEMA}.exporter_profile;"
    )

    op.drop_table("exporter_activity", schema=SCHEMA)
    op.drop_table("exporter_contact", schema=SCHEMA)
    op.drop_table("exporter_profile", schema=SCHEMA)

    bind = op.get_bind()
    for e in reversed(_ENUMS):
        e.drop(bind, checkfirst=False)
