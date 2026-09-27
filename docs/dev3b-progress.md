# Developer 3B — progress

Deals, buyers, storage and documents (architecture §9.3, tasks L3-01b, L3-05 … L3-11b).
Running note, per prompt §8. Newest phase last.

Being built in four phases, each independently committable, in the prompt's own task
order so no phase depends on a later one:

| Phase | Tasks | State |
|---|---|---|
| 1 | L3-01b contracts, L3-07 storage, L3-08 scan step | **done** |
| 2 | L3-05 deal record, L3-06 buyer | **done** |
| 3 | L3-09 document records | not started |
| 4 | L3-10 handover, L3-11b screens | not started |

---

## Phase 1 — contracts, the storage port, and the scan step

### Delivered

- `docs/contracts/deal-and-buyer.md` and `docs/contracts/storage-and-documents.md`
  (L3-01b). **Not yet acknowledged** by 3A, Dev 2 or Dev 4 — the task is not
  complete until they have each confirmed they read them, and 3A has already merged
  their own work, so the deal/buyer contract needs their eyes on §5 (seam S1) in
  particular.
- `domain/storage.py`: `StoragePort`, `ScannerPort`, `DocumentScanStatus`,
  `build_storage_key`, `is_safe_key`. Pure — no I/O, no settings, no database.
- `infrastructure/storage/`: `LocalDiskStorage`, `PassThroughScanner`, `config.py`.
- `application/storage_service.py`: `StorageService` — stores, then scans, and refuses
  content for anything that is not `AVAILABLE`.
- 81 unit tests across `tests/unit/test_l3b_storage_key.py`,
  `test_l3b_local_disk_storage.py`, `test_l3b_storage_service.py`.

### Decisions I had to make

1. **`DocumentScanStatus` lives in `domain/storage.py`, not `document_enums.py`.** The
   scanner port returns it, and a port must not import the document entity's module —
   the dependency runs the other way. Phase 3's `crm_document` imports it from here.
2. **Two ports, not one.** `ScannerPort` is separate from `StoragePort` so replacing
   the pass-through with GuardDuty or ClamAV touches one implementation and nothing
   else. Prompt §6.2 asked for the scan status on the storage port; splitting it is a
   deviation in shape, not in behaviour, and the contract records it.
3. **An allow-list of content types**, in `storage_service.py`. The extension goes
   into the storage key, so a type with no known extension is refused rather than
   stored with a guessed one. Deriving the extension from the uploaded file name would
   put user-controlled text in a path, which §6.1 forbids.
4. **Download links are signed over key *and* expiry**, keyed on `SECRET_KEY`. Local
   disk has no presigned URLs, so the link is an API path plus a signature; signing the
   expiry inside the material is what stops a link's lifetime being extended by editing
   the query string. Phase 3's download route verifies it.
5. **No exceptions added to `onboarding/exceptions.py` yet.** The codes in the storage
   contract §8 are the HTTP mapping of a domain rule, and there is no route until
   Phase 3 — an exception no boundary raises is dead code in a shared file. My anchor
   there is untouched and waiting.
6. **`STORAGE_LOCAL_ROOT` is read in my own module config**, not added to
   `platform.configuration.Settings`: that class is platform-wide and not mine to
   extend. `Settings.ENVIRONMENT` is read (never written) for the key's first segment.
   Default root `backend/.local-storage`, added to `.gitignore`.

### Contradictions with the prompt, for whoever maintains it

1. **The migration head is `onboarding_0016_engagement`, not
   `onboarding_0020_retire_lifecycle`.** §3 of the prompt was written before 3A merged.
   The consequence is the one §3 already anticipated: 0018's `down_revision` is
   `onboarding_0016_engagement`, 3A landed first, and **I do not re-parent**.
2. **`onboarding/integrations/object_storage` does not exist**, so §6.2's "replace it"
   could not be carried out as written. The real scaffold is
   `app/integrations/object_storage`, and **I left it in place.** Its README says
   "Vendor implementations only. The port is owned by the consuming module
   (ARCHITECTURE.md §8)" — which is exactly the design I built, and it is the
   documented home for the future S3 *vendor* implementation. Deleting it would remove
   the place S3 is supposed to go and break the uniformity of 14 sibling scaffolds.
   Flagging rather than deciding: if audit note E34 meant something else, say so and I
   will retire it.
3. **`exporter_profile.background_check` still does not exist** (Dev 4's 0015 has not
   landed), so L3-10's guard remains blocked exactly as §6.6 predicted. Nothing in
   Phase 1 depends on it.

### Gate §7.6 — what this phase does **not** give you

- **There is no virus scanner.** `PassThroughScanner` returns clean for everything and
  says so in its name (`"pass-through"`, stored lowercase), in its log line, and in the
  contract. It must not be mistaken for a scan. Real exporter documents stay blocked
  until GuardDuty Malware Protection for S3 or a self-hosted ClamAV is behind
  `ScannerPort`.
- **There is no S3, no Object Lock, no KMS, and no retention lock.** Local disk only.
  Seven-year AML retention is not satisfied by anything here.

### Verification

- 81 new unit tests pass; backend suite otherwise unchanged (Phase 1 adds no route,
  no migration, no entity, and touches no shared file except `.gitignore`).
- `ruff check` clean on every file this phase added. The 9 pre-existing findings
  elsewhere in `app/modules/onboarding` are untouched and not mine.
- `lint-imports`: 19 contracts kept, 0 broken.
- `alembic heads`: one revision (`onboarding_0016_engagement`) — this phase adds no
  migration.

---

## Phase 2 — the deal record and its buyer

### Delivered

- `migrations/onboarding_0018_deal_buyer.py`: `deal_stage_enum`, `deal` and
  `deal_buyer`. Parent `onboarding_0016_engagement`, one head before and after,
  upgrade → downgrade → upgrade verified.
- `domain/entities/deal_enums.py`, `deal.py`, `deal_buyer.py`; `domain/deal_views.py`.
- `application/deal_service.py`: `open_deal`, `transition_stage`, `set_buyer`,
  `allowed_stage_moves`, and the A5 guard's read half.
- `api/deal_router.py` (5 routes) and `api/schemas/deal.py`.
- `infrastructure/repositories/deal_repository.py`, `deal_buyer_repository.py`.
- `sample_data_deals.py` — three §3.9 deals, converging (0 on a repeat run).
- Frontend seam S2 published: `api/deals.ts`, `hooks/deals.ts`, deal types.
- 47 tests (`test_l3b_deal_stage_rules.py`, `test_l3b_deal_buyer.py`), including a
  direct-SQL violation test for each of the six new constraints.

### Seams

- **S1 is in.** `open_deal` calls 3A's
  `ConversationService.mark_ready_now_for_opened_deal` in the same transaction, and
  a test asserts the gauge moves, that 3A's history row carries the `deal_id`, and
  that a second deal on an already-ready company writes no second history row
  (their idempotence). 3A's commit landed first, so the call went in immediately
  rather than as a follow-up.
- **S2 is published.** `openDeal`/`useOpenDeal` and the deal types are exported
  through the barrels the seam commit wired. 3A's Conversation panel does not yet
  offer the prompt — their work merged before this existed — so that is a small
  follow-up for them, not a blocker for me.

### Two bugs I made and fixed

1. **`db.get(ExporterProfile, company_id)` looked up the wrong column.**
   `customer_id` is the company's business key; the table's primary key is the
   inherited `id`. It found nothing for every company, so the handover guard raised
   `DEAL_COMPANY_NOT_FOUND` on a company that plainly existed. Ten tests failed on
   it. Now selects by `customer_id`.
2. **My deal hooks invalidated a query key that does not exist.** I wrote
   `['conversation', customerId]`; 3A's keys are `['exporterConversation', …]` and
   `['conversationHistory', …]`. A query key is a string, so it type-checked
   perfectly and would simply never have invalidated anything — the gauge would
   have shown a stale value after opening a deal. Found by grepping their hooks and
   comparing every key I touch against the real list.

### Decisions

1. **The buyer is its own table** (`deal_buyer`), not columns on `deal` — the
   contract §3 records why: Developer 4 attaches buyer checks to the buyer, and a
   check pointing at the deal could not distinguish "about the buyer" from "about
   the deal".
2. **A reason on a non-withdrawal is refused, not dropped** — silently discarding
   it would leave the operator believing it was stored.
3. **A terminal deal's buyer cannot be edited.** A handed-over deal's buyer is what
   the lending team was given; a withdrawn deal's is history.
4. **`event_type="deal_buyer_changed"`** on a `deal` history row, with the changed
   field names in `details`. A `buyer` dimension would need a change to
   `history-row.md` §2, which is Developer 1's.
5. **The handover guard is written but currently refuses everything.** It reports
   *why* — and while Developer 4's 0015 is missing, the reason is "the background
   check is not recorded yet". "Not recorded" is never treated as "clear": that
   would hand a deal to the lending team on the strength of a column that does not
   exist. `allowed_stage_moves` omits the move, so the screen explains instead of
   offering a button that 409s.
6. **Sample data stops at the honest state.** Architecture §3.9 wants one of company
   B's deals *handed over*, which no deal can legitimately reach yet, and company
   C's blocked *because its check is flagged*, which is the same missing column.
   Writing those stages directly would put rows in the database that the service
   would never have produced, with no history behind them. Both of B's deals stop at
   `GATHERING_PAPERWORK` with their buyers recorded; C's is `OPEN`. Phase 4 finishes
   this when 0015 lands.

### Environment findings (not code, but they cost time)

1. **The suite cannot run in the app container without the frontend mounted.**
   `tests/contract/test_openapi_artifact_is_current.py` resolves the repo root from
   the backend package, so inside the container it looks for `/frontend/openapi.json`
   and only `./backend` is mounted. Three tests fail for that reason alone. I mount
   `./frontend:/frontend:ro` in a local compose override; a host run never sees it.
2. **The committed `openapi.json` embeds `info.title`, which comes from `APP_NAME`.**
   `backend/.env` here sets "Aner Settlement Platform" while the committed artifact
   holds the `Settings` default "Business Platform", so the artifact test fails on a
   title, and regenerating naively would commit a title that breaks the test for
   everyone whose `.env` differs. I generate with `APP_NAME` pinned to the default.
   **Worth raising with Developer 1** (L1-14 owns regeneration): an artifact that
   embeds an environment-specific value is a trap for whoever regenerates next.
3. The artifact is **compact JSON**, not indented — regenerate exactly the way
   `pnpm generate:api` does, or the diff is 10,000 lines instead of one.

### Verification

- 47 new tests pass; route-authorisation suites pass (338) with a row and a refusal
  test for each of the five new routes.
- `ruff` clean on every Phase 2 file; `lint-imports` 19 kept, 0 broken.
- `alembic heads`: one revision (`onboarding_0018_deal_buyer`).
- Frontend: typecheck clean, `lint` 0 errors, 78 tests pass, `build` succeeds.
- `openapi.json` and `schema.ts` regenerated and current (contract test passes).
