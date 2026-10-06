# Contract — the deal and its buyer

**Owner:** Developer 2 (post-demo allocation; Developer 3B before it) · **Tables:**
`onboarding.deal`, `onboarding.deal_buyer`, `onboarding.deal_required_document` ·
**Migrations:** `onboarding_0018_deal_buyer`, `onboarding_0028_deal_foundation`,
`onboarding_0029_deal_snapshot`, `onboarding_0030_deal_req_docs`,
`onboarding_0034_deal_buyer_co`, `onboarding_0036_deal_branch`,
`onboarding_0038_buyer_map`, `onboarding_0039_closed_buyer`

**Used by:** Developer 3 (company lists and panels, trade history), Developer 1
(buyer checks attach to the deal's buyer; the handover guard reads the company's
background check and compliance facts).

**State.** All of it is built, and §6's handover works end to end. The guard is a list
of conditions over injected providers (§6.1), and **all eight now decide**: the two
assumption-A5 conditions, the required documents (§6.1.1), both parties' compliance
(P3-3b, P3-4, P4-7), the two invoicing-branch rules (P6-7) and the deactivated-branch
rule (R-19, decision D-04). The handover is
persisted as well as announced (§6.2).

Architecture §3.3 ("The deal"), §3.5 and §3.6 are the source.

---

## 1. Values

```python
class DealStage(str, enum.Enum):
    OPEN = "OPEN"
    GATHERING_PAPERWORK = "GATHERING_PAPERWORK"
    HANDED_OVER = "HANDED_OVER"
    WITHDRAWN = "WITHDRAWN"
```

In `domain/entities/deal_enums.py` — **not** in `exporter_enums.py` (Developer 2's
company values) and **not** in `engagement_enums.py` (Developer 3A's). Database enum:
`onboarding.deal_stage_enum`.

### 1.1 Which moves exist

| From | To | Needs |
|---|---|---|
| `OPEN` | `GATHERING_PAPERWORK` | — |
| `OPEN` | `WITHDRAWN` | reason |
| `GATHERING_PAPERWORK` | `HANDED_OVER` | the §6 guard, and a buyer |
| `GATHERING_PAPERWORK` | `WITHDRAWN` | reason |

`HANDED_OVER` and `WITHDRAWN` are terminal: nothing leaves them. A deal that was
withdrawn in error is a **new deal**, not a reopened one — the same rule the journey
uses, and for the same reason: a record of what was decided must not be editable into
a different decision.

**A terminal deal is closed to edits, not only to stage moves.** Its buyer cannot be
changed and no document can be added to it (`storage-and-documents.md` §6.2), both
refused with `DEAL_TERMINAL`. A handed-over deal's buyer and paperwork are what the
lending team was given; a withdrawn deal's are history.

Unlike the conversation gauge, **any-value-to-any-value is not allowed here.** A stage
is a claim about what has happened to a deal, not a judgement, so an illegal move is
refused with `DEAL_TRANSITION_NOT_ALLOWED` (422) and leaves the row untouched.

---

## 2. A company has many deals

`deal.company_id` is a real foreign key to `exporter_profile.customer_id`
(`ON DELETE RESTRICT`: a company with deals is not deletable). No uniqueness — a
company has any number of deals over time, open ones included. Architecture §3.3.

**Only a `PROSPECT` or a `CUSTOMER` may have a deal opened.** A deal follows a sales
conversation, which applies from `PROSPECT` onward (assumption A4), and opening one
sets the conversation to `READY_NOW` (§5) — so `DealService.open_deal` refuses a
`LEAD` with 409 `DEAL_COMPANY_NOT_READY` before anything is written. (Implemented 29
September 2026 on the audit's recommendation; the programme lead to confirm. Seam
S1 checks no journey by design, so the check belongs here, where the deal is opened.)

Deleting a deal is not an operation. `WITHDRAWN` is how a deal ends.

---

## 3. The buyer

Its own table, `onboarding.deal_buyer`, one row per deal (`deal_id` unique), not
columns on `deal`.

**Why a table rather than columns.** Developer 4 attaches buyer checks to *the buyer*
(plan §8.2, decision 9): a verification result needs something with an id to point at,
and `entity_reference` pointing at a deal would make "a check about the buyer" and "a
check about the deal" the same thing. A separate row gives the buyer its own identity
without pretending it is a company.

| Column | Type | Null | Notes |
|---|---|---|---|
| `deal_id` | uuid | no | FK → `deal.id`, `ON DELETE CASCADE`, **unique** |
| `name` | varchar(500) | no | |
| `country` | char(2) | no | ISO-3166-1 alpha-2, uppercase |
| `registration_number` | varchar(100) | yes | Whatever the buyer's jurisdiction issues |
| `tax_id` | varchar(100) | yes | |
| `contact_email` | varchar(255) | yes | |
| `contact_phone` | varchar(50) | yes | |

**One buyer per deal.** A deal with two buyers is two deals: the buyer is who the
exporter is selling to, and financing one shipment for two buyers is not a thing the
prototype models.

**The buyer's identifiers and contact details are masked** for OPERATIONS and
DEVELOPER, like an exporter's PAN and GSTIN (`api/schemas/masking.py`, decision
12): `registration_number`, `tax_id`, `contact_email` and `contact_phone` reach them
masked on every deal route, a masked value is refused on `PUT .../buyer`, and a masked
field left out of that request keeps its stored value. COMPLIANCE and ADMIN see them
in full. (Changed 28 September 2026 in the frontend refresh, at the lead's call; it
reverses this contract's first design, which left the two identifiers visible.)

**The buyer is optional at `OPEN` and required to leave `GATHERING_PAPERWORK`.** A
deal often starts before the buyer is known; a handover without a buyer is not a
handover, since the payload carries buyer details (§6).

### 3.0 The buyer is becoming a company record

Plan P4-4. `deal.buyer_company_id` (migration 0028) is a nullable FK to
`exporter_profile.customer_id`, `ON DELETE RESTRICT`, with
`ck_deal_buyer_is_not_the_seller` refusing a deal a company sells to itself on. The
deal response carries `buyer_company` — `{company_id, name, country,
pipeline_status, pan, cin}`, with the identifiers masked by the rule below.

The two coexist on purpose, and for a while:

| A deal | Has | The guard reads |
|---|---|---|
| written before P4-6 | `deal_buyer` only | `for_legacy_buyer(deal_buyer.id)` |
| written after P4-4 | `buyer_company_id` | `for_company(buyer_company_id)` |
| mid-migration | both | the **company**, which is the authority |

"A handover needs a buyer" is satisfied by **either** (task 2.4): a deal the
migration has not reached is not blocked, and a deal with neither is still refused
with `DEAL_BUYER_REQUIRED`. The handover snapshot is built from the company when
there is one, since that is what the lending team is being handed; its keys are the
same either way, so a reader never has to know which era wrote it. A company has no
`tax_id` of its own, so the snapshot's `tax_id` is its PAN and its contact fields are
empty — a company's contacts are people on its own record, and inventing a primary
contact here would put a name in the handover that nobody chose.

So the buyer migration (P4-6) is a data migration, not a behaviour change: §6.1
condition 5 decides the same thing either way. `deal_buyer` writes are retired in
P4-10, after every environment has migrated; the table itself is kept.

**Writing it (task 2.4, R-24).** `PUT /deals/{id}/buyer` takes one of three forms,
and exactly one per request: `{buyer_company_id}` names a company on file as the buyer;
`{create: {name, country, pan?, gstin?, registration_number?}}` creates the buyer as a
company and names it; and the legacy `{name, country, …}` records a `deal_buyer` row. A
body carrying more than one is refused (422) rather than merged — they disagree about
what a buyer *is*, and writing two would leave a deal whose company says one thing and
whose row says another.

**Creating the buyer company (R-24, plan P4-3, P4-4's "or creates one").** For a buyer
not on file. Before it, the only ways in were the legacy form, which P4-10 retires, and
Add company, which makes a **lead** and inflates the pipeline (P4-2). In order, and
nothing is written until every check has passed:

1. The deal is not closed (409 `DEAL_TERMINAL`) and names no buyer company yet (409
   `DEAL_BUYER_COMPANY_ALREADY_SET`).
2. **IQ-7, with no exception:** a company outside India that holds no PAN needs its
   registration number (422). The P4-6 exemption is for rows that predate the rule; a
   buyer entered now can meet it. GSTINs must carry the PAN given (422).
3. **Match first** (`CompanyDirectory.match`, audited like every identifier lookup,
   BQ-2). If an identifier names a company on file — `MATCHED`, or a `CONFLICT` between
   several — it is refused, 409 `BUYER_COMPANY_ALREADY_KNOWN`, with `error_context`
   `{match_kind, company_ids}`, so the caller can offer that company instead of a
   duplicate. The audit row is committed before the refusal. A name that only
   resembles a company (`POSSIBLE_DUPLICATE`) does **not** stop it: a name is never an
   identity (IQ-8), and the caller has already been shown the look-alikes.

The company is created by `CompanyDirectory.create_buyer_company`: `pipeline_status =
NOT_IN_PIPELINE`, `source` and `created_via` `DEAL_BUYER`, `created_via_deal_id` this
deal, one `pipeline` history row and **no journey row** — so the pipeline's counts do not
move. It is then named through the same path as `{buyer_company_id}`, which writes the
trade relationship and the `deal_buyer_company_set` history row. A retry after a failure
between the two steps makes no second company: an identifier matches the first and is
refused as already known; with none, the create is keyed on the deal. Roles: staff, as
for every form (DEVELOPER 403, D8). The response is the deal, masked as below. The
deal page offers it in the buyer picker once the match is `NEW`, or `POSSIBLE_DUPLICATE`
after the person says none of the look-alikes is the buyer.

`buyer_company_id` is **set once**: `trg_deal_buyer_company_set_once`
(migration 0034) lets it go from `NULL` to a value and refuses every change after,
and the service refuses a *different* company with 409
`DEAL_BUYER_COMPANY_ALREADY_SET` while treating the same company again as a no-op so
a retry is not an error. The reason is that the column is what the buyer's checks are
recorded against and read back through (`for_company(buyer_company_id)`), what the
handover guard's condition 5 asks about (BQ-4), and what the handover snapshot
records: re-pointing it would silently reinterpret all three. A deal pointed at the
wrong buyer is withdrawn and a new one opened, so the correction leaves a trail. The
column is also in `prevent_terminal_deal_change()` from 0034, so a closed deal's
buyer no longer changes at all — which, unlike set-once, also refuses a *first* write
to a closed deal.

**One condition was too strong, and migration 0039 relaxed it.** 0034's terminal
freeze refused *any* difference on a closed deal, `NULL` → a value included — so a
deal handed over last year could never be linked to its buyer company, which is
exactly the write P4-6 has to make. 0039 moves the column into its own clause, refused
only when the **old** value was not `NULL`: a closed deal's buyer company may be
filled in once and never changed. That is the rule 0029 had already given
`handover_snapshot` for the same reason, and `buyer_company_id` had simply not been
given it. Set-once is unchanged everywhere else. It was found by writing 2.6's tests
rather than by reading the trigger, which is what those tests are for.

A company may not be its own buyer: 422 `DEAL_BUYER_IS_THE_SELLER`, ahead of
`ck_deal_buyer_is_not_the_seller`, so the refusal names the problem. The check means
such a row **cannot exist**, which is worth knowing when reading code that handles
one: the buyer migration's "resolved to its own seller" report and the relationship
backfill's refusal are both guards that cannot fire while that constraint stands, and
§17.2's matching validation query is structurally zero.

Recording one writes a `deal` history row, `event_type = "deal_buyer_company_set"`,
whose `details` carry `buyer_company_id`, the company's `buyer_name` and
`had_legacy_buyer` — the last so the P4-10 retirement can find the deals that still
carry both.

### 3.1 A buyer's problems stay on the buyer

Architecture §3.5 and decision 9. A buyer failing a check is recorded against the
buyer; a deal falling through is `WITHDRAWN` with a reason on the deal. **Neither
touches the company's record.** There is no "has a bad deal" or "buyer risk" field on
`exporter_profile`, and adding one would be a contract change, not a detail.

The deal page shows the buyer's checks to staff (`BuyerChecks`), read and recorded by
`deal_buyer.id`. Once the deal is `HANDED_OVER` or `WITHDRAWN`, no new check may be
recorded (D17, 409 `DEAL_CLOSED`), and the verifications list stops offering
`can_record_result` for that buyer; existing checks stay readable and reviewable.

### 3.2 Linking the deals that came before (the buyer migration, P4-6)

A **command**, not an Alembic revision —
`python -m app.modules.onboarding.migrate_deal_buyers` — because plan §17.2 puts a
person between reading and writing: name-only duplicates are reported and confirmed by
hand (IQ-8), and a revision has nowhere to pause for that. The sequence is `pg_dump`,
`--dry-run`, read the report, confirm what needs a person, `--apply --run-id`,
`--validate`, and a second `--apply` that must create nothing. Run it with
`LOG_LEVEL=WARNING DEBUG=false`; its output is ASCII, so a Windows console can show it.

How a legacy buyer's identity is resolved, in order of confidence:

1. **A company it is already linked to** — the deal names a buyer company (task 2.4),
   or its BUYER results already have a `subject_company_id`. Both are set once, so that
   company is the answer (`match_rule = ALREADY_LINKED`, migration 0041) unless an
   identifier on the legacy row contradicts it, or the links contradict each other.
2. A **PAN** (which may well join an existing *seller* — that is the point of unifying
   the two). A PAN that only GSTINs carry, on several companies, is a conflict.
3. A **`(country, normalised registration number)`** pair. Rows sharing either
   identifier are one company. A number with fewer than two letters or digits is not
   an identity: it is reported, not used, and not stored on a created company.
4. A **new** `NOT_IN_PIPELINE` company, **one per row** when the row has no
   identifier. A **name is never a merge** (IQ-8): a name matching an existing
   company needs a person, and identifier-less buyers sharing a name with each other
   are kept separate and listed for review.

Refused and reported rather than guessed: a buyer resolving to its own deal's seller;
identifiers naming different companies; one identifier naming several; and rows
already linked to *different* companies sharing one identifier (a contested identity
maps nobody by rule — including rows mapped by an earlier run). A person resolves a
refusal with `--confirm-name <deal_buyer_id>=<company_id>`, naming one of the
candidates the report prints (`match_rule = NAME_CONFIRMED`, so the row says a human
decided). Every confirmation is checked before anything is written: one bad line
stops the run, not half of it.

It writes `deal_buyer_company_map` (0038, append-only, keyed on `deal_buyer_id`, which
is what makes a re-run a no-op), the created companies — each with one history row,
`company_created_from_deal_buyer`, carrying `{run_id, deal_buyer_ids, deal_ids,
match_rule}`, and the buyers' email and phone as non-primary contact records —
`deal.buyer_company_id`, and `verification_result.subject_company_id` for the deal's
BUYER results. It touches no `deal_buyer` row, no `entity_type`, no
`entity_reference`, no `subject_snapshot` and no existing history row. `--validate`
also checks that the map and the BUYER results agree with each deal's buyer company.

**There is no logical rollback**, and `--rollback` writes nothing: it reports what a
run did and names the dump. §17.2 allowed for one *"before enabling the freeze
trigger"*, but in the shipped schema both `deal.buyer_company_id` and
`verification_result.subject_company_id` are set-once and frozen, so neither can be
set back to `NULL`. Restoring the `pg_dump` is the only route back — which is why
taking one is step zero and not a precaution.

**Then the relationships.** The migration writes `buyer_company_id` with an `UPDATE`,
so the deals it links arrive without the trade relationship that
`DealService.set_buyer_company` would have created in the same transaction. Developer
3's `backfill_trade_relationships` (P5-5) is step 3 of the operational order and
creates exactly those. See `trade-history.md`.

---

## 4. Who may do what

Per architecture §3.7: OPERATIONS, COMPLIANCE and ADMIN open deals, move stages, and
edit the buyer. DEVELOPER reads. API_USER reaches nothing.

**Which documents a handover needs is a settings change, so ADMIN only** —
`POST /settings/deal-required-documents` (§6.1.1). Any CRM reader may *read* the
rule, including DEVELOPER: it carries no identifiers and nothing decision D8
protects, and the same gate serves `/qualification/criteria`. Changing it changes
which deals can be handed over, which is why writing it is narrower than moving a
stage.

### 4.1 The server serves the allowed moves

`GET /onboarding/deals/{deal_id}` includes `allowed_stage_moves`, the moves **this
user** may make from the deal's current stage — the rules as data, so the screen asks
rather than keeping a copy (§7.5). Same shape as
`ExporterProfileService.allowed_marker_moves` and `ConversationService.allowed_moves`,
deliberately.

A move that is legal but blocked by the §6 guard is **not** in the list, and the
response says why through `handover_blocked_reason`, so the screen can explain
instead of offering a button that 409s.

`GET /onboarding/exporters/{company_id}/deals` carries `can_open_deal`: whether this
caller may open a deal on the company now — a staff role and a `PROSPECT` or
`CUSTOMER` company (§2). The screen offers "Open a deal" from it.

`allowed_stage_moves` and `handover_blocked_reason` are served only to a role that may
move a deal (OPERATIONS, COMPLIANCE, ADMIN). DEVELOPER is served no moves and no
reason: it could act on neither, and the reason names the company's background check,
which decision D8 keeps from DEVELOPER.

### 4.2 Every deal, across companies

`GET /onboarding/deals` lists every deal, newest first, for any CRM reader (the
Deals page). Each row names the seller and the buyer — the buyer company once
`buyer_company_id` is set, the `deal_buyer` details otherwise, the same authority
the deal page gives them — and the **corridor**: the seller's country, then the
buyer's, as `IN-US`. The corridor is worked out on every read and never stored, so
it cannot disagree with the parties; it is `null` while either country is unknown,
most often because no buyer has been recorded yet.

Filters, all optional and all applied together: `corridor` (repeatable; `UNKNOWN`
matches a `null` corridor), `stage` (repeatable), `q` (part of the reference, the
seller's name or the buyer's name, any case, wildcards literal), `company_id` (that
company as seller **or** as buyer company — a `deal_buyer` row is not a company, so
it cannot match), and `opened_from` (inclusive) / `opened_before` (exclusive); a
timestamp without a zone is read as UTC. `total` counts the matches.

`corridors` lists every corridor in use with its count, **ignoring the filters**, so
a screen's choices do not vanish as they are applied. `can_open_deal` there is the
role half only: which companies may have a deal is the company's own rule (§2).

---

## 5. Seam S1 — opening a deal sets `READY_NOW`

Architecture §3.3: "opening a deal also sets this."

`DealService.open_deal` calls Developer 3A's
`ConversationService.mark_ready_now_for_opened_deal(company_id, deal_id=..., actor_id=...)`
in the same session and transaction, after the deal row exists (so `deal_id` is real)
and before the commit. Engagement contract §6 guarantees it is idempotent, checks no
journey stage and no role, and flushes without committing.

**This service never assigns `exporter_profile.conversation`** and never imports
Developer 3A's enum to compare against it (`company-record.md` §2.4 forbids writing
another developer's gauge field, "including just to keep it in step").

If 3A's method were somehow absent, `open_deal` ships without the call and the call
arrives as its own commit — never a stub of their service, and never the column
written directly.

---

## 6. Handover

### 6.1 The guard is a list of conditions

`GATHERING_PAPERWORK → HANDED_OVER` is decided by an **ordered list of conditions**
(`domain/handover_conditions.py`), each returning one unmet-condition string or
nothing. Every condition runs, and `handover_blocked_reason` is all of them joined
with `"; "` — for example `the company is PROSPECT, not CUSTOMER; the background
check is FLAGGED, not CLEAR`. While any is unmet, `allowed_stage_moves` omits the
move, so the screen explains instead of offering a button that 409s (§4.1).

| # | Condition | Provider | State |
|---|---|---|---|
| 1 | the company's journey is `CUSTOMER` | — | **live** (assumption A5) |
| 2 | the company's background check is `CLEAR` | — | **live** (assumption A5) |
| 3 | every required document category is present | `RequiredDocumentsPolicy` | **live** (P2-5b) |
| 4 | the company's Clear is current, and its own sanctions/AML have not failed | `ComplianceFactsReader` | **live** (P3-3b, P4-7) |
| 5 | the buyer's sanctions **and** AML are `PASSED` | `ComplianceFactsReader` | **live** (P3-4, P4-7) |
| 6 | the invoicing branch is recorded, when the seller has one | `BranchFlagReader` | **live** (P6-7, task 2.9) |
| 7 | the invoicing branch is not flagged | `BranchFlagReader` | **live** (P6-7, task 2.9) |
| 8 | the invoicing branch is not deactivated | `BranchFlagReader` | **live** (R-19, decision D-04, 5 October 2026) |

Conditions 1 and 2 are real: a company becomes a `CUSTOMER` when it is a `PROSPECT`
with a `CLEAR` check (`company-record.md` §3.2), and the check is read through
Developer 4A's published helper (`background-check.md` §10) — this service never
creates or writes that column (`company-record.md` §2.4). A company never checked
reads `NOT_STARTED`, and "not `CLEAR`" is never treated as "clear".

Conditions 3–8 ask an **injected provider**, and all of them are now live. "No facts"
is never read as "everything passed": the null providers (`NoComplianceFacts`,
`NoRequiredDocuments`, `NoBranchFlags`) each answer the way that **adds no refusal**,
so a caller that has not injected a real reader gets the guard it had before that
rule existed — never a deal let through on a question nobody answered.

Conditions 4 and 5 read Developer 1's published `ComplianceFactsReader`
(`domain/compliance_facts.py`, implemented by `application/compliance_facts.py`), in
the guard's own session. Condition 5 reads a buyer recorded as a company through
`for_company` and a legacy `deal_buyer` row through `for_legacy_buyer`, so the same
rule decides before and after the buyer migration (P4-6).

**Condition 4 names the date.** It reports an expiry only when the company *is*
`CLEAR` but no longer currently so — a company that was never `CLEAR` is condition 2's
to report, and saying "expired" as well would tell an operator to renew a check that
was never passed. The message is "the background check expired on `YYYY-MM-DD`".

**Conditions 6 and 7 are the branch rules** (plan P6-7, task 2.9), kept separate
because they have different remedies: "record the branch" versus "resolve the flag or
invoice from another branch". A joined message offering both for one deal would be
confusing, and they cannot both apply — a deal either names a branch or does not.

Condition 6 is asked **only of a seller that has a branch to name**: a company with no
active GST registration is not blocked on a field it cannot fill, which is why the
reader answers about the company (`has_active_registrations`) and not just about the
deal. Its message is "the invoicing branch is not recorded".

Condition 7 names the state — "the invoicing branch Maharashtra is flagged" — which is
why the reader returns it alongside the answer: a deal's invoicing branch is a row id,
and only Developer 3's lane knows that a GSTIN's state is its first two characters. One
branch, not the company (decision BQ-6): deals invoiced from the company's other
branches proceed.

**Condition 8: a branch deactivated after it was recorded blocks** (R-19; the lead
decided "block, not warn" as D-04 on 4 October 2026). A deactivated branch cannot be
*chosen* (`set_invoicing_branch` refuses it, 422), but it can be deactivated after a
deal recorded it; that deal then names a branch the company no longer invoices from.
The reader's `is_active` answers with the state's name, like `is_flagged`, so the
message is "the invoicing branch Karnataka is deactivated". The remedy is to choose an
active branch (the picker shows the recorded one as "— deactivated" and offers the
active ones). A branch both flagged and deactivated reports both conditions. The null
`NoBranchFlags` answers "active", so an un-injected reader adds no refusal. **On
deploy**, a deal already invoiced from a branch deactivated earlier becomes blocked.

Every write that changes what conditions 6–8 read — adding, deactivating, flagging
or unflagging a branch — locks the owning company `FOR UPDATE` before the branch, so it
waits for a handover that holds the company `FOR SHARE` and the next guard sees it
(R-18; the background check's D10 for branches).

**Condition 5 requires `PASSED`, not "not `FAILED`".** An unscreened buyer reads
`MISSING` and blocks (BQ-4): "we have not checked" and "the check came back clean"
must not collapse into one outcome. So a deal whose buyer has no sanctions and AML
results cannot be handed over, whether that buyer is a company or a legacy
`deal_buyer` row.

### 6.1.1 Condition 3 — the required documents

`onboarding.deal_required_document` (migration 0030) is the rule, as data: one row
per `(category, document_type, version)`, `active` saying whether that version
requires the document. It is **versioned and append-only**, like
`qualification_criterion` — adding a requirement writes version *n+1* with
`active = true`, removing one writes version *n+1* with `active = false`, and
nothing is ever updated or deleted. A deal handed over last month was judged
against the rule as it stood then, and that rule is still readable.

`document_type` is `''` for "any document in this category". A sentinel rather than
`NULL`, because two `NULL`s do not collide in Postgres and the unique constraint on
`(category, document_type, version)` would then let one requirement be added twice
at a version. The API maps `''` to `null` both ways, so no caller sees it.

| | |
|---|---|
| Seeded | One requirement: category `PRE_SHIPMENT`, any type (IQ-10) |
| Counts as present | An `AVAILABLE` document on the deal (IQ-11). `PENDING_SCAN` is not evidence yet; `QUARANTINED` and `SCAN_FAILED` never will be |
| Satisfies a typed requirement | Only a document of that type |
| Routes | `GET /settings/deal-required-documents` (any CRM reader), `POST` (ADMIN) |
| Refused | A category a deal cannot hold — `ENTITY_KYC` belongs to a company (§3.4), so requiring it of a deal would be a rule no deal could satisfy. A `document_type` the document settings do not configure under the category (422 `DOCUMENT_TYPE_NOT_ALLOWED`, the upload route's own refusal), checked when a requirement is added and not when one is stopped. A change that would leave the rule as it already is — including stopping a key nobody ever required. Two administrators changing one key at once: the second gets 409 `DEAL_REQUIRED_DOCUMENT_CHANGED` and nothing is saved |
| The message | `missing required documents: PRE_SHIPMENT, BANKING` — every missing category at once, the category alone for an any-type requirement and `CATEGORY (type)` for a typed one |

**This changed behaviour deliberately.** Before P2-5b a deal could go to the
lending team with no paperwork at all. Deals **already** `HANDED_OVER` are
untouched: the guard runs on the move, so a past handover is never re-judged, and
turning a new requirement on does not invalidate one. **On a live database**, every
open deal without an `AVAILABLE` pre-shipment document is blocked from handover the
moment `onboarding_0030_deal_req_docs` runs, until one is uploaded — tell the
operations team before deploying it.

The guard reads **both parties'** rows once per run — share-locked on the move (D10)
and unlocked on the read that renders a page — and hands every condition the same
snapshot, so no condition can see a different company than the lock was taken on.

The locking read is one statement, `WHERE customer_id IN (…) ORDER BY customer_id …
FOR SHARE`. The ordering is the deadlock rule, not tidiness: Postgres takes row locks
in the order the query returns them, so two handovers that share a pair of companies —
A selling to B while B sells to A — queue in one order instead of each holding what
the other wants (P4-7).

### 6.2 The handover is recorded, not only announced

On handover, in this order:

1. `deal.handover_snapshot` is written **in the same `UPDATE` as the stage move**:
   `{buyer, buyer_company_id, document_ids, snapshot_source, snapshot_at}`. The
   order matters — `trg_deal_terminal_freeze` fires on the old row, whose stage is
   still `GATHERING_PAPERWORK`, so the column is written before it is frozen.
2. The history row, in the same transaction (§7).
3. `OnboardingEventPublisher.deal_handed_over(...)`, after the commit — history is
   the source of truth and the announcement is best effort (architecture §3.6).

The snapshot is **set once**: the trigger lets it go from `NULL` to a value on a
terminal deal, so a deal handed over before snapshots existed can be filled in by a
migration, and refuses every change after that. `snapshot_source` says which it is —
`taken_at_handover` for a record, `backfilled_from_deal_buyer` for migration 0029's
reconstruction from the `deal_buyer` row and the handover history row.

The stored snapshot is never masked: it is the record of what the lending team was
given, and a record that changed shape with its reader would be useless. The deal
response masks the buyer inside it by exactly the rule that masks the live buyer
(§3), so a tax identifier is no more visible inside a snapshot than outside one.

`document_ids` is every document on the deal when it was handed over, whatever its
scan status — the snapshot records what was there, not only what satisfied a rule.
In a backfilled snapshot it is `null` when no handover history row recorded the
paperwork, just as `buyer` is `null` when the buyer row is gone: "not recorded",
never `[]`, which would say the deal went over with no paperwork.
Whether a document *counts towards a requirement* is condition 3's separate
question, and only `AVAILABLE` documents do (§6.1.1).

---

## 7. History

Every stage change writes one row through Developer 1's `HistoryService.record(...)`,
in the same transaction as the change (architecture §3.8).

| Field | Value |
|---|---|
| `dimension` | `"deal"` — fixed by `history-row.md` §2 |
| `company_id` | always set, even though the change is about a deal |
| `deal_id` | always set for a `deal` row (`history-row.md` §2.1) |
| `event_type` | `deal_initial` at creation, `deal_transition` for a move |
| `source` | `deal_service.open_deal`, `deal_service.transition_stage`, … |
| `actor_id` | from the login session, never the request body (§7.5) |
| `reason` | required for `WITHDRAWN` (assumption A7) |

Buyer edits write `dimension="deal"` with `event_type="deal_buyer_changed"` — a buyer's
details are part of a deal's story, and the alternative (a `buyer` dimension) would need
a change to `history-row.md` §2, which is Developer 1's. `from_value` and `to_value` are
both the deal's unchanged stage, so the row's `details` say what happened: `changed`
(the field names that changed, sorted), `buyer_name` and `created` (`true` when this
recorded the deal's first buyer). The history screen shows "Buyer recorded" or "Buyer
updated: …" from them. Rows written before `created` was added lack it and read as
updates.

---

## 8. Error codes

| Code | Status | When |
|---|---|---|
| `DEAL_NOT_FOUND` | 404 | No such deal. |
| `DEAL_TRANSITION_NOT_ALLOWED` | 422 | The move is not in §1.1 for the current stage. |
| `DEAL_TERMINAL` | 409 | A move out of `HANDED_OVER` or `WITHDRAWN`. |
| `DEAL_WITHDRAWAL_REASON_REQUIRED` | 422 | `WITHDRAWN` without a reason (A7). |
| `DEAL_BUYER_REQUIRED` | 422 | Leaving `GATHERING_PAPERWORK` with no buyer. |
| `DEAL_HANDOVER_BLOCKED` | 409 | Any §6.1 condition is unmet. The message names every one of them. |
| `VALIDATION_ERROR` | 422 | On `POST /settings/deal-required-documents`: a category a deal cannot hold, or a change that changes nothing (§6.1.1). |
| `DOCUMENT_TYPE_NOT_ALLOWED` | 422 | On `POST /settings/deal-required-documents`: a `document_type` not configured under the category (§6.1.1). |
| `DEAL_REQUIRED_DOCUMENT_CHANGED` | 409 | On `POST /settings/deal-required-documents`: another administrator changed the same requirement first; nothing was saved (§6.1.1). |
| `DEAL_COMPANY_NOT_FOUND` | 404 | Opening a deal for a company that does not exist. |
| `DEAL_COMPANY_NOT_READY` | 409 | Opening a deal for a company that is still a `LEAD` (§2). |
| `DEAL_BUYER_COMPANY_ALREADY_SET` | 409 | Naming or creating a buyer company on a deal that already names a different one (§3.0). |
| `BUYER_COMPANY_ALREADY_KNOWN` | 409 | Creating a buyer company whose identifier a company on file holds; `error_context` carries `match_kind` and `company_ids` (§3.0, R-24). |

---

## 9. What this contract does not cover

- **Transactions and how they perform** — the lending side's, outside the CRM
  entirely (architecture §3.5). Not modelled here, not now, not later.
- **Underwriting decisions.** The CRM hands a deal over; whether to fund it is not
  its business.
- **Documents.** `storage-and-documents.md`, same owner.
- **What the two companies have traded, and whether they were paid.**
  `trade-history.md` (Developer 3). A deal is what they are doing now; a trade
  relationship is what they have done, invoice by invoice. The deal page shows the
  pair's history, and the handover does not depend on it.
