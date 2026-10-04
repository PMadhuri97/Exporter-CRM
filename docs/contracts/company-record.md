# Contract — the company record

**Owner:** Developer 2 · **Implemented by:** L2-03 (identity), L2-04 (journey), L2-05 (migration 0014), L2-06 (tax IDs), L2-08 (marker), L2-11 (the move to `CUSTOMER`) · **Status:** implemented — §10 lists what is still open

Every gauge, deal, document and check in the CRM hangs off one company record.
This is what Developers 1, 3 and 4 build against: what a company is called,
which values its journey and marker take, which fields sit on it, and who may
write each one.

It fixes **vocabulary and rules**, not storage. Column types, whether GSTINs
are a child table or an array, and index names are migration 0014's to decide
(L2-05), as long as they honour what is written here.

Changing this contract needs the agreement of Developer 2 and every developer
who writes or reads a field on it (architecture §7.5).

---

## 1. One company, one identifier

A company has exactly one identifier: a `uuid`, minted by the CRM when the
company is created, never reused and never changed.

| Where | It is called | Why |
|---|---|---|
| Existing columns, routes and responses | `customer_id` | `exporter_profile.customer_id`, `exporter_lifecycle_history.customer_id`, `/onboarding/exporters/{customer_id}`, every child table today |
| Event payloads, the history writer's parameters, new code | `company_id` | `docs/contracts/event-envelope.md` §3, `HistoryService.record(company_id, ...)` |

**They are the same value.** New code says `company_id`. Renaming the existing
`customer_id` columns and route parameter is **not** part of this contract: it
would touch every developer's tables, the generated frontend types and the
route-authorisation table at once. Whether 0014 renames it is recorded as open
item O1.

The name is misleading and worth stating plainly: a CRM `customer_id` is **not**
an id in the `customers` module. None of the CRM's ids match that module's rows
(architecture §5.5), and the CRM never writes to it (decision 10). A company is a
"customer" in the CRM's sense only when its journey says `CUSTOMER`.

`exporter_profile` also has a surrogate primary key `id`. Nothing references it.
Every link to a company — contacts, activities, screening items, verification
results about the company, history, deals, documents, qualification — uses the
company id above.

---

## 2. The record

The logical fields. "Owner" is the developer whose service is the **only**
writer of that field; everyone else reads it.

### 2.1 Identity (Developer 2)

| Field | Meaning | Required at creation | Rule |
|---|---|---|---|
| `company_id` | §1 | minted by the server | Never supplied by a caller creating a company |
| `name` | The company's legal name | **yes** | Non-empty after trimming, at most 255 characters. A column on the company record (0014); can be corrected, never cleared. Nullable in the database only while the API's unnamed create path exists (§10) |
| `country` | Country of incorporation | **yes** | ISO 3166-1 alpha-2, upper case (`IN`) |
| `pan` | Indian income-tax account number | no | One per company. Unique across companies — §4 |
| `gstins` | GST registrations | no (empty list) | Several per company, one per state. A duplicate across companies warns, never blocks — §4 |
| `iec` | Importer-exporter code | no | §4 |
| `cin` | Company registration number | no | §4 |
| `source` | How the company reached us | **yes** | The existing `ExporterSource` values. **Immutable once set**, enforced by the service and by `trg_exporter_profile_source_immutability`. `RXIL` for RXIL intake. `DEAL_BUYER` only for a company created as a deal's buyer, outside the pipeline: `POST /exporters` and the CSV import refuse it (R-21) |
| `date_added` | When the record was created | server-set | Immutable |

`legal_name` / `incorporation_country` on `onboarding_request`, and the
`legal_name` the list response currently derives from it, are the legacy
source this replaces. After L2-03 no CRM query reads `onboarding_request`.

Today's single `gstin` field becomes `gstins`. Until L2-03/0014 land the API
still exposes `gstin`; how the response carries the transition is L2-03's call,
announced to Developer 1 so the generated types are regenerated once.

### 2.2 Descriptive fields (Developer 2)

Kept as they are today, editable by staff, each edit recorded (L2-07,
dimension `profile`): `industry`, `export_markets`, `products`,
`year_established`, `website`, `relationship_manager`.

`relationship_manager_user_id` stays dormant: nothing writes it, and nothing may
use it to widen who sees identifiers (decision 12). Relationship-manager
ownership is post-prototype.

### 2.3 Journey and marker (Developer 2)

| Field | Values | Default |
|---|---|---|
| `journey` | `LEAD`, `PROSPECT`, `CUSTOMER` | `LEAD`; `PROSPECT` for RXIL intake (decision 7) |
| `marker` | `NONE`, `PAUSED`, `ENDED` | `NONE` |

Rules in §3.

### 2.4 Current gauge values

The record carries the **current** value of each gauge so lists and filters
need no join (architecture §3.8). The history log carries every change. Each
gauge's values and moves are defined by its owner's contract; this contract
only fixes the field name, the owner, and the default.

| Field | Owner | Default | Values defined in |
|---|---|---|---|
| `qualification` | Developer 2 | `NOT_YET_REVIEWED` | `criterion-result.md` §4 |
| `conversation` | Developer 3 | Developer 3's engagement contract (architecture: `NOT_CONTACTED`, tracked from `PROSPECT`) | engagement contract (L3-01) |
| `background_check` | Developer 4 | `NOT_STARTED` | background-check contract (L4-01) |

**None of these three columns exists yet.** Migration 0014 did not add them:
the conversation and background-check values are defined by contracts not yet
published (L3-01, L4-01), and qualification's lands with its tables (0017).
Each owner adds its own column in its own migration, with the default above.

**Only the owner writes its field**, through its own service, and writes the
history row in the same transaction (history contract §5). No other service
assigns to another developer's gauge field, including "just to keep it in
sync".

The background-check risk rating (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`, decision 6)
is Developer 4's. Whether it is also carried on the company record for list
filtering is Developer 4's call in the background-check contract.

---

## 3. Journey and marker rules

### 3.1 The journey moves forward only, and never by hand

| Move | Caused by | Written by |
|---|---|---|
| created at `LEAD` | Manual entry, bulk import | Developer 2's create path |
| arrives as `PROSPECT` | RXIL intake (decision 7) | Developer 2's RXIL intake (L2-12). As built: created as a `LEAD` and moved to `PROSPECT` by RXIL's own `QUALIFIED` outcome, so every commit satisfies invariant 1; a delivery interrupted in between is finished by the next one |
| `LEAD` → `PROSPECT` | A qualification outcome of `QUALIFIED` is recorded | Developer 2, in the same transaction as the outcome |
| `PROSPECT` → `CUSTOMER` | The company is `PROSPECT` **and** its background check is `CLEAR` — whichever becomes true second (assumption A1) | Developer 2 (L2-11) |

Nothing else. In particular:

- **No person moves the journey directly.** There is no "move to next stage"
  action in the target model; each move is the consequence of a qualification
  outcome or a background-check decision. Today's
  `POST /onboarding/exporters/{customer_id}/transition` belongs to the old ten
  statuses and goes with them (L2-04).
- **Never backwards.** A `CUSTOMER` whose check later becomes `FLAGGED` or
  `ON_HOLD` stays a `CUSTOMER`; the flag is visible and blocks deal handovers
  (assumption A5). A `NOT_QUALIFIED` lead stays `LEAD`, is never deleted, and
  can be re-reviewed (decision 8).
- **Never skipped.** `LEAD` → `CUSTOMER` does not exist. A lead whose check is
  already `CLEAR` becomes `PROSPECT` and then `CUSTOMER` in the same
  transaction, as two moves with two history rows.

Consequence for the allowed-moves endpoint (decision U1, still unowned): for the
journey dimension, the set of moves a person may request is **empty**. The
journey still belongs in that endpoint's response (current value, and why the
next move has not happened), but it contributes no buttons.

### 3.2 The PROSPECT → CUSTOMER hand-off

Developer 4 decides `CLEAR`; Developer 2 moves the journey (architecture §8.2).
Both orders must work:

- **Qualified first, cleared second.** Developer 4's `CLEAR` decision is what
  completes the condition; the move follows from Developer 4's signal (L4-05).
- **Cleared first, qualified second.** Developer 2's `QUALIFIED` outcome sees
  `background_check = CLEAR` on the record and moves straight through to
  `CUSTOMER`.

The move writes a `journey` history row and then announces
`company.became_customer` (event contract §3). The payload's `company_id`,
`name`, `country`, `pan` and `gstins` come from §2.1 of this contract;
`risk_rating` and `clearing_decision_id` come from Developer 4's decision.

**They commit together — one transaction** (decision U4, implemented 29 September
2026 on the audit's recommendation; **awaiting the programme lead's written
confirmation**). Developer 2's `ExporterProfileService.promote_to_customer_if_ready`
flushes and never commits, like seam S1, and is called by whichever move completes
the condition, before that move's single commit:

- `BackgroundCheckService._move` when it records `CLEAR` (Developer 4A);
- `QualificationService` when a `QUALIFIED` outcome moves a `LEAD` to `PROSPECT`
  (manual review and RXIL intake alike).

Both callers hold the company row `FOR UPDATE` first, so a `CLEAR` and a `QUALIFIED`
landing together serialise and the move happens exactly once. No committed state is
ever `PROSPECT` **and** `CLEAR`; a failure anywhere rolls the whole move back. The
move is idempotent: an already-`CUSTOMER` company (a reopen then a second `CLEAR`) is
a no-op that writes no row and announces nothing. `company.became_customer` is
published **after** the commit, best effort. The journey row carries `terminal: true`,
`cause`, `clearing_decision_id` and `risk_rating`.

### 3.3 The marker

`PAUSED` and `ENDED` are commercial states, set alongside the journey and
never instead of it (decision 3). A compliance concern is **not** a marker; it
is `FLAGGED` or `ON_HOLD` on the background check.

| Move | Reason | Who |
|---|---|---|
| `NONE` → `PAUSED` | required | OPERATIONS, COMPLIANCE, ADMIN |
| `NONE` → `ENDED` | required | OPERATIONS, COMPLIANCE, ADMIN |
| `PAUSED` → `ENDED` | required | OPERATIONS, COMPLIANCE, ADMIN |
| `PAUSED` → `NONE`, `ENDED` → `NONE` (clear) | optional | OPERATIONS, COMPLIANCE, ADMIN |

`ENDED` → `PAUSED` is not a move: clear first. A move to the value the marker
already has is refused, not silently accepted.

`ENDED` companies are left out of **default** working lists and remain
findable by search and by an explicit marker filter (assumption A11). `PAUSED`
companies stay in default lists, visibly marked.

As built (L2-08), on `GET /onboarding/exporters`: with no `marker` filter and no
search term — `name`, `pan`, `gstin`, `iec` — `ENDED` companies are excluded;
any search term includes them; `marker=ENDED` lists only them. `source` and
`status` are list filters, not search terms, and do not bring them back. The
marker is set and cleared through `POST /onboarding/exporters/{customer_id}/marker`
only; the edit route refuses it. The current reason is on the record
(`marker_reason`, `NULL` exactly when the marker is `NONE`, enforced by the
database) and every change is a `marker` history row.

The marker changes nothing else: not the journey, not any gauge, not any deal.

---

## 4. Identifier rules

Values are stored **normalised**: surrounding whitespace removed, letters in
upper case. Formats are checked on the normalised value; an invalid format is
refused with a message naming the field.

| Identifier | Format | Across companies |
|---|---|---|
| PAN | 10 characters: 5 letters, 4 digits, 1 letter (`AAAAA9999A`) | **Unique. A duplicate is refused** (decision 4). The database enforces it, not only the service |
| GSTIN | 15 characters: 2-digit state code, the PAN (characters 3–12), 1 entity character, `Z`, 1 check character | **A GSTIN already held by another company produces a warning, not a refusal** (decision 4). Within one company, the same GSTIN twice is refused |
| IEC | 10 alphanumeric characters | No uniqueness rule in the prototype. Used for duplicate matching in bulk import |
| CIN | 21 characters: `L`/`U`, 5 digits, 2-letter state, 4-digit year, 3 letters, 6 digits | No uniqueness rule in the prototype. Used for duplicate matching in bulk import |

**GSTIN contains the PAN.** When a company has a PAN, every GSTIN on it must
carry that PAN in characters 3–12; a mismatch is refused. When a company has
no PAN, its GSTINs must still all carry the *same* PAN — GSTINs carrying two
PANs cannot be one company's, and are refused on the company screens as they
are by import and RXIL intake. That embedded PAN is used for duplicate
*matching* only; it is never written into `pan` silently.

**Warnings are part of the response, not an error.** A save that raises a
GSTIN warning succeeds, and the response says which GSTIN is also held by which
other company (subject to §5's masking). As built (L2-06): create, edit and
detail responses carry `gstin_warnings: [{gstin, other_customer_ids}]`, empty
when there is nothing to warn about; the GSTIN in a warning is masked like
every other identifier. Only the database's per-company uniqueness
(`uq_exporter_gstin_customer_gstin`) exists — never a global one.

### 4.1 A GST registration is a branch (task 3.12, plan P6-1)

`exporter_gstin` grew in place rather than being copied into a `gst_registration`
table. A row is now a **branch**: a GSTIN plus the state it was issued in, the GST
portal's status, the registered address, a compliance flag, and whether the company
still uses it.

Three facts that are easy to confuse, kept apart:

| Column | Whose answer it is |
|---|---|
| `status` (`UNVERIFIED` / `ACTIVE` / `CANCELLED` / `SUSPENDED`) | the **GST portal's**. `UNVERIFIED` is the default and means "nobody has checked", deliberately not `ACTIVE`, which would be a claim |
| `active` | **ours** — whether we still use this branch |
| `flag_status` (`NONE` / `FLAGGED`) | **compliance's** (task 3.14) |

`state_code` and `state_name` are **derived** from the GSTIN's first two characters
(`domain/gst_states.py`) and never entered: a typed state could contradict the GSTIN
beside it. A state code this release does not know keeps `state_name = NULL` —
recorded as unknown rather than guessed, because the format check accepts any two
digits.

**A registration is never deleted.** `trg_exporter_gstin_no_delete` refuses it, and
`gstin_rows` no longer cascades `delete-orphan`. Before task 3.12 a company edit that
dropped a GSTIN deleted its row; once a deal records its invoicing branch that delete
hits `fk_deal_seller_gst_registration_id`'s `RESTRICT`, and where it succeeded it
destroyed the record of a branch the company really traded through. Dropping one is a
**deactivation**, and re-adding the same GSTIN reactivates that row rather than
inserting a second — so there is one row per `(company, GSTIN)` forever.

`PATCH /exporters/{id}` **no longer accepts `gstins`** (422, task 3.13). Adding,
deactivating and flagging a branch are three decisions with three routes under
`/exporters/{id}/gst-registrations` and `/gst-registrations/{id}`, each leaving its
own `gst_registration` history row with the GSTIN masked. `company.gstins` means the
**active** ones.

**Flagging is per branch and per company.** A company trading through five states may
have a problem in one of them, so a flag blocks handovers only for deals invoiced
through *that* branch (decision BQ-6, task 2.9). A reason is required to flag **and**
to unflag — the first is what the block will say, the second is why we decided the
problem was resolved — and `ck_exporter_gstin_flag_reason` holds the first at the
database. Because a GSTIN may legitimately sit on two companies (IQ-9), flagging one
company's row does **not** touch the other's; the flag response names the other
holders so nobody believes they have stopped trade that is still running (task 3.15).

Flag and unflag are **COMPLIANCE and ADMIN only**. Recording and deactivating a
branch stay with STAFF: which branches a company trades through is a record a
relationship manager keeps.

A "verify on the GST portal" link is served only to a role that sees the full GSTIN
(task 3.17), because the link contains it.

**Bulk import matching** (L2-13, assumption A14) matches an incoming row to an
existing company on PAN, then GSTIN via its embedded PAN, then IEC, then CIN,
and reports every row as accepted, rejected, or possible duplicate. It never
merges two companies on its own.

**As built** (L2-12, L2-13) — one algorithm, `CompanyMatcher`, for bulk import
and RXIL intake alike, over identities checked by the same normalisers as
manual creation (`check_identity`):

| The incoming company… | Result |
|---|---|
| has a PAN (its own, or the one every GSTIN carries) that an existing company holds, and nothing disagrees | **matched** to that company; nothing on it is changed |
| …but that company has a different IEC or CIN, or another company holds its IEC or CIN | **conflict** — rejected, every company involved named |
| has no PAN of its own, its GSTINs all carry one PAN, and exactly one existing company with no PAN holds every one of them (and no GSTIN carrying another PAN) | **matched** to that company — it is the one an earlier GSTIN-only delivery or row created. The IEC/CIN conflict rules above apply |
| brings its own new PAN, and shares only GSTINs with companies that have no PAN | **new**, with a `GSTIN_HELD_BY_OTHER_COMPANY` warning (decision 4) |
| shares an IEC or CIN with a company that has a different PAN | **conflict** |
| otherwise shares a GSTIN, IEC or CIN with one company, and no PAN settles it | **possible duplicate** — nothing created, for a person to decide |
| …with several companies | **possible duplicate**, also `AMBIGUOUS_MATCH` |
| shares nothing | **new** |

IEC is now checked too (10 letters or digits), by the same normaliser for
manual creation, editing and import. A CSV row is `accepted` (`created` as a
`LEAD` or `matched`), `rejected` or `possible_duplicate`; RXIL refuses a
conflict or possible duplicate with 409. Neither ever makes a `CUSTOMER`.

---

## 5. Who may see and do what

Unchanged from what Developer 1 built (L1-10, architecture §3.7, decision 12):

- **Read** a company: OPERATIONS, COMPLIANCE, ADMIN, DEVELOPER. API_USER: nothing.
- **Create and edit** a company, **set and clear the marker**: OPERATIONS,
  COMPLIANCE, ADMIN.
- **Full PAN, GSTIN and IEC**: COMPLIANCE and ADMIN. Everyone else receives them
  masked, on the server (`api/schemas/masking.py`, `can_reveal_identifiers`).
  Contact email and phone follow the same rule.
- **Exact search by PAN, GSTIN or IEC**: only roles that may see them unmasked;
  anyone else gets 403 naming the parameter, because an exact match is itself
  an answer (`_reject_identifier_search`).
- **CIN** is masked like the other three (the recommended default for open
  item O4, applied in L2-05 until the programme lead decides otherwise). There
  is no CIN search filter yet.
- **Name search** (case-insensitive, partial) is open to every reader.

**The actor is always the logged-in user**, taken from the session by the route
and passed to the service. No request body carries an actor, a "decided by", or
a source that claims to be the platform. Moves the platform makes on its own
(an automatic journey move) record `actor_id = None` in history only when no
person caused them; a journey move caused by a person's qualification outcome
records that person.

---

## 6. History

Every change to the record writes one row through `HistoryService.record`, in
the same transaction as the change (history contract §5). Developer 2's
dimensions:

| Dimension | Written when | `from` → `to` | `reason` |
|---|---|---|---|
| `journey` | creation, and each move in §3.1 | `NULL` → `LEAD`/`PROSPECT` at creation; then the move | — |
| `marker` | each move in §3.3 | `NONE`/`PAUSED`/`ENDED` | required on setting, optional on clearing |
| `profile` | each edit of an identity or descriptive field (L2-07) | old value → new value | — |
| `qualification` | see `criterion-result.md` §6 | | |

**Event types.** The journey keeps the names its rows have always had —
`lifecycle_initial` / `lifecycle_transition` — because a downstream consumer
(ANER-4.2-S1T2) polls for them (history contract §3). Every other Developer 2
dimension uses the contract's derived names (`marker_transition`,
`profile_transition`, ...). Since L2-04 every journey row — the `LEAD` row at
creation, the `LEAD` -> `PROSPECT` move a `QUALIFIED` outcome makes, and an
RXIL intake's rows — uses these two names, and carries `terminal` in its
details: `false` for `LEAD` and `PROSPECT`; `true` for the move to `CUSTOMER`
(L2-11, §3.2). Rows written before L2-04 for the ten old
statuses are kept as they were.

**Allowed moves are served, not copied.** Each company response carries
`allowed_marker_moves` — the marker values this viewer may set from here, each
with `reason_required` — and the qualification response carries
`allowed_outcomes` and `can_record_results`. The frontend offers exactly those
and holds no transition table. The journey has no allowed moves: it is never
moved by hand. The cross-gauge allowed-moves endpoint remains open item O6.

**How a `profile` row is written** (L2-07, built). One row per field whose
value actually changes; an edit that changes nothing writes nothing.

| Column | Value |
|---|---|
| `dimension` | `profile` |
| `event_type` | `profile_transition`, passed explicitly |
| `from_status` | `NULL` |
| `to_status` | the field's name (`website`) |
| `actor_id` | the signed-in user |
| `event_metadata` | `field`, `from`, `to` (the old and new values, `null` when empty), `edit_id` (shared by every row of one edit), `source` |

The values sit in `event_metadata`, not in `from_status`/`to_status`, because
those columns hold 64 characters and refuse an empty value: a website, a list
of export markets and a cleared field fit neither. `event_type` is passed
explicitly because the shared writer would otherwise derive `profile_initial`
from the `NULL` `from_status`. This settles open item O7.

**Identifiers are masked in these rows**, for every reader: `pan`, `gstins`, `iec`,
`cin` and `registration_number` are written masked (`registration_number` since R-15;
before it the full value was written), and the history route masks them again when it
serves a row, so a row written before R-15 is served masked too without being rewritten
(the log is append-only).

**`identity_type` follows the edit** (R-16): it is recomputed whenever `pan` or
`registration_number` changes, by the same rule as on create. An edit that touches
`country`, `pan` or `registration_number` must leave the company identifiable (IQ-7):
moving a PAN-less company abroad without a number, or clearing a foreign company's
number, is refused (422). A buyer the P4-6 migration created with no number keeps IQ-7's
exception until one is added. Migration 0043 corrected the rows edited before this.

**A tax identifier's old and new values are masked in the row itself** (PAN,
GSTIN, IEC — last four characters visible), not just in the response. The
history read route returns `details` to every CRM reader, including
OPERATIONS and DEVELOPER, who only ever see these identifiers masked on the
company. The company keeps the full value; the history records that it
changed, when, by whom, and its last four characters. This settles open item
O5 for the prototype; storing full values would need the history read route to
mask by role, which is Developer 1's route.

---

## 7. Relation to the other contracts

| Contract | Relation |
|---|---|
| History row (Dev 1) | This contract writes the `journey`, `marker` and `profile` dimensions and uses them exactly as that contract defines. It adds no column and changes no rule there |
| Event envelope (Dev 1) | `company.became_customer` takes its company fields from §2.1. `partition_key` is the company id |
| Migration register (Dev 1) | 0014 implements §2 and §4 and adds the history foreign key the register assigns to it |
| Criterion result (Dev 2) | Defines the `qualification` field's values and the outcome that moves `LEAD` → `PROSPECT` |
| Engagement (Dev 3), background check (Dev 4) | Define the `conversation` and `background_check` values. This contract only reserves the field names and says who writes them |

---

## 8. Invariants

Any of these being false is a bug:

1. `journey = PROSPECT` or `CUSTOMER` ⇒ `qualification = QUALIFIED`.
2. `journey = CUSTOMER` ⇒ the history shows a `background_check` `CLEAR` at or
   before the `PROSPECT` → `CUSTOMER` row. (The check may have moved since.)
3. `journey` never takes an earlier value than one it has held.
4. No two companies share a PAN.
5. A company's GSTINs all embed its PAN, when it has one.
6. Every current value on the record equals the `to` value of the latest
   history row of its dimension.
7. Every child record points at a company that exists (from 0014 onward).

---

## 9. Open items

Recorded, not decided here. Each names who decides.

| # | Question | Decides |
|---|---|---|
| O1 | Does 0014 rename `customer_id` to `company_id` in the CRM's own tables and routes? Recommendation: **no** in the prototype — all four developers' code and the generated types would move at once for no behavioural gain | Dev 2 with Dev 1 (types) |
| O2 | The ANER-4.2-S1T2 consumer watches `lifecycle_transition` rows for `ONBOARDED` (the `terminal` flag). That status is gone (L2-04, migration 0020). Journey rows keep the `lifecycle_*` event types and the `terminal` flag, which only `CUSTOMER` will set (L2-11) — confirm that `CUSTOMER` is the replacement | Programme lead, with whoever owns that consumer |
| O3 | ~~Decision U4: do Developer 4's `CLEAR` and Developer 2's `CUSTOMER` move commit in one transaction?~~ **Implemented as one transaction** (§3.2, 29 September 2026) — the programme lead to confirm in writing | Programme lead, Dev 2, Dev 4 |
| O4 | Is CIN masked like PAN/GSTIN/IEC? Recommendation: **yes** until decided — widening later is safe, narrowing later is not | Programme lead (decision 12's scope) |
| O5 | ~~Profile-history rows for tax identifiers: masked in the row, or stored in full and masked on read?~~ **Settled for the prototype: masked in the row** (§6). Revisit only if the history read route gains role-based masking | Dev 2 with Dev 1 — Dev 1 to acknowledge |
| O6 | ~~Decision U1: who owns the allowed-moves endpoint~~ **Resolved in practice:** there is no single endpoint — each gauge's owner serves its own allowed moves (`allowed_marker_moves`, qualification's `allowed_outcomes`, the conversation's and background check's `allowed_moves`, the deal's `allowed_stage_moves`, `can_open_deal`), and the frontend keeps no copy | Programme lead |
| O7 | ~~How a `profile` history row records an empty value.~~ **Settled: values in `event_metadata`, `to_status` names the field** (§6) | Dev 2 with Dev 1 — Dev 1 to acknowledge |

---

## 10. What is implemented today

Stated separately so nobody reads this contract as a description of the code.

| Item | State |
|---|---|
| Company id (as `customer_id`), `source` immutability, descriptive fields | **implemented** |
| IEC column | **implemented**, format not yet checked |
| Server-side masking and identifier-search refusal | **implemented** (Dev 1, L1-10) |
| `journey` history rows (`lifecycle_*`, with `terminal`) | **implemented** — for the three journey stages (L2-04); older rows for the ten statuses are kept |
| `name` / `country` / `cin` as columns on the company record | **implemented** (0014). The transitional identity store is deleted; no CRM code reads a company's identity from `onboarding_request` |
| `onboarding_history` on the company detail | **removed** (L2-03) |
| Retiring the ten old statuses | **implemented** (L2-04, migration 0020): `lifecycle_status`, its enum, the transition route and the frontend's copy of the graph are gone |
| The move to `CUSTOMER` | **implemented** (L2-11) — both orders, in the completing move's transaction, announced after the commit (§3.2) |
| `allowed_marker_moves` on company responses; `allowed_outcomes` / `can_record_results` on qualification | **implemented** (L2-04, L2-14) |
| `gstins` (several, `exporter_gstin`), PAN format and uniqueness, GSTIN format and PAN cross-check, duplicate-GSTIN warnings | **implemented** (0014, L2-06) |
| `marker` and `marker_reason`, the marker route, ENDED off the default list | **implemented** (0014, L2-08) |
| `journey` (`LEAD`/`PROSPECT`/`CUSTOMER`) and `qualification` columns | **implemented** (0017); the old `lifecycle_status` beside it was dropped in 0020. Qualification moves it `LEAD` -> `PROSPECT` |
| `conversation`, `background_check` fields | **implemented** — Dev 3A's 0016 and Dev 4A's 0015 (see §2.4) |
| The ORM declares every index and constraint 0014/0017 created (PAN unique, the outcome chain) | **implemented** — checked by `test_orm_matches_the_onboarding_schema.py` |
| `website` | **retired** (R11, decision IQ-16, task 3.7). No write path accepts one — the request schemas refuse the field (422) and the CSV importer reads the old `website` column and ignores it — and no response carries one. The column and every stored value are kept: nothing is destroyed, nothing is shown |
| `registration_number` | whatever the company's own registrar issued, for a company not identified by a PAN. **Required for a company outside India** that holds no PAN (decision IQ-7); stored as the registrar writes it and compared with everything but the ASCII letters and digits removed, upper-cased — exactly the unique index's expression, so a lookup and an insert can never disagree (R-20) — so one number cannot be entered twice per country (`uq_exporter_profile_country_registration_number`). A number with no ASCII letter or digit is refused (422). A duplicate is refused with 409 `DUPLICATE_REGISTRATION_NUMBER` naming the holder, like a PAN — unlike a GSTIN, which stays warn-only (IQ-9). Masked like CIN |
| `profile` history on edits; clearing a field | **implemented** (L2-07) |
| Real links from contacts, activities, screening items, GSTINs and history | **implemented** (0014, `ON DELETE RESTRICT`); `verification_result.entity_reference` deliberately has none |
| `name` required by the database | **not built** — waits for the unnamed create path to go |
