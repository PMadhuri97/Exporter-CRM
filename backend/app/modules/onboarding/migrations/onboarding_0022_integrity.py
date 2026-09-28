"""Database guards for documents, verification results and closed deals — the
integrity rules the services already keep, made true for every writer.

Revision ID: onboarding_0022_integrity
Revises: onboarding_0021_verif_review

``onboarding_0022_integrity`` is 25 characters, inside the register's 32-character
limit on ``alembic_version.version_num``.

Why
---
The final release audit (29 September 2026) tried each rule in raw SQL. The services
never break them, but the database let a writer that bypasses the services do so:

* a ``crm_document`` row could be deleted, or re-pointed at another file, owner or
  type — although documents are kept (seven-year retention, architecture §7.6) and a
  background-check decision may have pinned one as evidence;
* a ``verification_result`` could be deleted while nothing yet referenced it — while
  every other record a compliance decision rests on is append-only;
* a ``HANDED_OVER`` or ``WITHDRAWN`` deal could be moved again, although both stages
  are terminal and a handover is what the lending team was given.

What it adds, all in the ``onboarding`` schema
-----------------------------------------------
* ``trg_crm_document_identity_immutability`` → ``prevent_field_mutation_when_set()``
  on what a document *is*: its owner, category, type, source, name, content type,
  size, uploader, upload time and storage key. ``scan_status`` and ``scanner_name``
  stay writable — a real scanner reports after the upload.
* ``trg_crm_document_no_delete`` and ``trg_verification_result_no_delete`` →
  ``public.prevent_mutation()`` on ``DELETE``. Updates keep their own rules
  (0021's outcome freeze and input immutability on results).
* ``prevent_terminal_deal_change()`` and ``trg_deal_terminal_freeze``: once a deal's
  stage is ``HANDED_OVER`` or ``WITHDRAWN``, its stage, handover time, withdrawal
  reason, company and reference no longer change. A deal on its way to a terminal
  stage is unaffected.

Every rule has a direct-SQL test in ``test_crm_integrity_guards_0022.py``.

Downgrade drops the three triggers and the function; no data changes either way.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0022_integrity"
down_revision: str | None = "onboarding_0021_verif_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: What a document is. Everything but the scan verdict, which arrives later.
DOCUMENT_IDENTITY = (
    "company_id",
    "deal_id",
    "category",
    "document_type",
    "source",
    "file_name",
    "content_type",
    "size_bytes",
    "uploaded_by",
    "uploaded_at",
    "storage_key",
)


def upgrade() -> None:
    columns = ", ".join(f"'{column}'" for column in DOCUMENT_IDENTITY)
    op.execute(
        f"""
        CREATE TRIGGER trg_crm_document_identity_immutability
        BEFORE UPDATE ON {SCHEMA}.crm_document
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set({columns});
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_crm_document_no_delete
        BEFORE DELETE ON {SCHEMA}.crm_document
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_verification_result_no_delete
        BEFORE DELETE ON {SCHEMA}.verification_result
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_terminal_deal_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
               AND (NEW.stage IS DISTINCT FROM OLD.stage
                    OR NEW.handed_over_at IS DISTINCT FROM OLD.handed_over_at
                    OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
                    OR NEW.company_id IS DISTINCT FROM OLD.company_id
                    OR NEW.reference IS DISTINCT FROM OLD.reference)
            THEN
                RAISE EXCEPTION
                    'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_terminal_freeze
        BEFORE UPDATE ON {SCHEMA}.deal
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_terminal_deal_change();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_deal_terminal_freeze ON {SCHEMA}.deal;")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_terminal_deal_change();")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_verification_result_no_delete "
        f"ON {SCHEMA}.verification_result;"
    )
    op.execute(f"DROP TRIGGER IF EXISTS trg_crm_document_no_delete ON {SCHEMA}.crm_document;")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_crm_document_identity_immutability "
        f"ON {SCHEMA}.crm_document;"
    )
