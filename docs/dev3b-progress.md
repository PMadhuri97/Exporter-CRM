# Developer 3B — progress

Deals, buyers, storage and documents (architecture §9.3, tasks L3-01b, L3-05 … L3-11b).
Running note, per prompt §8. Newest phase last.

Being built in four phases, each independently committable, in the prompt's own task
order so no phase depends on a later one:

| Phase | Tasks | State |
|---|---|---|
| 1 | L3-01b contracts, L3-07 storage, L3-08 scan step | **done** |
| 2 | L3-05 deal record, L3-06 buyer | not started |
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
