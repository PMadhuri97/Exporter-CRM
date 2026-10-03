# Remaining work — Exporter CRM

**As of 4 October 2026**, on `feature/company-foundation-and-compliance-guard` @ `451ef97`.
That PR is 4 commits on `main` @ `6f8648c`, by one developer, and covers Developer 2's and
Developer 3's remaining lanes. Developer 1's lane was already merged (PR #16).

This is the **one list of everything still pending**, whoever it used to belong to. From
here there is one developer, so nothing below is assigned to a lane: an item is either
open or done. It replaces `dev1-remaining-work.md`, `dev2-remaining-work.md` and
`dev3-remaining-work.md`, deleted on 4 October 2026 (`git show 451ef97:docs/<name>` recovers
them). The task numbers (2.6, 3.12, …) and plan ids (P4-6, …)
are kept because the code, the contracts and the plan cite them.

Every finding marked **confirmed** was reproduced on 4 October 2026 against a copy of the
scratch database (15,898 companies, 1,158 deals, 783 legacy `deal_buyer` rows), not
inferred from reading.

| | |
|---|---|
| **PR verdict** | **Not mergeable as it stands.** Three gates fail (§2), and the deal page cannot hand over a deal whose seller has a GST registration (§3). The rest of the PR is sound; once those are fixed it can merge |
| **Before merge** | §2 and §3: R-01 – R-05, all small |
| **Before the buyer migration runs anywhere** | §4: R-06 – R-11. On the scratch copy it merged 400 identifier-less buyers into one company |
| **Bugs to fix soon** | §5: R-12 – R-23, six of them confirmed with a reproduction |
| **Unbuilt** | §6: R-24 – R-33. Two of them are preconditions for retiring `deal_buyer`; R-33 points to the separate frontend plan |
| **Waiting on the lead** | §8: D-01 – D-07 from this PR, plus the decisions already open |
| **Next free migration number** | **0041** (`contracts/migration-register.md` §1) |

---

## 1. What the PR delivered

Read against the three lane documents as they stood on 2 October (now deleted; in git history). "Done" means built,
tested and checked here. "Done, with defects" points to the item that fixes it.

### Developer 2's lane

| Task | State | Notes |
|---|---|---|
| 2.4 buyer company on the deal (P4-4) | **Done** | `PUT /deals/{id}/buyer {buyer_company_id}`, set once (0034), snapshot from the company, `CompanyPicker` and `CompanyComplianceSummary` (seller and buyer) on the deal page, `BuyerChecks` only for legacy buyers. The picker cannot **create** a company (R-24) |
| 2.5 compliance conditions (P3-3b, P3-4, P4-7) | **Done** | All four gaps from the old `dev2-remaining-work.md` §2 are closed. Developer 1's reader is injected; there is one copy of each Protocol; the expiry message is gated on `is_clear` and gives the date; both parties are share-locked, sorted by `customer_id`. It includes Developer 1's "handover vs a flag on the buyer" concurrency test (`test_l3b_handover_compliance.py:302`) |
| 2.6 buyer migration (P4-6) | **Done, with defects; never run on a live database** | `migrate_deal_buyers.py`, the map table (0038), and filling a closed deal's buyer (0039). It breaks IQ-8 and can re-subject results to the wrong company (§4) |
| 2.7 deals as buyer | **Done** | `GET /exporters/{id}/deals?as=buyer`, `CompanyDealsList` full, and the buyer's history includes its deals' rows (D8 still applied) |
| 2.8 invoicing branch on the deal (P6-6) | **Backend done; UI missing** | `PUT /deals/{id}/invoicing-branch`, composite FK (0036). No picker on the deal page (R-05) |
| 2.9 branch rules in the guard (P6-7) | **Done, with defects** | Both rules live through `BranchFlagService`. A flag does not wait for a handover in flight (R-18) |
| 2.10 retire `deal_buyer` writes (P4-10) | **Not started** | Blocked (R-25) |
| 2.11 trade history on the deal page | **Done** | Only on a deal with a buyer company |
| 2.12 main end-to-end | **Done** | Match → buyer company → branch → handover → payment outcome, read from both sides |

### Developer 3's lane

| Task | State | Notes |
|---|---|---|
| F3 company foundation (P4-1) | **Done** | 0032; `CompanyDirectory`; the real `BranchFlagReader`; `CompanyPicker` and `TradeHistoryPanel` |
| 3.7 website removed (IQ-16) | **Done** | Forms, request schemas, CSV (the old header is still read), RXIL; stored values kept and hidden |
| 3.8 identity and `created_via` (IQ-7) | **Done, with defects** | 0033 backfill; the registration number is masked in responses. Not masked in **history** (R-15); `identity_type` goes stale on edit (R-16) |
| 3.9 not in pipeline | **Done** | Excluded from the working list, a notice on the company page, deal lists mounted |
| 3.10 `POST /companies/match` (BQ-2) | **Done** | Exact identifiers only, no identifier in the response, every lookup audited |
| 3.11 bring into pipeline | **Done** | Route and button; the journey starts at LEAD |
| 3.12 `exporter_gstin` as a branch | **Done** | 0035; a no-delete trigger; `delete-orphan` removed |
| 3.13 GST registration routes and section | **Done** | PATCH no longer takes `gstins` |
| 3.14 flag / unflag, real reader | **Done** | |
| 3.15 shared-GSTIN warnings (IQ-9) | **Done** | `also_held_by` |
| 3.16 PAN from GSTIN | **Not started** | Optional; conditional on 3.2's reports (R-30) |
| 3.17 "Verify GSTIN" link | **Done** | Served only to roles that see the full GSTIN |
| 3.18–3.19 trade tables | **Done** | 0037 |
| 3.20 trade routes | **Done** | No identifiers in any response |
| 3.21 payment outcome on a deal | **Done, with defects** | Not atomic (R-12) |
| 3.22 trade panels | **Done** | |
| 3.23 relationship backfill (P5-5) | **Done; never run on a live database** | Works here: 783 created, validation all 0, a re-run creates nothing. Crashes on a Windows console (R-11) |
| 3.24 masking sweep | **Done, breaks a gate** | Imports `app.main` (R-02) |
| Inherited: IEC `CHECK` | **Done** | 0040 |

### Developer 1's lane (merged before this PR)

| Item from `dev1-remaining-work.md` §2 | State |
|---|---|
| 1. Concurrency: handover vs a flag on the buyer company | **Done** in this PR (`test_l3b_handover_compliance.py:302`). The strict-xfail version pre-staged on 2 October was never committed, and is not needed now |
| 2. Delete `BuyerChecks.tsx` | Blocked (R-26) |
| 3. Re-run `test_dev1_company_keyed.py` against F3 | Covered by the full-suite run in §12 |
| 4. Optional: "Not in pipeline" on the Re-KYC due list | Not started (R-29) |

### Checked and sound

- **Migrations 0032–0040** leave a single head.
  - Upgrade from `auth_0005` on the scratch copy took 10 s.
  - Downgrade to `auth_0005` and back to head also passed, with migrated buyer data
    present.
  - Every rewrite of `prevent_terminal_deal_change()` (0034, 0036, 0039) restates 0029's
    snapshot block.
- **Authorisation.**
  - Every new route has a role dependency and a row in both route-authorisation tables.
  - DEVELOPER can read trade history and write nothing.
  - `/companies/match` refuses DEVELOPER.
- **Masking on reads.** The 3.24 sweep calls every CRM `GET` as OPERATIONS and as
  DEVELOPER. The one leak is in history **written** by an edit, which the sweep does not
  exercise (R-15).
- **Frontend tests.** vitest passes: 45 files / 435 tests. `vite build` on its own also
  succeeds.

---

## 2. Gates that fail today — fix before merging

| Id | Gate | What fails | Fix |
|---|---|---|---|
| **R-01** | `tsc -b --noEmit`, and so **`npm run build`** (`tsc -b && vite build`) | **21 type errors**, all caused by the PR. Twelve are in source: `GstRegistrationsSection.tsx` lines 87, 98, 271, 274; `TradeInvoiceList.tsx` 76; `DealDetailPage.tsx` 105, 106, 152 (×2); `ExporterDetailPage.tsx` 164. Nine are in tests: `CompanyPicker.test.tsx` (7), `GstRegistrationsSection.test.tsx` (2). One each in `ExportersListPage.test.tsx` and `PipelinePage.test.tsx`, whose fixtures predate three new list fields. **The production build does not complete**; only `vite build` on its own passes | The regenerated `schema.ts` changed shapes the screens were written against: `AddGstRegistrationRequest.status` is now required, `also_held_by` optional, and the legacy buyer form's `name`/`country` optional; list items gained `registration_number`, `identity_type` and `pipeline_status`. `evidence_refs` (`list[dict]` on the server) generates as `Record<string, never>[]`, so type it on the server as a list of `{type, ref}` and regenerate. Then fix the screens and fixtures |
| **R-02** | `lint-imports --config importlinter.ini` | **18 kept, 1 broken** (baseline 19 / 0). The broken one is "modules never import the delivery layer": `test_dev3_masking_sweep.py:49` does `from app.main import app` | Take the app from the `client` fixture's transport, or move the sweep to `backend/tests/contract/` |
| **R-03** | `ruff check .` | **17** (baseline 16). The new one is `I001` in `test_dev3_f3_foundation.py:18` | `ruff check --fix` on that file only |
| **R-04** | Backend suite | See §12 | — |

---

## 3. Release blocker in behaviour — fix before merging

| Id | Problem | Evidence | Fix |
|---|---|---|---|
| **R-05** | **No invoicing-branch picker on the deal page, but the guard asks for one.** Since task 2.9, "the invoicing branch is not recorded" blocks a handover whenever the seller has an active GST registration. The only writer is `PUT /deals/{id}/invoicing-branch`, and no screen calls it. **So a deal opened in the UI for a seller with a GSTIN can never be handed over from the UI.** The seeded deals hide this, because `sample_data_deals._ensure_invoicing_branch` sets the branch for them | No client code calls `/invoicing-branch` (only `schema.ts` names it). `demo.md` §4 step 10 describes a control that does not exist | On the deal page, offer staff a select of the seller's **active** registrations (`GET /exporters/{id}/gst-registrations`: state name and masked GSTIN), with a "clear" option, until the deal closes. Show the recorded branch's state read-only. Add a hook and a test, plus a `DealDetailPage` test that shows the guard's message |

---

## 4. The buyer migration (2.6, P4-6) — fix before it runs on any live database

`--dry-run`, `--apply`, `--validate` and a re-run were all executed on the scratch copy.
`subject_company_id` and `deal.buyer_company_id` are frozen once set, so **a wrong run
can only be undone by restoring the `pg_dump`**.

| Id | Problem | Evidence | Fix |
|---|---|---|---|
| **R-06** | **Name-only buyers are merged automatically**, against IQ-8 and plan §17.2 step 4 ("not auto-merged; a person confirms"). A buyer with no identifier, and no existing company of that name, gets `rule = NEW` and `group_key = NAME:<country>:<name>`. `apply` then reuses that one created company for every later row with the same name (`migrate_deal_buyers.py:390-392`, `:435-436`) | **Confirmed.** Dry run: **"need a person: 0"**, with `NAME:NL:ROTTERDAM TRADING: 400 rows` going to one company, plus two smaller name groups. `--apply`: 783 buyers became **10 companies** | Give name-only `NEW` rows no group key, so each becomes its own company (IQ-8: "keep separate"). List the look-alike groups in the report as "kept separate — review". Add a test with two identifier-less buyers of the same name |
| **R-07** | **A deal that already names a buyer company gets its legacy buyer mapped to a different company, and its BUYER results re-subjected to that other company.** `resolve()` never reads `deal.buyer_company_id`. `apply`'s deal update skips such a deal silently (`WHERE buyer_company_id IS NULL`), but its results update does not (`:469-488`). This hits every deal whose buyer company was chosen on the new deal page before the migration runs | **Confirmed.** 5 deals mapped to another company; **45 BUYER results** whose `subject_company_id` ≠ the deal's buyer company. **`--validate` reported every check OK** | When the deal already names a company: map to it if the identifiers agree, otherwise report "needs a person". Add two validation queries: map company ≠ `deal.buyer_company_id`, and BUYER result subject ≠ the deal's buyer company |
| **R-08** | A PAN found through a GSTIN takes an **arbitrary** holder when several companies hold GSTINs carrying it (`scalar()` on `gstin LIKE '__<PAN>%'`, `:324-329`). §17.2 step 2 wants a `CONFLICT` reported | Code reading. IQ-9 makes shared GSTINs legal, so this case is real | Fetch every distinct holder; more than one → a problem row |
| **R-09** | `--confirm-name <buyer>=<company>` accepts **any** company id. Nothing checks it against the row's candidates, against the deal's seller, or that it exists. Because `create_buyer_company` commits each company as it goes, a seller id fails on `ck_deal_buyer_is_not_the_seller` **mid-run**, after earlier rows are already committed | Code reading | Validate every confirmation before writing anything |
| **R-10** | Gaps against §17.2. (a) The buyer's email and phone never reach a contact record: `BuyerCompanyDraft` carries them and `create_buyer_company` drops them. (b) The creation history row lacks event `company_created_from_deal_buyer` and details `{run_id, deal_buyer_ids, deal_ids, match_rule}`. (c) A one-character registration number groups rows together. (d) Validation query 5 also counts DEAL_BUYER companies later brought into the pipeline, so it fails after normal use | (c) confirmed: `REG:BE:X` grouped 11 rows. The rest from code reading | Carry the contacts. Write the specified row. Report implausible registration numbers. Restrict query 5 to companies a run created (`source_ref = run_id`) |
| **R-11** | **Both data commands crash on a Windows console.** They print `→`, which cp1252 cannot encode. `backfill_trade_relationships.py:132` crashes **before** `--apply` writes anything; `migrate_deal_buyers.py:357` crashes as soon as a conflict row is printed. Separately, with `DEBUG=true` / `LOG_LEVEL=DEBUG` (the dev `.env`) every SQL statement is echoed and buries the report | **Confirmed** for the backfill: `UnicodeEncodeError` on `--dry-run` and `--apply` | Print `->`, or call `sys.stdout.reconfigure(encoding="utf-8")` in both `main()`s. In the runbook, run with `LOG_LEVEL=WARNING DEBUG=false` |

---

## 5. Bugs to fix soon (not merge blockers)

| Id | Problem | Evidence | Fix |
|---|---|---|---|
| **R-12** | **Recording a payment outcome is not atomic.** `record_outcome_for_deal` calls `record_invoice`, which **commits**, and only then validates the outcome. A refused request leaves the invoice behind, and the corrected retry is then refused because the invoice exists | **Confirmed.** `PARTIAL` with no `amount_paid` → 422, but the invoice is written. Retry with `amount_paid` → 422 `TRADE_INVOICE_ALREADY_RECORDED` | Validate the outcome before writing. Give `record_invoice`/`record_outcome` a no-commit path for this caller, and commit once at the end |
| **R-13** | **Two outcomes at once give a 500.** Two first outcomes, or two corrections of the same head, hit `uq_trade_invoice_outcome_first` / `_supersedes`. That surfaces as `IntegrityError` → 500 instead of the 409 `TRADE_OUTCOME_STALE` the route documents | **Confirmed:** `['IntegrityError', 'TradeInvoiceOutcome']` | Lock the invoice row `FOR UPDATE` in `record_outcome` before reading the head |
| **R-14** | Two concurrent payment-outcome calls on a deal with no invoice can create **two invoices** for it. Nothing locks the deal, and `trade_invoice.deal_id` has no unique index | Code reading | Lock the deal row in `record_outcome_for_deal`. Add a partial unique index if "one invoice per deal" is the rule (D-03) |
| **R-15** | **Edits to `registration_number` are written unmasked into history**, which OPERATIONS and DEVELOPER can read. `_MASKED_IN_HISTORY` (`exporter_profile_service.py:161`) lists PAN, GSTINs, IEC and CIN only | **Confirmed:** old and new values appear in `GET /exporters/{id}/history` for both roles | Add it to the set. Check live databases for rows already written (`dimension = 'profile' AND to_value = 'registration_number'`). Extend the 3.24 sweep to **edit** each identifier before reading history |
| **R-16** | **`identity_type` goes stale.** It is set only on create. A PATCH of `pan` or `registration_number` never recomputes it, and that is exactly IQ-7's completion flow. IQ-7 is not enforced on PATCH either: moving a company abroad, or clearing a foreign company's number, is accepted | **Confirmed:** after a PAN is added by PATCH, `identity_type` stays NULL | Recompute it in `update_profile`, and apply `require_foreign_registration_number` to the post-edit state. Backfill the rows edited since 0032 |
| **R-17** | `POST /trade-relationships/{id}/invoices` accepts **any `deal_id`**. Nothing checks that the deal exists (there is no FK) or belongs to the relationship's pair, and the value is frozen once written | **Confirmed:** a random UUID → 201 | Validate that the deal exists and belongs to the pair. Migration 0041: an FK `trade_invoice.deal_id → deal.id`, and also the missing `exporter_profile.created_via_deal_id → deal.id` |
| **R-18** | **A handover and a branch flag can interleave.** The guard share-locks both companies, but `GstRegistrationService.flag` locks only the `exporter_gstin` row. So a flag committed between the guard and the handover's commit does not stop the handover: the race D10 closed for the background check | **Confirmed:** `flag()` completes while the guard's `FOR SHARE` lock is held | Have `flag()` lock the owning `exporter_profile` row `FOR UPDATE` first (and `deactivate()` too, if D-04 makes deactivation a block). Add a concurrency test like `test_l3b_handover_compliance.py:302` |
| **R-19** | A **deactivated** invoicing branch does not block the handover. `set_invoicing_branch` refuses an inactive branch, but a later deactivation is never re-checked, and `deactivate()` ignores open deals | Code reading | D-04 first, then either a guard condition or a warning |
| **R-20** | Registration-number matching disagrees with the unique index. `registration_key()` keeps any Unicode `isalnum()` character, but the index strips everything outside `[A-Za-z0-9]`. For a non-ASCII number, match says "no company" and the insert then fails with `IntegrityError` → 500 | `company_identity.py:90` vs 0032's index expression | Make the Python side ASCII-only |
| **R-21** | `POST /exporters` accepts `source = DEAL_BUYER` and creates an **in-pipeline** lead with a journey row: a company sourced as a buyer that is not one | `CreateExporterProfileRequest.source: ExporterSource` | Refuse `DEAL_BUYER` there. R-24 is the way to create a buyer |
| **R-22** | The `/companies/match` audit row records `ActorType.COMPLIANCE_OFFICER` whatever the caller's role | `company_directory.py:258` | Map the type from the role, or use a neutral one |
| **R-23** | `trade` history rows sit on the seller's timeline only. The buyer company's History tab shows its deals but no invoices or outcomes, because the read-side union admits `deal` rows only | `exporter_lifecycle_history_repository._about_company` | D-06 |

---

## 6. Unbuilt work

| Id | Item | Needs | Notes |
|---|---|---|---|
| **R-24** | **Create a buyer company** from the deal screen | — | Nothing creates a `NOT_IN_PIPELINE` company, though `demo.md` §4 step 5 tells the presenter to (`CompanyPicker.tsx:253` says it "arrives with the buyer migration"). Today's options are the legacy details form, which is being retired, or Add company, which makes a **lead** and inflates pipeline counts (P4-2). To build: a route over `CompanyDirectory.create_buyer_company` (match first; the IQ-7 number for foreign buyers; D8; an authorisation row; a masking test), and a "Create buyer company" step in the picker when the match is `NEW`. **A precondition for R-25** |
| **R-25** | **2.10 / P4-10 — retire `deal_buyer` writes.** A trigger refuses INSERT/UPDATE (the table is kept). Drop the legacy `buyer` from the deal response after one release. Rewrite decision 9 in `architecture.md`, `deal-and-buyer.md` and `event-envelope.md` | §4 fixed; P4-6 run in **every** environment (§7); R-24 | This removes "Record details instead" and the legacy form of `PUT /deals/{id}/buyer` |
| **R-26** | Delete `components/BuyerChecks.tsx`, its test, its export, and `BUYER_CHECK_TYPES` if nothing else uses it | R-25 | Until then it is the only place a legacy buyer's sanctions and AML can be recorded, which BQ-4 needs |
| **R-27** | **Past-invoice form** on the company page's trade panel (claimed past trade, P5-8) | — | The API exists (`POST /trade-relationships/{id}/invoices`, `…/outcomes`); there is no screen |
| **R-28** | **IQ-7 completion list:** companies whose `identity_type` is NULL (migrated buyers with no number, and legacy rows) | R-16 | Plan §17.2 sends such buyers "to the completion list"; only the `pipeline_status` filter exists |
| **R-29** | Optional: `pipeline_status` on the Re-KYC due list and its Home card | — | Add it to `ReKycDueCompanyResponse` and regenerate the OpenAPI artifacts |
| **R-30** | Optional 3.16 / P6-4: PAN from GSTIN for PAN-less companies, with an audit table for rollback | 3.2's reports (§7 step 0) | Only if the reports say it is worth doing |
| **R-31** | `name` / `country` `NOT NULL`: remove the unnamed `POST /exporters` path, then expand → backfill → contract | Nothing calls the unnamed path | Inherited from `open-items.md` §2 |
| **R-32** | Name matching scans every company in the country, in Python, on each lookup (`company_directory._by_name`). The migration's step 4 does this **per buyer** | Only matters past about 50,000 companies in one country | Store a `name_key` column, maintained by `company_names.name_key` |
| **R-33** | **Frontend redesign and fail-closed role access.** Planned separately in `docs/frontend-plan.md` (written 4 October, not yet committed), not repeated here. Its Phase 0 fixes seven role-visibility gaps (G1–G7) on today's screens, for example API_USER seeing the full navigation and DEVELOPER reaching the Add company and Import CSV forms by URL | — | Do Phase 0 before any visual work. Its deal-room and party-card designs should include R-05's branch picker and R-24's create-buyer step, rather than building those twice |

---

## 7. On live databases — in this order, do not reorder

This is not a coding dependency. It is the order things run in each environment:
`crm_uat_walk`, `crm_release_audit`, demo, and shared test.

0. **3.2's inventory reports.** Run `backend/scripts/crm_data_inventory.sql` (read-only)
   on every live database and keep the output with the migration ticket. The reports size
   step 5 and decide R-30. Never attach numbers from a development database.
1. **Before deploying this release:**
   - Run the IEC pre-check for 0040, which fails outright on any violating row. This must
     return 0:
     `SELECT count(*) FROM onboarding.exporter_profile WHERE iec IS NOT NULL AND iec !~ '^[A-Z0-9]{10}$'`
   - **Send the 0031 release note** (still owed). After 0031, `export_history` and
     `export_licence` stop counting towards the suggestion, so an undecided lead may now
     suggest `QUALIFIED`. Decided companies are unaffected.
2. `pg_dump`.
3. `alembic upgrade head` (0032 → 0040). Read the two counts it prints: 0033's companies
   left with `created_via` NULL, and 0035's unknown state codes.
4. Deploy. From here users can name a buyer **company** on a deal, which is the case
   R-07 must handle in step 5.
5. **Buyer migration P4-6**, only after §4 is fixed:
   - Dry run:
     `LOG_LEVEL=WARNING DEBUG=false python -m app.modules.onboarding.migrate_deal_buyers --dry-run`
   - Compliance reviews the name-only look-alikes (IQ-8).
   - `--apply --run-id <id>`, plus any `--confirm-name` lines.
   - `--validate`: every count must be 0.
   - Re-run `--apply`: it must create nothing. The counts must equal the dry run's.
   - **`--rollback` writes nothing. The dump is the only way back.**
6. **Relationship backfill P5-5** (3.23): `--dry-run`, then `--apply --run-id <id>`, then
   `--validate`. Undoing it is one `DELETE` (`--report-run` prints it), as long as no
   invoice points at the run's relationships.
7. **P4-10** (R-25), only once every environment has passed step 5. Then R-26.

---

## 8. Decisions waiting on the lead

### 8.1 New from this PR

| Id | Question | What was built |
|---|---|---|
| D-01 | May the invoicing branch be **changed** before handover? Allocation task 2.8 said "set-once"; plan P6-6 says "may be set any time before handover" | Changeable until handover, frozen after (0036) |
| D-02 | §17.2's logical rollback of P4-6 is impossible, because both columns it would reset are frozen. Accept restoring the dump as the only rollback? | `--rollback` reports and writes nothing |
| D-03 | One invoice per deal? | One in practice (the deal route refuses a second), but not enforced (R-14) |
| D-04 | Should a deactivated invoicing branch block the handover, or only warn? | Neither (R-19) |
| D-05 | Should DEVELOPER see GST branch **flag reasons**? They are compliance judgements (D8) | Served on `GET …/gst-registrations` and in `gst_registration` history; `gst_registration` is not in `HIDDEN_FROM_DEVELOPER` |
| D-06 | Should a buyer company's History tab show the trade rows of deals it bought on? | No (R-23) |
| D-07 | `also_held_by` and `/companies/match` name other companies to OPERATIONS | Built that way. It falls under the open "identifier disclosure" question below |

### 8.2 Already open (`open-items.md` §1)

- **Confirmed on 2 October 2026, but the record never reached the repo.** You confirmed
  these as built. The write-up (`background-check.md` §14.2, and their removal from
  `open-items.md` §1) never reached `main`, so it needs recording again:
  - Developer 1's five: REVIEW + REJECTED reads `FAILED`; `CHECK_CYCLE_EMPTY`; the
    maker-checker details; the expiry backfill keyed on the last Clear; `BuyerChecks`
    kept until P4-10.
  - D4's verification side.
  - No D2 amendment for placeholders.
  - No document required to Clear (revisit with gate §7.6).
- **Still awaiting written confirmation:** U4/D11; deals only for `PROSPECT`/`CUSTOMER`;
  the D2 clarification; the D5 amendment.
- **Undecided:**
  - D12: RXIL's results contract (blocks RXIL results intake), and RXIL's service
    identity.
  - O2: `CUSTOMER` replaces `ONBOARDED`.
  - Identifier disclosure to masked roles.
  - The reload-burst refresh window.
  - Re-dating a `NOT_NOW` check-back in one step.
  - Retiring `GET /exporters/activities/pending`.
  - Cross-company Deals and Documents lists.
  - Gate §7.6 (a real scanner, S3 with Object Lock) and the `object_storage` package.
  - CI (U6).

---

## 9. Documents to correct

| Document | What is wrong |
|---|---|
| `demo.md` §4 steps 5 and 10 | Step 5 says the picker creates a buyer company (R-24); step 10 says the branch is chosen on the deal page (R-05). Neither control exists |
| `open-items.md` §1 | Stale rows: §1.1 "the expiry condition … does not yet block a handover" (2.5 is done); "P4-11 rests on … not yet merged" (F3 is in). §1.2's BQ-4 row is now marked built but belongs out of "Undecided". Re-record the 2 October confirmations (§8.2) |
| `contracts/migration-register.md` §1 | Blank lines after the 0032, 0034 and 0037 rows split the table, so each row after a gap renders as plain text |
| `onboarding_0033_created_via.py` docstring | Names `test_dev3_f3_created_via.py`, but the test is in `test_dev3_company_identity.py` |
| `development.md` | No runbook for the two data commands. Add §7's steps 5–6, with the `LOG_LEVEL` and console-encoding notes |

---

## 10. Engineering backlog (carried from `open-items.md` §2)

- CSV imports stop at 1,000 rows. Only if the business needs more: a background job.
- `bank_activity_finding` has no FK to the company. Decide when a bank feed exists.
- The OpenAPI comparison includes `info.title`, which comes from `APP_NAME`.
- The suite in the `aner-app` container needs `./frontend` mounted.
- Two flaky tests:
  - `test_dev1_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle`
    (a `decided_at` tie; order by `decided_at DESC, id DESC`).
  - `test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` (asserts a query
    plan).
- Accounts made with a special-use address cannot sign in.
- The shared test database accumulates rows.
- There are no documents in the sample data.
- The company search returns no `total`.
- Two screens show a user id rather than a name.
- No screen for managing reason codes.
- The legacy onboarding routes and the `compliance` routes commit after the response.
- The legacy case path records the actor type as `API_CLIENT`.
- Contract acknowledgement tables still read "pending".

## 11. Deferred, or waiting on outside parties (allocation §7)

- P1-3 rupee display: thresholds stay in USD (BQ-1).
- P6-3 global GSTIN uniqueness: dropped (IQ-9).
- P7-1 – P7-3 provider adapters: checks stay manual (BQ-8).
- P7-4 field-level provenance and P7-5 consent: both wait for the DPDP meeting.
- P7-6 RXIL automatic intake: waits for D12.
- P7-7 encryption, a real scanner and S3 Object Lock: a precondition for real data.

---

## 12. Gates and baseline (4 October 2026)

Run as in `development.md` §7, against a scratch database at head. Never use the shared
`aner_settlement`, which sits at 0027. Export **both** `DATABASE_URL` and
`DATABASE_SYNC_URL`.

| Gate | Result on `451ef97` | Last baseline (2 October) |
|---|---|---|
| `alembic heads` | one: `onboarding_0040_iec_format` | one: `auth_0005_rm_role_name` |
| Backend suite | _pending — the run was still going when this was written_ | 4,932 passed, 7 skipped, 27 xfailed, 1 environmental failure |
| `ruff check .` | **17** (R-03) | 16 |
| `lint-imports` | **18 kept, 1 broken** (R-02) | 19 kept, 0 broken |
| `tsc -b --noEmit` / `npm run build` | **21 errors; the build fails** (R-01) | — |
| `eslint .` | 0 errors, 2 warnings | same |
| `vitest run` | 45 files / 435 tests | 39 / 372 |
| `vite build` alone | passes (chunk-size warning) | same |

**Removed on 4 October 2026:** the three lane documents (this file replaces them) and the
outdated design PDF, `Exporter-CRM-Architecture-and-Plan.pdf`. Both are recoverable with
`git show 451ef97:docs/<name>`. Every link to them now points here, at `architecture.md` or
at `plan.md`. Keep this file up to date as items close.

## 13. Suggested order

1. §2 and §3 (R-01 – R-05): small, and they unblock the merge.
2. R-15, R-12, R-13, R-17, R-18. One migration (0041) for the FKs; the rest is service
   code with tests.
3. §4 (R-06 – R-11), including R-07's validation queries. Then run P4-6 on a scratch copy
   again before touching a live database.
4. R-24, then the live runbook (§7) one environment at a time, then R-25 and R-26.
5. R-16 with R-28, then R-27, then the rest of §5 and §6.
6. R-33 (the frontend plan) can run alongside steps 2–5. Its Phase 0 access fixes are
   small and independent of everything above.
