# Developer 3B — progress

Deals, buyers, storage and documents (architecture §9.3, tasks L3-01b, L3-05 … L3-11b).
Running note, per prompt §8. Newest phase last.

Being built in four phases, each independently committable, in the prompt's own task
order so no phase depends on a later one:

| Phase | Tasks | State |
|---|---|---|
| 1 | L3-01b contracts, L3-07 storage, L3-08 scan step | **done** |
| 2 | L3-05 deal record, L3-06 buyer | **done** |
| 3 | L3-09 document records | **done** |
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

---

## Phase 3 — the document record

### Delivered

- `migrations/onboarding_0019_documents.py`: three enums and `crm_document`, parent
  `onboarding_0018_deal_buyer`. One head; upgrade → downgrade → upgrade verified.
- `domain/entities/document_enums.py` (ten categories, each carrying the owner it
  belongs to; four sources) and `crm_document.py`.
- `domain/document_views.py`, `infrastructure/repositories/crm_document_repository.py`.
- `infrastructure/document_type_loader.py` plus
  `deployments/gitops/reference-data/crm/documents/document-types.yaml` — 31 types
  across all ten categories.
- `application/document_service.py`: upload (validate → store → scan → record),
  lists, the category catalogue, download links and content.
- `api/document_router.py` (8 operations) and `api/schemas/document.py`.
- Frontend: `api/documents.ts`, `hooks/documents.ts`, document types.
- 58 tests (`test_l3b_document_rules.py`, `test_l3b_documents.py`), including a
  direct-SQL violation test for each of the five new constraints.

### A bug I caught before it shipped

**`/documents/content` was declared after `/documents/{document_id}`.** FastAPI
matches in declaration order, so a GET of the content path would have been read as a
document id and refused as an invalid UUID — every download broken, and nothing in a
type-checker or a unit test would have said so. The content route now comes first,
with a comment saying why, and the API test fetches a real document through the link
so the ordering is pinned. The same trap 3A documented for `/exporters/follow-ups`.

### Decisions

1. **Types are settings, categories are code.** The ten categories are a database
   enum because each carries a rule — which owner it may be filed against — and the
   server enforces it. Types are a GitOps YAML file, so adding one needs no release
   and no migration (architecture §3.4). A test writes its own settings file and
   proves a brand-new type works without touching code.
2. **Exactly one owner, enforced with `num_nonnulls(company_id, deal_id) = 1`** —
   one expression that stays correct if a third owner kind is ever added. Both
   halves (neither owner, both owners) have direct-SQL tests.
3. **Validate, then store, then record.** A refused upload leaves neither a row nor
   an object; the reverse order would litter the disk with orphans for every
   rejected request. Tested by asserting the storage root is empty after each kind
   of refusal.
4. **`POST` for a download link, not `GET`.** It mints a credential rather than
   reading a resource, and should not be prefetched or cached. The link is refused
   for any document that is not `AVAILABLE`, and the scan status is re-checked when
   the content is fetched, so a link minted while a document was clean stops working
   if a later verdict quarantines it.
5. **The signature covers the key *and* the expiry**, and an authentic signature
   over a passed expiry is still refused — tested, because that is the case a naive
   implementation gets wrong.
6. **Content is served as `attachment` with `nosniff`.** An HTML or SVG document
   served inline from this origin would run as this application.
7. **No response carries the storage key** (decision D8): it is an internal address,
   and publishing it invites clients to build their own URLs.
8. **The file name never enters the key** — it is a column. A test uploads
   `../../etc/passwd invoice.pdf` and asserts the key contains neither the name nor
   `passwd`.
9. **Uploads bypass `apiRequest` on the frontend**, because that helper sets a JSON
   content type and serialises the body; the multipart boundary has to come from the
   browser. It still takes the access token from the same place, so an upload
   refreshes like any other call.

### Housekeeping

- `# noqa: E402` on my appended imports in the three shared index files, matching the
  style 3A established there — the anchor design puts imports after code by
  construction, and 3A documented the same exemption.
- The 9 `ruff` findings left in `app/modules/onboarding` are all pre-existing:
  verified by running `ruff` against those same files as they stand at `447c6ba`,
  before any of my work.

### Gate §7.6 — unchanged, and still true

The scanner is still the labelled pass-through: **every document in this build was
"scanned" by something that checks nothing**, and `scanner_name` says `pass-through`
on every row and in every API response so no screen can imply otherwise. Still no
S3, no Object Lock, no KMS, no retention lock.

### Verification

- 186 L3B tests pass together (81 storage + 47 deal + 58 document).
- Route-authorisation suites pass (362) with a row and a refusal test for each new
  route. The two multipart uploads are covered by their own refusal tests instead of
  the shared table, which sends JSON — a multipart route rejects a JSON body at
  parsing, before the gate, which would prove nothing about the gate.
- `lint-imports` 19 kept, 0 broken. `alembic heads`: one
  (`onboarding_0019_documents`).
- Frontend: typecheck clean, `lint` 0 errors, 78 tests, `build` succeeds.
- `openapi.json` and `schema.ts` regenerated; artifact contract test passes.
