# Contract — storage and documents

**Owner:** Developer 3B · **Port:** `onboarding/domain/storage.py` · **Implementations:** `onboarding/infrastructure/storage/` · **Table:** `onboarding.crm_document` · **Migration:** `onboarding_0019_documents`

**Used by:** Developer 4 (evidence at decision time, plan §8.2), Developer 3A (nothing
— documents are not part of the conversation gauge), Developer 2 (nothing).

**Scope split.** Phase 1 publishes this whole file and builds §1–§4 (the port, the
local-disk implementation, the key shape, the scan step). §5 and §6 — the document
record and its routes — are Phase 3. §7 is Phase 4. Nothing in §5–§7 exists yet, and
this file says plainly where that is so.

Architecture §3.4 is the source; where this file is more specific, it is filling in a
decision the architecture left to implementation, and says so.

---

## 1. The port, and why there is one

`StoragePort` is a `Protocol` in `onboarding/domain/storage.py`. Four operations:

```python
async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject
async def open_link(self, key: str, *, expires_in: timedelta) -> DownloadLink
async def read(self, key: str) -> bytes
async def delete(self, key: str) -> None
```

- **The prototype has one implementation**, `LocalDiskStorage`. S3 with Object Lock and
  KMS is a second implementation of the same port, later (decision D8, gate §7.6).
  Local disk stays for development and tests either way.
- **It is a `Protocol`, not a base class.** An implementation satisfies it without
  importing it, which is the convention throughout this repository (consumer-owned
  ports) and what lets a test pass a fake without a subclass.
- **It knows nothing about documents.** No `document_id`, no category, no owner: it
  moves bytes at a key. The document record is §5, and it is the *caller* that decides
  a key belongs to a document. Keeping the port that narrow is what makes the S3
  swap a change in one file.

### 1.1 What the port returns

| Type | Fields | Why |
|---|---|---|
| `StoredObject` | `key`, `size_bytes`, `content_type` | `size_bytes` is measured by the implementation from what it actually wrote, never taken from the client's claim. |
| `DownloadLink` | `url`, `expires_at` | `url` is opaque to the caller. Local disk returns an API path carrying a signed token; S3 will return a presigned URL. A caller that parses it is wrong. |

---

## 2. The key shape

```
{env}/{owner_type}/{owner_id}/{source}/{document_id}{ext}
```

Architecture §3.4, fixed. Built by `build_storage_key(...)` in `domain/storage.py`, which
is pure and has no I/O, so the shape is tested without touching a disk.

- `env` is `settings.ENVIRONMENT` lowercased (`development`, `test`, `production`), so
  one bucket can hold several environments without them colliding.
- `owner_type` is `company` or `deal`; `owner_id` is that row's UUID.
- `source` is the document's source, lowercased (§5.3).
- `document_id` is the document row's UUID, and `ext` comes from the **sniffed**
  extension for the stored content type, never from the uploaded file name.

**Only the relative key is stored, never a cloud address** (decision D8). No bucket, no
host, no `s3://`. Changing provider must not require touching a single row.

**The original file name and type never appear in the key.** They are columns on the
document row (§5.2). Two reasons, both from §9.3's "Watch out for": a user-supplied
name inside a key is a path-traversal surface, and a key that embeds a name cannot
survive a rename.

### 2.1 Keys are validated before any I/O

`LocalDiskStorage` refuses, before opening anything:

- a key that is absolute, or contains `..`, a backslash, a NUL byte, or a
  drive-letter prefix;
- a key that, once resolved against the configured root, lands outside it.

The second check is the one that actually matters — it catches a traversal the first
check's blocklist misses — and it is done with `Path.resolve()` and
`is_relative_to(root)`, not with string comparison. A refused key raises
`StorageKeyRefusedError` (§8) and touches no file.

---

## 3. Where local-disk files live

`STORAGE_LOCAL_ROOT`, an environment variable, default
`<repo>/backend/.local-storage`. Everything the implementation writes stays under it.
The default is inside the repository because a developer losing uploads on reboot is
more surprising than a directory to ignore; `.local-storage/` is in `.gitignore`.

Directories are created as needed, with the parents of the key. Nothing else in the
tree is ever removed, including on `delete` — only the one file goes.

---

## 4. The scan step, and the placeholder that is not a scanner

Architecture §3.4 and assumption A9.

| Status | Meaning | Can it be opened? |
|---|---|---|
| `PENDING_SCAN` | The default on every upload. | **No** |
| `AVAILABLE` | A clean result came back. | Yes |
| `QUARANTINED` | The scanner found something. | **No**, ever |
| `SCAN_FAILED` | The scanner could not decide. | **No**, ever |

- **Every upload lands `PENDING_SCAN`**, whatever the scanner does next, and a document
  that is not `AVAILABLE` is refused to **everyone** — not by role, by state. There is
  no role, and no flag, that opens a quarantined file.
- `QUARANTINED` and `SCAN_FAILED` **raise an alert** (a logged event at warning level
  carrying the document id and the scanner name; there is no alerting system to call
  yet, and inventing one is out of scope).
- **The prototype's scanner is a labelled pass-through.** `PassThroughScanner.name`
  is `"pass-through"`, stored lowercase on the document row exactly as a provider is
  stored `"manual"` (§7.5, D4), and displayed uppercase. It returns clean for
  everything.
- **It is not a scanner and must never read as one.** The screen says so (§7), the
  data says so, and gate §7.6 blocks real exporter documents until a real scanner
  (GuardDuty Malware Protection for S3, or ClamAV) is behind this interface. A fake
  "passed" that looks real is the specific failure Developer 4's placeholder clean-up
  exists to prevent.

### 4.1 The scanner is its own port

```python
class ScannerPort(Protocol):
    name: str
    async def scan(self, key: str, content: bytes) -> ScanOutcome
```

`ScanOutcome` carries the resulting status and an optional detail string. A real
scanner replaces this one implementation and nothing else — which is the whole reason
it is separated from `StoragePort` rather than folded into `put`.

---

## 5. The document record — Phase 3 builds this

Nothing in this section exists yet.

### 5.1 Owner: exactly one of a company or a deal

Architecture §3.4: a document belongs **either** to a company or to a deal. Two
nullable foreign keys, `company_id` and `deal_id`, and a database `CHECK` that exactly
one is set. Both get a direct-SQL violation test (register rule): a row with neither,
and a row with both.

### 5.2 Columns

`category`, `document_type`, `source`, `file_name`, `content_type`, `size_bytes`,
`uploaded_by`, `uploaded_at`, `scan_status`, `scanner_name`, `storage_key`.

`storage_key` is unique: two rows pointing at one object would make `delete`
ambiguous.

### 5.3 Categories are fixed and server-checked; types are settings

Ten categories, each belonging to a company, a deal, or both (architecture §3.4):

| Category | Belongs to |
|---|---|
| `ENTITY_KYC`, `COMPLIANCE_SCREENING`, `COMPANY_MARKET_REVIEW` | company |
| `PRE_SHIPMENT`, `SHIPPING`, `CUSTOMS_AND_REGULATORY`, `BUYER` | deal |
| `BANKING`, `INSURANCE`, `OTHER` | both |

The server refuses a category filed where it does not belong, and the screen offers
only the categories valid for where the user is. Document **types** within a category
are seeded settings, so a new type needs no code change and no migration.

`COMPANY_MARKET_REVIEW` with source `SYSTEM` is for later (D16): the category exists,
and nothing in the prototype generates into it.

Sources: `RXIL`, `EXPORTER_UPLOAD`, `INTERNAL`, `SYSTEM`.

---

## 6. Routes — Phase 3 builds this

`POST` upload, `GET` list (by company or by deal), `GET` download. Roles per §3.7:
OPERATIONS, COMPLIANCE and ADMIN upload and read; DEVELOPER reads; API_USER reaches
nothing. The download route refuses any document that is not `AVAILABLE` to every
role, and a link that has expired, both tested.

---

## 7. Handover — Phase 4 builds this

`deal.handed_over` carries the list of document ids the handover rested on, as a
snapshot (architecture §3.6), so a later upload cannot change what the lending team
was given. `OnboardingEventPublisher.deal_handed_over` already exists and already has
this payload; Phase 4 calls it and writes no new publisher.

---

## 8. Error codes

All of these are **Phase 3**: they are the HTTP mapping of a domain rule, and
until there is a route there is nothing to map. Phase 1 raises plain domain
errors — `StorageKeyError`, `UnsupportedContentTypeError`,
`DocumentNotServableError` — and adds nothing to `onboarding/exceptions.py`,
because an exception no boundary raises is dead code in a shared file.

| Code | Status | Raised from | When |
|---|---|---|---|
| `STORAGE_KEY_REFUSED` | 422 | `StorageKeyError` | A key is absolute, escapes the root, or contains a forbidden segment. |
| `STORAGE_OBJECT_NOT_FOUND` | 404 | `FileNotFoundError` | No object at that key. |
| `DOCUMENT_CONTENT_TYPE_NOT_SUPPORTED` | 422 | `UnsupportedContentTypeError` | A content type with no extension in the allow-list. |
| `DOCUMENT_NOT_AVAILABLE` | 409 | `DocumentNotServableError` | Content requested for a document that is not `AVAILABLE`. |
| `DOCUMENT_CATEGORY_NOT_ALLOWED` | 422 | — | A category filed against the wrong owner type. |
| `DOCUMENT_LINK_EXPIRED` | 403 | — | A download token past `expires_at`. |

---

## 9. What this contract does not cover

- **The legacy `onboarding_document` table** (audit note E34) hangs off
  `onboarding_request`. It is not this record, and it is not extended, reused or
  renamed.
- **Object Lock, KMS and seven-year retention** are gate §7.6 items, not built.
- **Virus scanning**, as above: a pass-through only.
