# Remaining work — Exporter CRM

What is still to do, what waits on whom, and what needs a decision. Only open items are
listed; what was built, and why, is in git history and in the contracts. Last reviewed
15 October 2026, on `fix/crm-drop-columns` (migration head `onboarding_0061_drop_columns`;
next free onboarding number **0062**).

---

## 1. Before the next release: on live databases, in this order

**Where.** Every database that holds data someone needs; development and test databases
are rebuilt from empty plus the sample data instead. **Merging into `main` deploys**: the
backend workflow rolls the ECS service out on every merged pull request that touches
`backend/`, and the container runs `alembic upgrade head` first.

| Database | Done | Left |
|---|---|---|
| `aner_settlement` (local) | 15 October 2026: steps 1, 3 and 5 — dumps in `db-backups-2026-10-15`, all four commands validated (100 RMs set, 6 addresses, 4 buyers, 4 relationships); upgraded to `onboarding_0060_drop_tables` | upgrade to 0061; step 2 (`FIELD_ENCRYPTION_KEYS` is unset; the local development key stands in), step 4 (nobody holds Compliance lead or Sales lead), step 6 |
| The ECS service's database | the release with 0060 deployed | step 5 — run the four commands against it **before this release deploys** (a one-off ECS task with the deployed image, or a session with its `DATABASE_URL`); then steps 2, 4 and 6 |

**This release drops what step 5.1 and 5.2 convert, and no longer carries those two
commands.** Run them from the release with 0060 (`main` at `c2c1ad4`). Until they have
validated, 0061 refuses on start-up — listing why, changing nothing — and the new task
does not come up.

1. **`pg_dump -Fc`** of the database. The data commands below do not undo in place; the
   dump is the way back. Keep users out until step 5 has validated.
2. **Settings.** `FIELD_ENCRYPTION_KEYS` set in the environment's secret store and backed
   up (without it, bank details answer 503; losing it loses every stored account number).
   `JWT_SECRET_KEY` set to a random value of at least 32 characters (the server now
   refuses to start without one outside local/test). Setting it for the first time ends
   every access token signed with the old default; the client refreshes, which is
   expected and harmless. Access tokens from before `auth_0011` carry no session id and
   are refused once, then the client refreshes and continues.
   `METRICS_BEARER_TOKEN` if anything scrapes `/metrics`. `CRM_DOCUMENT_SCANNER=clamav`
   with a clamd sidecar before real exporter documents are uploaded.
3. **`alembic upgrade head`**, then deploy. Read what each migration prints: 0054 and 0057
   leave a rule `NOT VALID` and print the query listing the rows that break it; 0057
   refuses while a linked owner in the old onboarding tables carries a date of birth or
   identification number; 0059 refuses while one seller has two deals with the same
   reference, and lists them.
4. **Lead roles.** Someone must hold *Compliance lead* (assigns reviews, approves a
   high-risk Clear, confirms a true sanctions match when
   `CRM_SANCTIONS_TRUE_MATCH_APPROVAL=HEAD`) and someone *Sales lead* (assigns RMs and
   collections owners): Settings → Users. Until then nobody can do those things.
5. **The data commands**, each `--dry-run` (read the report), `--apply --run-id <id>`,
   `--validate` (every count 0, else stop), in this order — the procedure, quiet settings
   and Windows console notes are [`development.md`](development.md) §10.1:
   1. `python -m app.modules.onboarding.backfill_relationship_managers` — names each
      company's RM as a user from the retired free text (an unmatched name is discarded).
   2. `python -m app.modules.onboarding.convert_gst_addresses` — turns each GST branch's
      text address into a linked correspondence address.
   3. `python -m app.modules.onboarding.migrate_deal_buyers` — maps every legacy deal buyer
      to a company. First, `SELECT count(*) FROM onboarding.deal WHERE stage = 'HANDED_OVER'
      AND handover_snapshot IS NULL` must be 0. Compliance reads the dry run's look-alikes
      and the rows that need a person; confirm those with `--confirm-name`.
   4. `python -m app.modules.onboarding.backfill_trade_relationships` — only after 3 has
      validated.
6. **Tell the users what changed:** a deal's buyer is always a company (the old buyer form
   is gone; deals that had one keep it, read-only); a seller's deals need different
   references; a company's RM is a user, never free text; a GST branch's address is an
   address record.

An environment older than `onboarding_0053` also meets these on upgrade; tell its users
before deploying: the administrator becomes read-only and sees tax identifiers masked;
only Compliance saves a copy of a document; bank details and sanctions true matches need
a second person (`CRM_BANK_CHANGE_APPROVAL_MODE`, `CRM_SANCTIONS_TRUE_MATCH_APPROVAL`);
`CLEAR`, `FLAGGED` and `ON_HOLD` need two compliance officers and a Clear lasts a year;
a handover needs a scanned-clean pre-shipment document, a buyer with sanctions and AML
passed, an active primary contact on the seller, no sanctions flag, and the invoicing
branch when the seller has an active GST registration. Below `onboarding_0040`, first
check `SELECT count(*) FROM onboarding.exporter_profile WHERE iec IS NOT NULL AND iec !~
'^[A-Z0-9]{10}$'` is 0.

## 2. Open work

| Item | What is left | Waits on |
|---|---|---|
| Buyer warnings on the deal | A deal should *warn* — never block — when its buyer's KYB is not passed, or its background check is not `CLEAR` or has expired. Compute the warnings on the server beside the handover guard (`domain/handover_conditions.py`) and show them on the deal page | — |
| Handover conditions as a list | Serve `handover_conditions: [{key, met, message}]` beside `handover_blocked_reason`, so the deal page shows a checklist instead of one joined sentence | — |
| Remove `BuyerChecks.tsx` | Delete the component, its test, its export and the deal page's mount. It is the only screen for a legacy buyer's checks | §1 step 5.3 in every environment |
| Audit every disclosure to a masked role | Only `/companies/match` writes an audit row when it names the company holding an identifier. The duplicate-PAN refusal, the GSTIN warnings on create and edit, `also_held_by` on GST registrations and the CSV import's `candidates` name the holder without one. Move the audit helper into one place and call it from each | — |
| Company name and country required | `CreateExporterProfileRequest` still allows a company with neither (`create_or_get_profile`). Remove that path; then a migration that refuses while any nameless company exists and sets both `NOT NULL` | The count of nameless companies in each environment |
| Retire `GET /exporters/activities/pending` | Superseded by `GET /follow-ups`; lists completed follow-ups too; no screen calls it. Remove the route, its authorisation rows and OpenAPI entry | Confirm no outside caller |
| Criterion versions name their author | The qualification-criteria screen shows `created_by` as a user id; serve `created_by_name` like every other history-like read | — |
| Company search total | `GET /exporters` returns no `total`, so Home and Companies cannot show exact counts | — |
| Change a "not now" check-back date in one step | Today it takes two gauge moves. Add it as its own action with its own history event | — |
| Refresh-token reuse window | Reloading quickly several times can sign a user out: accept the token just rotated once more for about 30 seconds (`/auth/refresh`). Platform code: run the whole suite | — |
| CI | Only deploy workflows exist. Add a pull-request workflow running `development.md` §7 (Postgres 16, `alembic heads/upgrade/check`, `pytest --crm`, ruff, lint-imports; tsc, eslint, vitest, build) and the whole suite nightly | The lead enables it |
| List rows and filters for the screens | Company list rows carrying the background check, awaiting-approval and Re-KYC flags (staff only); a background-check filter on the company search; the server's route-role table as a guarded artifact the frontend's capability map is checked against | — |
| Intermittent tests | `test_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle` (two decisions can share a timestamp: order ties by the decision chain); `test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` (asserts a query plan); `test_buyer_migration_safety.py::test_a_created_company_gets_one_creation_row_saying_where_it_came_from` (a `created_at` tie broken by a random id) | — |
| OpenAPI artifact test and `APP_NAME` | The test compares `info.title`, which comes from `APP_NAME`; pin the title in code or leave it out of the comparison | — |
| Run the suite in the `aner-app` container | `test_openapi_artifact_is_current.py` needs `./frontend`; mount it read-only in compose | — |
| Isolate the document converter | LibreOffice runs as the backend's user beside its secrets. Run it in a separate container or job with no database credentials, no `FIELD_ENCRYPTION_KEYS` and no network | Infrastructure |

## 3. Decisions awaited

| Question | Options | Blocks |
|---|---|---|
| Who manages the sanctions lists? Only the administrator holds `settings:manage`, so Compliance cannot record a new list version (the re-screen trigger), while the administrator can make a mandatory list optional | Keep it under settings; or guard the lists with a compliance permission | Nothing |
| Should a required-document setting apply to deals already in progress? Today a requirement switched on blocks a handover that was ready | As built; or only deals opened after the change | Nothing |
| The deal-value qualification criterion never fires: a deal is opened only for a qualified company, and `QUALIFIED` is final | Drop it as an automatic source; or answer it from an expected deal size recorded on the lead | Nothing |
| DEVELOPER reads a company's bank accounts (masked to the last four, with bank, IFSC and SWIFT) and their history | As built (consistent with masked tax identifiers); or withhold them | Nothing |
| A company can be cleared with no document (screening answers and passed KYB, AML and sanctions suffice) | Accepted for now; revisit before real documents are stored | Real data (§4) |

## 4. Deferred

Not current work; each starts only when its trigger happens.

| Item | Trigger |
|---|---|
| A real virus scanner, S3 with Object Lock, KMS and retention, field-level encryption of tax identifiers. **Precondition for any real document or customer data** (each is a new implementation of `ScannerPort` / `StoragePort`) | A decision to use real data |
| Field-level provenance and consent | The data-protection review |
| Provider adapters (Middesk, Trulioo, Sumsub); checks stay manual | A decision to connect a provider |
| RXIL results intake and its machine identity (never `API_USER`) | RXIL's package and results contract |
| Thresholds shown in rupees (they stay in USD) | A business request |
| PAN derived from a GSTIN for PAN-less companies (with an audit table for rollback) | Enough such companies to be worth it |
| A stored `name_key` for name matching (today every company in a country is scanned per lookup) | About 50,000 companies in one country |
| Group-level `--confirm-name` for the buyer migration | A dry run with many rows sharing one contested identifier |
| A server-checked preview (`dry_run`) for the CSV import; imports above 1,000 rows as a background job | A business need |
| A cross-company documents list | A product decision |
| Documents in the sample data | A scanner worth running |
| The "Verify GSTIN" link (`services.gst.gov.in/services/searchtp?tin=`): the portal's deep-link format was never confirmed; if it ignores the parameter, it opens the search page | Confirmation from the portal |
| Worklists and the approvals badge are computed on every read (the badge refetches every 60 seconds per tab) | A few thousand companies under review at once: store the deadlines or cache the counts |

## 5. Later, optional

**Retire `deal_buyer` entirely.** After the buyer migration has run everywhere and the
deal response's `buyer` field has been gone for one release: read the seller timeline
from the `company_created_from_deal_buyer` history rows instead of joining `deal_buyer`,
stop falling back to `DealBuyer.name`/`country`, then archive and drop the table
(31 tables). Irreversible; recover from the archive.

**Squash the CRM's migrations into one baseline — at the CRM's separation, not before.**
Alembic keeps one chain for the whole platform and the CRM's revisions are woven through
it (`auth_0002`–`auth_0010` between onboarding revisions, `customers_0002` descending
from `onboarding_0002`, two merge revisions), so squashing now would mean rewriting
schemas, roles and grants the separation throws away. When the other modules' migrations
are gone and the chain is CRM-only:

1. Preconditions: every environment at the same head *H*; one release with no rollback;
   `pg_dump --schema-only` of each matches a fresh build at *H*; the pre-squash commit
   tagged.
2. Write `baseline_0001.py` (`down_revision = None`): a guard refusing a non-empty
   database; the extensions and roles the kept schemas need; the schema DDL from a fresh
   reference build; grants; the seed rows of every table a fresh build fills (roles and
   permissions, qualification criteria, required documents, payment terms, sanctions
   lists); a `downgrade()` that raises.
3. Verify: build from the baseline alone and compare schema, roles, privileges and seed
   rows with a build of the old chain; `alembic check` clean; every gate green.
4. In the same PR: delete the old revision files; move the constants three tests import
   from migrations (`onboarding_0033._CHANNEL_BY_SOURCE`, `onboarding_0040.IEC_PATTERN`,
   `onboarding_0035._STATE_NAMES`) into the domain; delete tests of historical data
   steps, keep tests of the resulting rules; restart the migration register.
5. Switch each environment over: `alembic current` shows *H*; compare the schema; dump;
   `alembic stamp --purge baseline_0001` with the new image; start it (`upgrade head` is
   a no-op). To roll back before later migrations, `alembic stamp --purge H` with the old
   image.
