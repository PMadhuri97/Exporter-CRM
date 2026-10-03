# Developer 2 — what is done, and what is left

**As of 2 October 2026**, with `feature/handover-snapshot` (F2, 2.1–2.3) merged into `main`
and Developer 3's 3.1–3.6 merged after it. Lane: deals, the handover guard, required
documents, the buyer migration and the invoicing branch (`developer-allocation.md` §4).
Re-check the code before trusting a "not built" below — this file says what was true on
that date.

| | |
|---|---|
| **Done (merged)** | F2, 2.1, 2.2, 2.3 |
| **Done, awaiting merge** | **2.5** (every §2 gap closed); **2.4** (0034), **2.7**; **2.8** (0036), **2.9**; **2.11**; **2.12**; **2.6** — code complete (0038, 0039) and **never run** |
| **Can start now** | Nothing is blocked |
| **Waiting on Developer 3** | — |
| **Still owed** | 2.6's **run** on each environment (`pg_dump`, dry run, Compliance reviews the name-only duplicates, apply, validate), which is also what unblocks 2.10 |
| **Final integration** | 2.12 — done |
| **Next free migration number** | **0041** — 0034, 0036, 0038 and 0039 are this lane's; 0032, 0033, 0035, 0037 and 0040 are Developer 3's (`contracts/migration-register.md` §1) |

**The merge order changed.** The allocation planned F1 → F3 → F2; what happened was
**F1 → F2 → F3**. F2 therefore declared `BranchFlagReader` itself and stubbed around the rest
of Developer 3's interfaces, and **most of the remaining lane now waits on F3** — which is
Developer 3's next PR.

---

## 1. Done

| Task | What exists | Proof |
|---|---|---|
| **F2** | `onboarding_0028_deal_foundation`: `deal.buyer_company_id` (FK → company, `RESTRICT`, `ck_deal_buyer_is_not_the_seller`), `deal.handover_snapshot`, `deal.seller_gst_registration_id` (FK → `exporter_gstin.id`, `RESTRICT`). The guard as an ordered list of injected conditions (`domain/handover_conditions.py`). `DealResponse.buyer_company` (masked summary; `pipeline_status` is `null` until F3). `CompanyDealsList.tsx` stub, final props `{ companyId, as }` | `test_l3b_handover_conditions.py`, `test_l3b_handover_snapshot.py` (`buyer_company` shape), `CompanyDealsList.test.tsx` |
| **2.1** (P2-7) | `onboarding_0029_deal_snapshot`: the snapshot is written on `HANDED_OVER`, backfilled for older handed-over deals (`snapshot_source = 'backfilled_from_deal_buyer'`), and frozen by `prevent_terminal_deal_change()` | `test_l3b_handover_snapshot.py` (runs the real `_BACKFILL`) |
| **2.2** (P2-5a) | `onboarding_0030_deal_req_docs`: versioned, append-only `deal_required_document`, seeded with `PRE_SHIPMENT` (IQ-10). `GET/POST /settings/deal-required-documents` (read staff, write ADMIN; 409 `DEAL_REQUIRED_DOCUMENT_CHANGED` on concurrent edits). Settings screen | `test_l3b_deal_required_documents.py`, `DealRequiredDocumentsPage.test.tsx` |
| **2.3** (P2-5b) | Guard condition 3 is **live**: "missing required documents: …", counting only `AVAILABLE` documents (IQ-11). `sample_data_deals.py` and the main e2e upload a pre-shipment document | `test_l3b_handover.py`, `test_crm_end_to_end.py` |

The guard's state is tabulated in `contracts/deal-and-buyer.md` §6.1: conditions 1–3 live,
4–6 waiting.

---

## 2. Gaps in what is merged — fix inside 2.5

1. **Conditions 4 and 5 are inert.** `DealService.__init__` injects only
   `RequiredDocumentsPolicy`; compliance is still `NoComplianceFacts`, although Developer 1's
   real reader exists (`application/compliance_facts.py`, `ComplianceFactsService(db)`,
   async). Consequence today: **an expired Clear does not block a handover**
   (`open-items.md` §1 says so), and a buyer's sanctions/AML are not checked.
2. **Two copies of one interface.** `handover_conditions.py` re-declares
   `ComplianceFactsReader` and `PartyComplianceFacts` as Protocols; Developer 1's published
   ones are in `domain/compliance_facts.py`. They are structurally compatible today. Import
   Developer 1's (or keep the structural one and add a test that Developer 1's service
   satisfies it) so the two cannot drift.
3. **The expiry message is wrong once the reader is wired.** `seller_compliance_is_current`
   reports "the company's background check has expired" whenever `is_clear_current` is
   false — including a seller that is not `CLEAR` at all, which condition 2 already reports.
   Gate it on `facts.is_clear and not facts.is_clear_current`, and say the date, as
   Developer 1 asked: "the background check expired on `clear_expires_at`" (P3-3b).
4. **Only the seller row is share-locked.** P4-7 wants both companies share-locked, sorted by
   `customer_id`, so a handover and a flag on the buyer cannot race. Developer 1 then adds
   the "handover vs a flag on the buyer company" concurrency test
   (`dev1-remaining-work.md` §2) — tell them when 2.5 merges.

---

## 3. Remaining lane tasks

Specs are in allocation §4; this column says what is true on `main` now.

| # | Task | State on `main` | Needs | Notes |
|---|---|---|---|---|
| 2.4 | `PUT /deals/{id}/buyer {buyer_company_id}` (seller ≠ buyer); "needs buyer" reads `buyer_company_id`, else `deal_buyer`; snapshot from the buyer company; set-once trigger rule for `buyer_company_id`; deal page mounts `CompanyPicker` and `CompanyComplianceSummary` | `PUT /deals/{id}/buyer` still takes the **legacy `deal_buyer` form**; nothing writes `buyer_company_id`; the deal page shows `buyer_company` read-only when present | `CompanyPicker` (Developer 3, F3 stub) | Backend can start now. Keep `BuyerChecks` mounted **only** for deals whose buyer is still a `deal_buyer` row; mount `CompanyComplianceSummary` (`{ companyId }`: the gauge with "Awaiting approval" / "Re-KYC due" badges, expiry, sanctions/AML, a link to the company's background-check panel) for the seller and the buyer company. Changes the request schema → regenerate artifacts |
| 2.5 | Compliance conditions with `ComplianceFactsReader` (P3-3b, P3-4, P4-7); buyer falls back to `for_legacy_buyer`; share-lock both companies sorted by `customer_id` | condition code written, **inert** (§2) | — (Developer 1's reader is on `main`) | **Start here.** Fixes §2's four gaps. Fakes: `StaticComplianceFactsReader`, `party_facts(...)` in `tests/fixtures/compliance.py`. Any test that clears a company now needs `record_required_checks(company_id)` (same file) and two users — `approve_as(checker, company, maker=…)` (services) or `propose_and_approve(client, company, maker_token=…, checker_token=…)` (HTTP). Then update `deal-and-buyer.md` §6.1's table |
| 2.6 | **Code done; never run.** `python -m app.modules.onboarding.migrate_deal_buyers --dry-run / --apply --run-id / --validate / --rollback`, with `deal_buyer_company_map` (0038), 12 tests over §17.2's edge cases, and §17.2's seven validation queries. Migration **0039** came out of writing those tests: 0036 had frozen `buyer_company_id` so hard that a *closed* deal could never be linked, which §17.2 requires. **`--rollback` writes nothing** — it reports what a run did and says the `pg_dump` is the only way back, because both `deal.buyer_company_id` and `verification_result.subject_company_id` are set-once and frozen, so §17.2's logical rollback is not available in the shipped schema. An earlier version attempted it and would have failed halfway, after clearing some results | absent | `CompanyDirectory` (F3); Developer 3's **3.2 reports** to size it; 2.4 merged | `subject_company_id` is set-once and then frozen by `trg_verification_result_input_immutability`; never touch `entity_type` / `entity_reference` / `subject_snapshot`. From then on every read treats the row as the buyer company's check (inputs, facts, rule B, the company's verification list) and later reviews go on the buyer company's timeline with `deal_id`; `buyer_checks` / `for_legacy_buyer` keep reading it for old deals (`contracts/background-check.md` §12.2). Run order: §5. The dry-run report truncates: 568 problem rows and 73 candidates on one line was the first version, and unreadable |
| 2.7 | `GET /exporters/{id}/deals?as=buyer`; `CompanyDealsList` full version; buyer company's history includes deal rows where it is the buyer (D8 applies) | list is seller-only; `as="buyer"` shows "not available yet" | — | Can start now. Developer 3 mounts the list in 3.9 |
| 2.8 | Invoicing branch: set before handover; must belong to the seller; set-once trigger rule; picker listing the seller's active registrations | column exists, nothing writes it | **Developer 3's 3.12** | **Do not ship before 3.12.** Until 3.12 a company edit that drops a GSTIN deletes the row (`delete-orphan`), and with a deal pointing at it that delete hits the `RESTRICT` FK. "Active registrations" also needs 3.12's `active` column |
| 2.9 | "invoicing branch <state> is flagged" via `BranchFlagReader`; "record the invoicing branch" when the seller has an active registration (IQ-20) | condition 6 written, inert (`NoBranchFlags`); the second rule absent | `BranchFlagReader` (F3 stub, 3.14 real); 2.8 | Inject Developer 3's reader into `DealService`; the condition's code does not change |
| 2.10 | Retire `deal_buyer` writes (trigger refuses INSERT/UPDATE; table kept); drop the legacy `buyer` from the response after one release; rewrite decision 9 in `architecture.md`, `deal-and-buyer.md`, `event-envelope.md` | absent | 2.6 applied in **every** environment | Then tell Developer 1 to delete `BuyerChecks.tsx` (`dev1-remaining-work.md` §2) |
| 2.11 | **Done.** `TradeHistoryPanel` mounted on the deal page in a `Panel` of its own, `{ sellerId: deal.company_id, buyerId: deal.buyer_company.company_id, dealId: deal.id }` | absent | `TradeHistoryPanel` (F3 stub, 3.22 full); 2.4 | **Only on a deal with a buyer company**, and absent rather than empty otherwise: a deal whose buyer is still a `deal_buyer` row has no second company to pair the seller with, and an empty panel would imply the two had never traded |
| 2.12 | **Done.** The main path now runs `POST /companies/match` (new → create → possible duplicate) → buyer **company** → invoicing branch → paperwork → screening → handover → `POST /deals/{id}/payment-outcome`, then asserts the relationship is readable from **both** sides and that `trade` is among the seller's history dimensions | covers two users + required document; no buyer company | 2.4, Developer 3's 3.21 | Final integration (allocation §6). Keeps the `checker` token and rule-B checks Developer 1 added. `gst_registration` is deliberately **not** in the dimension assertion: this path's GSTIN arrives through create, which writes no such row |

---

## 4. What you wait on, and who waits on you

| You need | From | For |
|---|---|---|
| `CompanyPicker` | Developer 3, F3 (stub) / 3.10 (full) | 2.4's screen |
| `CompanyDirectory.create_buyer_company` | Developer 3, F3 | 2.6 |
| 3.2's per-environment reports | Developer 3 | sizing 2.6 |
| `exporter_gstin` evolved in place (no deletes, `active`) | Developer 3, 3.12 | 2.8 |
| `BranchFlagReader` | Developer 3, F3 (stub) / 3.14 (real) | 2.9 |
| `TradeHistoryPanel`; recorded outcomes | Developer 3, F3 / 3.22; 3.21 | 2.11; 2.12 |

| Waiting on you | Who | For |
|---|---|---|
| 2.5's buyer share-lock | Developer 1 | the "handover vs flag on the buyer company" concurrency test |
| 2.6 applied everywhere, then 2.10 | Developer 1 | deleting `BuyerChecks.tsx` |
| 2.6 applied | Developer 3 | running the relationship backfill (3.23) |
| 2.7 | Developer 3 | `CompanyDealsList as="buyer"` on the company page (3.9) |

---

## 5. Operational order on live databases — do not reorder

From allocation §6. Not a coding dependency; the order things run on a live database.

1. `pg_dump`.
2. Your buyer migration **P4-6** (task 2.6, after 2.4 merges): dry run, Compliance reviews
   the name-only duplicates (IQ-8), apply, validation queries.
3. Developer 3's relationship backfill **P5-5** (3.23).
4. Your **P4-10** (task 2.10), only once every environment has passed step 2.

---

## 6. Before every PR

- `alembic heads` prints one; your migration's `down_revision` is the head **at merge
  time**; take the next free number from the register (and update its §1); id ≤ 32
  characters.
- A data migration: `pg_dump` first, a dry run and validation queries, read the current
  state rather than assume it, and say in the docstring how it rolls back.
- Request or response schema changed → regenerate `frontend/openapi.json` and
  `frontend/src/lib/api/schema.ts`; never hand-merge them.
- New route → a row in your block of `test_route_authorization.py`, D8 (DEVELOPER)
  handling, and a masking test for OPERATIONS and DEVELOPER on any new response shape.
- The guard: Developer 1 does not touch it, and you do not touch Developer 1's reader —
  change which provider `DealService` hands in, not a condition's caller.
- Gates (`development.md` §7). Baseline on 2 October 2026: backend 4,932 passed, 7
  skipped, 27 xfailed; the one failure,
  `idempotency/test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index`, also fails on
  `main` (query-planner choice as the ledger table grows) — not yours to chase. Frontend 39
  files / 372 tests; ruff 16; import-linter 19 kept / 0 broken.
