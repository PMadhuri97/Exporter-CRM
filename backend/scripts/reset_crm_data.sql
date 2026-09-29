-- Reset the Exporter CRM's data, keeping the schema and the seeded settings.
--
-- For a development database that has collected test rows (19,000+ companies at the
-- time of writing) and needs to be empty enough to demo or test against. It does NOT
-- drop or recreate anything: the schema, the migration history and the reference data
-- an administrator did not create all survive.
--
--   docker exec -i aner-postgres psql -U aner -d aner_settlement -v ON_ERROR_STOP=1 \
--       < backend/scripts/reset_crm_data.sql
--
-- ── Why TRUNCATE and not DELETE ──────────────────────────────────────────────
--
-- Nineteen tables here carry `public.prevent_mutation()`, declared
-- `BEFORE DELETE OR UPDATE ... FOR EACH STATEMENT`. They are append-only by design:
-- a history row, a decision, a completion record is evidence, and the database
-- refuses to let any code edit or remove one. A `DELETE` is rejected outright.
--
-- `TRUNCATE` fires only `TRUNCATE` triggers, and none is declared, so it passes. That
-- is the intended escape hatch for a maintenance reset, not a way around the rule:
-- nothing in the application can reach it.
--
-- `CASCADE` handles the foreign keys, of which several are `ON DELETE RESTRICT`
-- precisely so that evidence cannot vanish from under a decision. Listing the tables
-- in one statement also means order does not matter.
--
-- ── What is kept ─────────────────────────────────────────────────────────────
--
--   * the schema, and `alembic_version` — no migration is re-run;
--   * `qualification_reason_code` — all nine are the migration's seed;
--   * `qualification_criterion` rows with `created_by IS NULL` — the seven the
--     migration seeded. Criteria a test or an administrator created are removed.
--
-- ── What is removed ──────────────────────────────────────────────────────────
--
-- Every company, contact, activity, deal, buyer, document, qualification result and
-- outcome, conversation and follow-up record, background-check decision and its
-- evidence, verification result, screening answer, and the whole history log.
--
-- Section 2 (user accounts) is separate and commented out. Read it before running.

\timing on

BEGIN;

-- ── 1. CRM data ──────────────────────────────────────────────────────────────
-- One statement: `TRUNCATE` takes a table list, so the foreign keys between these
-- are satisfied whatever order they are written in.

TRUNCATE TABLE
    -- The company and everything hanging off it
    onboarding.exporter_profile,
    onboarding.exporter_contact,
    onboarding.exporter_gstin,
    onboarding.exporter_activity,
    onboarding.follow_up_completion,
    onboarding.exporter_lifecycle_history,

    -- Qualification (the criteria themselves are handled in section 1b)
    onboarding.qualification_result,
    onboarding.qualification_outcome,

    -- Deals and their buyers
    onboarding.deal,
    onboarding.deal_buyer,

    -- Documents. The storage keys they point at are files on disk; see the note
    -- at the foot of this script.
    onboarding.crm_document,

    -- The background check: decisions and the evidence each was pinned to
    onboarding.background_check_decision,
    onboarding.background_check_evidence,

    -- Its inputs, owned by the verification side
    onboarding.verification_result,
    onboarding.screening_review_item,
    onboarding.bank_activity_finding,

    -- The legacy onboarding path and the case engine. Not part of the CRM story,
    -- but test runs leave rows here too and they reference the same companies.
    onboarding.onboarding_request,
    onboarding.onboarding_document,
    onboarding.onboarding_event,
    onboarding.onboarding_verifications,
    onboarding.onboarding_case,
    onboarding.onboarding_customers,
    onboarding.onboarding_applicant_mappings,
    onboarding.onboarding_webhook_events,
    onboarding.case_state_transition,
    onboarding.kyc_case,
    onboarding.person_profile,
    onboarding.ubo_record,
    onboarding.kyb_vendor_registration,
    onboarding.kyb_vendor_result
RESTART IDENTITY CASCADE;

-- ── 1b. Qualification criteria ───────────────────────────────────────────────
-- Not truncated: the seven rows migration `onboarding_0017_qualification` seeded
-- have `created_by IS NULL`, and losing them would leave qualification with nothing
-- to score against. Only rows someone created are removed.
--
-- The append-only trigger has to be lifted for this one statement, because a
-- selective delete is exactly what it forbids. It is restored immediately, inside
-- the same transaction, so a failure anywhere leaves the table protected.

ALTER TABLE onboarding.qualification_criterion DISABLE TRIGGER trg_qualification_criterion_append_only;

DELETE FROM onboarding.qualification_criterion WHERE created_by IS NOT NULL;

ALTER TABLE onboarding.qualification_criterion ENABLE TRIGGER trg_qualification_criterion_append_only;

-- `qualification_reason_code` is untouched: all nine rows are the migration's seed
-- and nothing creates more.

COMMIT;

-- ── 2. User accounts — OPTIONAL, read before uncommenting ────────────────────
--
-- Removes **every** account, including the one you are signed in with. Uncomment
-- only if you intend to recreate the accounts afterwards:
--
--   docker exec -e FIRST_ADMIN_EMAIL=admin@aner.example \
--               -e FIRST_ADMIN_PASSWORD=... \
--               -e FIRST_COMPLIANCE_EMAIL=compliance@aner.example \
--               -e FIRST_COMPLIANCE_PASSWORD=... \
--               aner-app python -m app.platform.authentication.cli bootstrap
--
-- then register operations@ and developer@ and promote them.
--
-- `auth.roles` and `auth.permissions` are left alone: the five built-in roles and
-- the permission catalogue are seeded by migration `auth_0004_rbac`, not by a user.
--
-- BEGIN;
-- TRUNCATE TABLE auth.users, auth.refresh_tokens RESTART IDENTITY CASCADE;
-- COMMIT;

-- ── 3. Afterwards ────────────────────────────────────────────────────────────
--
-- Check what is left:
--
--   SELECT 'companies', count(*) FROM onboarding.exporter_profile
--   UNION ALL SELECT 'deals', count(*) FROM onboarding.deal
--   UNION ALL SELECT 'documents', count(*) FROM onboarding.crm_document
--   UNION ALL SELECT 'history', count(*) FROM onboarding.exporter_lifecycle_history
--   UNION ALL SELECT 'criteria (kept)', count(*) FROM onboarding.qualification_criterion;
--
-- Expected: 0, 0, 0, 0, 7.
--
-- **Uploaded files are not touched.** Document rows are gone but the files they
-- pointed at remain under `backend/.local-storage/`. They are unreachable — nothing
-- records their keys any more — so they are harmless, and the directory can be
-- emptied by hand if you want the disk back.
--
-- **This does not fix a stale migration.** If the schema itself is behind the
-- migration files — for example a `CHECK` constraint added to a revision the
-- database already applied — only `alembic downgrade base && alembic upgrade head`
-- will pick it up. This script resets rows, not structure.
