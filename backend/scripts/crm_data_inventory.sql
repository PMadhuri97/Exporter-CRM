-- CRM data inventory — read-only.
--
-- Sizes the buyer and GST-branch migrations with facts instead of assumptions. Run it against
-- **every live database** and attach the output to the migration tickets; each
-- migration then states which environments it must run on.
--
--   docker exec -i aner-postgres psql -U aner -d <database> < backend/scripts/crm_data_inventory.sql
--
-- Or, for an environment outside Docker:
--
--   psql "$DATABASE_URL" -f backend/scripts/crm_data_inventory.sql
--
-- ── This reads and nothing else ──────────────────────────────────────────────
--
-- Every statement is a SELECT. There is no transaction, no temporary table and no
-- SET, so it is safe to run against production-like data and safe to interrupt.
--
-- ── Where to run it ──────────────────────────────────────────────────────────
--
-- The known environments are `crm_uat_walk`, `crm_release_audit`, the demo database
-- and the shared test database.
--
-- **Do not attach numbers from a development database.** The local one carries sample
-- data and whatever the test suite last left behind — it has been emptied and
-- repopulated more than once — so its counts say nothing about what a migration will
-- meet in an environment that matters. Running it locally is how you check the SQL
-- parses; running it on the environments above is the task.
--
-- ── What each answer is for ──────────────────────────────────────────────────
--
--   1  How big is the buyer migration, and how many buyers look like Indian
--      companies we could match to an existing record rather than create new.
--   2  How many BUYER verification results must survive being re-pointed when the
--      buyer becomes a company.
--   3  GSTINs held by more than one company — these warn rather than
--      block, so this is the size of the warning, not of a blocker.
--   4  PAN-less companies that hold GSTINs: candidates for deriving a PAN (explicitly
--      "only if the report shows it is worth doing").
--   5  CLEAR companies and when they were cleared — the input to re-KYC cycles and
--      Clear expiry.
--   6  Screening rows on `website-reviewed`, retired from the checklist by migration
--      0025 (eight-item decisions keep reading it), and the retired website field.
--   7  Documents per category on deals — the size of the per-deal evidence rule.

\echo ''
\echo '================================================================'
\echo ' CRM data inventory'
\echo '================================================================'
SELECT current_database() AS database, now() AS taken_at;

-- ── 1. Deal buyers ───────────────────────────────────────────────────────────
-- `tax_id` is free text today. The shapes below are the regexes the CRM already
-- enforces elsewhere (`domain/tax_identifiers.py`), so "looks like a PAN" here
-- means "would pass validation if we moved it onto a company record".

\echo ''
\echo '-- 1a. Deal buyers: how many, and how many carry an identifier -----------'
SELECT
    count(*)                                                      AS buyers,
    count(*) FILTER (WHERE tax_id IS NOT NULL)                    AS with_tax_id,
    count(*) FILTER (WHERE registration_number IS NOT NULL)       AS with_registration_number,
    count(*) FILTER (WHERE tax_id ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')    AS tax_id_shaped_like_pan,
    count(*) FILTER (
        WHERE tax_id ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'
    )                                                             AS tax_id_shaped_like_gstin,
    count(DISTINCT lower(btrim(name)))                            AS distinct_names
FROM onboarding.deal_buyer;

\echo ''
\echo '-- 1b. Deal buyers per country -------------------------------------------'
SELECT country, count(*) AS buyers
FROM onboarding.deal_buyer
GROUP BY country
ORDER BY buyers DESC, country;

\echo ''
\echo '-- 1c. Buyer names used on more than one deal ----------------------------'
\echo '--     (name-only duplicates; Compliance reviews these before the buyer migration)'
SELECT lower(btrim(name)) AS normalised_name, count(*) AS deals
FROM onboarding.deal_buyer
GROUP BY 1
HAVING count(*) > 1
ORDER BY deals DESC, normalised_name
LIMIT 50;

-- ── 2. BUYER verification results ────────────────────────────────────────────

\echo ''
\echo '-- 2. Verification results whose subject is a buyer ----------------------'
SELECT
    status,
    count(*) AS results,
    count(DISTINCT entity_reference) AS distinct_buyers
FROM onboarding.verification_result
WHERE entity_type = 'BUYER'
GROUP BY status
ORDER BY results DESC;

-- ── 3. GSTINs held by more than one company ──────────────────────────────────

\echo ''
\echo '-- 3. GSTINs on more than one company (warn, never block) ---------------'
SELECT gstin, count(DISTINCT customer_id) AS companies
FROM onboarding.exporter_gstin
GROUP BY gstin
HAVING count(DISTINCT customer_id) > 1
ORDER BY companies DESC, gstin
LIMIT 50;

-- ── 4. Companies with no PAN that hold GSTINs ────────────────────────────────
-- A GSTIN embeds its holder's PAN at characters 3-12, so a PAN can be derived.
-- Whether that is worth doing is decided from this count.

\echo ''
\echo '-- 4. PAN-less companies holding at least one GSTIN ----------------------'
SELECT
    count(*) AS companies_without_pan_but_with_gstin,
    count(*) FILTER (
        WHERE substring(first_gstin FROM 3 FOR 10) ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
    )        AS pan_derivable_from_gstin
FROM (
    SELECT p.customer_id, min(g.gstin) AS first_gstin
    FROM onboarding.exporter_profile p
    JOIN onboarding.exporter_gstin g ON g.customer_id = p.customer_id
    WHERE p.pan IS NULL
    GROUP BY p.customer_id
) AS pan_less;

-- ── 5. CLEAR companies and when they were cleared ────────────────────────────
-- The chain head is the decision nothing supersedes. Age is computed from the
-- decision date rather than `expires_at` (`onboarding_0027_clear_expiry`), so
-- this also runs on a database that has not reached that revision.

\echo ''
\echo '-- 5. Companies currently CLEAR, by age of the clearing decision ---------'
SELECT
    count(*)                                                           AS clear_companies,
    min(d.decided_at)                                                  AS oldest_clearance,
    max(d.decided_at)                                                  AS newest_clearance,
    count(*) FILTER (WHERE d.decided_at < now() - interval '1 year')   AS cleared_over_a_year_ago
FROM onboarding.exporter_profile p
JOIN onboarding.background_check_decision d
  ON d.company_id = p.customer_id
 AND d.to_value = 'CLEAR'
 AND NOT EXISTS (
     SELECT 1 FROM onboarding.background_check_decision later
     WHERE later.supersedes_decision_id = d.id
 )
WHERE p.background_check = 'CLEAR';

\echo ''
\echo '-- 5b. Risk ratings on those clearing decisions --------------------------'
SELECT d.risk_rating, count(*) AS companies
FROM onboarding.exporter_profile p
JOIN onboarding.background_check_decision d
  ON d.company_id = p.customer_id
 AND d.to_value = 'CLEAR'
 AND NOT EXISTS (
     SELECT 1 FROM onboarding.background_check_decision later
     WHERE later.supersedes_decision_id = d.id
 )
WHERE p.background_check = 'CLEAR'
GROUP BY d.risk_rating
ORDER BY companies DESC;

-- ── 6. The website screening item ────────────────────────────────────────────

\echo ''
\echo '-- 6. Screening rows on website-reviewed (retired in 0025) ---------------'
SELECT status, count(*) AS rows_recorded
FROM onboarding.screening_review_item
WHERE item_key = 'website-reviewed'
GROUP BY status
ORDER BY rows_recorded DESC;

\echo ''
\echo '-- 6b. Companies with a website recorded (the retired field) -------------'
SELECT
    count(*)                                        AS companies,
    count(*) FILTER (WHERE website IS NOT NULL)     AS with_website
FROM onboarding.exporter_profile;

-- ── 7. Documents on deals ────────────────────────────────────────────────────

\echo ''
\echo '-- 7. Deal documents per category and scan status ------------------------'
SELECT category, scan_status, count(*) AS documents
FROM onboarding.crm_document
WHERE deal_id IS NOT NULL
GROUP BY category, scan_status
ORDER BY documents DESC;

\echo ''
\echo '-- 7b. Deals, by stage, and how many carry paperwork ---------------------'
SELECT
    d.stage,
    count(*)                                               AS deals,
    count(*) FILTER (WHERE doc.documents > 0)              AS deals_with_documents,
    coalesce(sum(doc.documents), 0)                        AS documents
FROM onboarding.deal d
LEFT JOIN LATERAL (
    SELECT count(*) AS documents
    FROM onboarding.crm_document c
    WHERE c.deal_id = d.id
) AS doc ON true
GROUP BY d.stage
ORDER BY deals DESC;

\echo ''
\echo '================================================================'
\echo ' End of inventory. Attach this output to the migration tickets.'
\echo '================================================================'
