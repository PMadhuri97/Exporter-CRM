# Contract — the company record

> **Amendment, 9 October 2026 — permissions, and a read-only administrator.** Every CRM
> route now checks a permission (`require_permission`), not a role list; the grants each
> built-in role starts with are in `platform/authorization/catalog.py`
> (`BUILTIN_ROLE_PERMISSIONS`), seeded by `auth_0007_business_permissions`. The
> administrator (ADMIN) manages users, roles and settings and **reads** companies, deals,
> documents and compliance work, but creates, edits, decides, approves and assigns nothing,
> and sees tax identifiers masked. Wherever this document says "COMPLIANCE or ADMIN" (or
> lists ADMIN among those who write, decide, approve, assign, reveal or take in an RXIL
> package), read **COMPLIANCE** — or the holder of the named permission. The senior
> permissions (`exporters:assign_rm`, `compliance:assign`, `compliance:approve_high_risk`)
> are no longer "ADMIN, or the permission": they are held through the seeded **Sales lead**
> and **Compliance lead** roles. RXIL intake needs `exporters:partner_intake` (COMPLIANCE).

> **Amendment, 9 October 2026 — contacts and customer master data.** Routes are under
> `/api/v1/onboarding`; history rows are in `history-row.md` §2.
>
> * **Contact status.** A contact is ACTIVE, INACTIVE or LEFT_COMPANY
>   (`POST /exporters/{id}/contacts/{contact_id}/status`, `exporters:edit`); leaving
>   ACTIVE needs a reason, and a contact that is not active is never primary
>   (`ck_exporter_contact_primary_is_active`). `POST .../verification` stamps
>   `last_verified_at` / `_by`; `verification_due` is computed on read from
>   `CRM_CONTACT_REVERIFY_MONTHS` (default 12). The company list carries
>   `has_active_primary_contact` and filters on `missing_primary_contact=true`.
> * **Addresses.** `GET|POST /exporters/{id}/addresses`, `PATCH /addresses/{id}`,
>   `POST /addresses/{id}/default`, `POST /addresses/{id}/deactivate`
>   (`exporters:view` / `exporters:edit`). Types REGISTERED, BILLING, SHIPPING,
>   FACTORY_WAREHOUSE, CORRESPONDENCE; one active default per type; never deleted. A GST
>   registration may name its address (`exporter_gstin.address_id`, same company only).
>   The list says whether the default registered address changed after the last Clear.
> * **Bank accounts.** `GET|POST /exporters/{id}/bank-accounts`; `POST
>   /bank-accounts/{id}/approve|reject|verify|primary|deactivate|reveal`; `GET
>   /bank-accounts/pending`. Proposed (`exporters:manage_bank_accounts`), approved under
>   `CRM_BANK_CHANGE_APPROVAL_MODE` (OFF, SECOND_PERSON — the default, PERMISSION_HOLDER,
>   BOTH), verified by cheque, bank letter or a passed BANK_ACCOUNT verification
>   (`exporters:approve_bank_accounts`). A change is a new row (`replaces_id`); the old
>   account stays in force until the change is verified. Numbers are encrypted at rest
>   (`FIELD_ENCRYPTION_KEYS`) and served as `••••1234`; the full number only through
>   `reveal` (`exporters:view_bank_details`), which is audited. Only a VERIFIED account
>   is primary, one per currency.
> * **Payment terms.** `GET|POST /settings/payment-terms`, `PATCH
>   /settings/payment-terms/{code}` (versioned; `settings:manage` to change), and `PUT
>   /exporters/{id}/default-payment-term` (`exporters:edit`). The company responses carry
>   `default_payment_term_id`.
> * **Collections owner.** `POST /exporters/{id}/collections-owner` and `POST
>   /collections-owners/reassign` (`exporters:assign_collector`: COMPLIANCE and the lead
>   roles). Any active staff user; a reason to change or clear; `seen_user_id` refuses a
>   stale screen. Company responses carry `collections_owner_user_id` / `_name`; the list
>   filters on `collections_owner=me|none|<id>`.
> * **Groups.** `PUT /exporters/{id}/parent` (`exporters:edit`) sets
>   `parent_company_id` and `group_relationship` (SUBSIDIARY, BRANCH_OFFICE,
>   GROUP_COMPANY, JOINT_VENTURE); a loop is refused here and by
>   `trg_exporter_profile_no_group_cycle`. `GET /exporters/{id}/group` is the tree from
>   the ultimate parent (worked out on read), with each member's stage, check and risk
>   (for `compliance:view`), open deals and their value. `GET .../group/suggestions`
>   (`compliance:view`) lists companies sharing a director or beneficial owner; nothing
>   is linked automatically.
>
> **Amendment, 14 October 2026 — people (migration 0057).** A company's directors and
> beneficial owners are **people** on `exporter_contact`, beside its contacts: one row
> per person with roles `is_contact`, `is_director`, `is_ubo`, so a director who is also
> the main contact is one row. `POST /exporters/{id}/contacts` and `PATCH .../{contact_id}`
> take the roles and the optional person fields — date of birth, nationality, residence
> country, DIN (a director's), ownership % and control type (an owner's), identification
> type and number (stored encrypted). Only the name and a role are required; a rule
> broken is a 422. `GET .../contacts?role=CONTACT|DIRECTOR|UBO|ALL` (default `CONTACT`)
> lists them; the company detail embeds contacts only. Date of birth, DIN and the
> identification number are masked unless the viewer holds `exporters:view_full_tax_id`.
> A person is never deleted; adding a director or owner, or changing those roles, writes
> a `contact` history row (`person_added`, `person_roles_changed`). The sanctions
> screening and group suggestions read these people; the CRM no longer reads the old
> onboarding system's `ubo_record`, whose owners 0057 copied across with their ids.

**Owner:** Developer 2 · **Status:** implemented — §10 lists what is still open

Every gauge, deal, document and check in the CRM hangs off one company record.
This is what Developers 1, 3 and 4 build against: what a company is called,
which values its journey and marker take, which fields sit on it, and who may
write each one.

It fixes **vocabulary and rules**, not storage. Column types, whether GSTINs
are a child table or an array, and index names are migration 0014's to decide,
as long as they honour what is written here.

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
| `source` | How the company reached us | **yes** | The existing `ExporterSource` values. **Immutable once set**, enforced by the service and by `trg_exporter_profile_source_immutability`. `RXIL` for RXIL intake. `DEAL_BUYER` only for a company created as a deal's buyer, outside the pipeline: `POST /exporters` and the CSV import refuse it |
| `date_added` | When the record was created | server-set | Immutable |

`legal_name` / `incorporation_country` on `onboarding_request`, and the
`legal_name` the list response currently derives from it, are the legacy
source this replaces. No CRM query reads `onboarding_request`.

The single `gstin` field became `gstins` with migration 0014.

### 2.2 Descriptive fields (Developer 2)

Kept as they are today, editable by staff, each edit recorded (dimension `profile`): `industry`, `export_markets`, `products`,
`year_established`, `website`. (`website` is retired, §10; the legacy free-text
`relationship_manager` is read-only since 7 October 2026.)

The relationship manager is `relationship_manager_user_id`, set only through its own route
(§2.5). Being the RM never widens who sees identifiers (decision 12).

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
| `conversation` | Developer 3 | Developer 3's engagement contract (architecture: `NOT_CONTACTED`, tracked from `PROSPECT`) | engagement contract |
| `background_check` | Developer 4 | `NOT_STARTED` | background-check contract |

**None of these three columns exists yet.** Migration 0014 did not add them:
the conversation and background-check values are defined by contracts not yet
published, and qualification's lands with its tables (0017).
Each owner adds its own column in its own migration, with the default above.

**Only the owner writes its field**, through its own service, and writes the
history row in the same transaction (history contract §5). No other service
assigns to another developer's gauge field, including "just to keep it in
sync".

The background-check risk rating (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`, decision 6)
is Developer 4's. Whether it is also carried on the company record for list
filtering is Developer 4's call in the background-check contract.

### 2.5 Relationship manager (7 October 2026)

`relationship_manager_user_id` names the company's **one** relationship manager: an active
OPERATIONS user when written. It is written only by
`ExporterProfileService.set_relationship_manager`, each change a `relationship_manager` history
row with both ids, both names and the reason (`history-row.md` §2).

- **Claim and change.** An OPERATIONS user may set **themselves** on a company with no RM.
  Naming someone else, or changing or clearing an RM already set, needs ADMIN or
  `exporters:assign_rm` (a sales or CRM lead's custom role), and a change or clear needs a
  reason. `POST /exporters/{id}/relationship-manager {user_id, seen_user_id, reason}`; a stale
  `seen_user_id` is 409 `RELATIONSHIP_MANAGER_CHANGED`. An RM may also be named on create. The
  detail read serves `relationship_manager_actions` (`CLAIM`, `ASSIGN`, `CHANGE`, `CLEAR`) and
  every read the RM's name and `relationship_manager_inactive`.
- **Bulk.** `POST /relationship-managers/reassign` moves one RM's companies (all, a list, or one
  journey stage) to another, with a reason and a dry run; companies are locked in id order and
  any changed meanwhile skipped; one history row each, sharing a `bulk_run_id`.
- **Lists.** `GET /exporters?relationship_manager=me|none|inactive|<user id>`: My companies,
  Unassigned, a deactivated RM's companies. A filter only.
- **Ownership grants nothing**: not visibility and not unmasked identifiers (§5).
- **Required at the action, never by the database.** A lead may have none. Starting the
  background check on an in-pipeline company, and a person's `QUALIFIED`, need one in the same
  request (409 `RELATIONSHIP_MANAGER_REQUIRED`); imports, the RXIL intake, the platform's own
  loaders and buyer-only companies are exempt.
- **There is no free-text RM.** The old `relationship_manager` text was matched to RM
  accounts by a one-off command and dropped by migration 0061 (names no account matched
  were discarded, as decided on 14 October 2026). `POST /exporters` and
  `PATCH /exporters/{id}` refuse the field (422, the schemas forbid unknown fields); the RM
  is set through `POST /exporters/{id}/relationship-manager`.

---

## 3. Journey and marker rules

### 3.1 The journey moves forward only, and never by hand

| Move | Caused by | Written by |
|---|---|---|
| created at `LEAD` | Manual entry, bulk import | Developer 2's create path |
| arrives as `PROSPECT` | RXIL intake (decision 7) | Developer 2's RXIL intake. As built: created as a `LEAD` and moved to `PROSPECT` by RXIL's own `QUALIFIED` outcome, so every commit satisfies invariant 1; a delivery interrupted in between is finished by the next one |
| `LEAD` → `PROSPECT` | A qualification outcome of `QUALIFIED` is recorded | Developer 2, in the same transaction as the outcome |
| `PROSPECT` → `CUSTOMER` | The company is `PROSPECT` **and** its background check is `CLEAR` — whichever becomes true second (assumption A1) | Developer 2 |

Nothing else. In particular:

- **No person moves the journey directly.** There is no "move to next stage"
  action in the target model; each move is the consequence of a qualification
  outcome or a background-check decision. Today's
  `POST /onboarding/exporters/{customer_id}/transition` belongs to the old ten
  statuses and goes with them.
- **Never backwards.** A `CUSTOMER` whose check later becomes `FLAGGED` or
  `ON_HOLD` stays a `CUSTOMER`; the flag is visible and blocks deal handovers
  (assumption A5). A `NOT_QUALIFIED` lead stays `LEAD`, is never deleted, and
  can be re-reviewed (decision 8).
- **Never skipped.** `LEAD` → `CUSTOMER` does not exist. A lead whose check is
  already `CLEAR` becomes `PROSPECT` and then `CUSTOMER` in the same
  transaction, as two moves with two history rows.

Consequence for the allowed-moves endpoint (still unowned): for the
journey dimension, the set of moves a person may request is **empty**. The
journey still belongs in that endpoint's response (current value, and why the
next move has not happened), but it contributes no buttons.

### 3.2 The PROSPECT → CUSTOMER hand-off

Developer 4 decides `CLEAR`; Developer 2 moves the journey (architecture §8.2).
Both orders must work:

- **Qualified first, cleared second.** Developer 4's `CLEAR` decision is what
  completes the condition; the move follows from Developer 4's signal.
- **Cleared first, qualified second.** Developer 2's `QUALIFIED` outcome sees
  `background_check = CLEAR` on the record and moves straight through to
  `CUSTOMER`.

The move writes a `journey` history row and then announces
`company.became_customer` (event contract §3). The payload's `company_id`,
`name`, `country`, `pan` and `gstins` come from §2.1 of this contract;
`risk_rating` and `clearing_decision_id` come from Developer 4's decision.

**They commit together — one transaction** (implemented 29 September 2026 on the
audit's recommendation and confirmed by the lead on 4 October 2026). Developer 2's `ExporterProfileService.promote_to_customer_if_ready`
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

As built, on `GET /onboarding/exporters`: with no `marker` filter and no
search term — `name`, `pan`, `gstin`, `iec` — `ENDED` companies are excluded;
any search term includes them; `marker=ENDED` lists only them. `source` and
`status` are list filters, not search terms, and do not bring them back. The
marker is set and cleared through `POST /onboarding/exporters/{customer_id}/marker`
only; the edit route refuses it. The current reason is on the record
(`marker_reason`, `NULL` exactly when the marker is `NONE`, enforced by the
database) and every change is a `marker` history row.

The marker changes nothing else: not the journey, not any gauge, not any deal.

### 3.4 The list: what it can be narrowed by, and how many match

`GET /onboarding/exporters` narrows on the server, never in the browser, so a
filtered list is the server's answer and any count beside it stays true.

| Filter | Matching |
|---|---|
| `name` | Partial, case-insensitive |
| `pan`, `gstin`, `iec` | Exact, on the normalised value. Refused (403) for a role that may not reveal identifiers — an exact match answers "which company holds this" however the body is rendered |
| `source`, `journey`, `qualification`, `marker`, `pipeline_status` | Exact |
| `country` | The ISO code, whole and case-insensitive |
| `industry` | Partial, case-insensitive — typing `m` finds every industry holding an `m` |
| `background_check` | Exact. **Refused (403) for a role that may not read a background check** (D8 — DEVELOPER). The state is blanked on the rows for the same role: the list must not become a second way to read compliance work, and a filtered list names the flagged companies whether or not the column is rendered |
| `trade_role` | Which side the company has traded on, by participation. `BOTH` means both sides, not either. Asking for `BUYER` lifts the buyer-only exclusion |
| `has_open_deals` | Whether the company has a deal that is neither handed over nor withdrawn, **as the selling company** |
| `relationship_manager` | `me`, `none`, `inactive` or a user id. Ownership narrows; it never changes what a reader may see |
| `missing_primary_contact` | Companies with no active primary contact |
| `collections_owner` | `me`, `none` or a user id |

A blank value is not a filter: `?country=` and `?industry=` are the same as not
asking, which is what a cleared control sends.

**`total`** is the number of companies the filters match, behind the page — a
`count(*)` over the same conditions the page is drawn from. **Every filter in this
table applies to both**, and two things keep that true: the route builds one set of
keywords and passes it to the search and the count alike, and `_repository_filters`
turns that set into conditions once, including the identifier clean-up and the two
default exclusions.

Both halves have failed before, which is why both are stated. First the clean-up ran
only on the search, so a lower-case PAN found one company and counted none. Then three
filters — `missing_primary_contact` and the two collections-owner filters — were passed
to the search and left out of the count, so an empty list sat under a total of 48.
Adding a filter means adding it to the one keyword set; passing it to either call on
its own is the mistake both failures were.

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
other company (subject to §5's masking). As built: create, edit and
detail responses carry `gstin_warnings: [{gstin, other_customer_ids}]`, empty
when there is nothing to warn about; the GSTIN in a warning is masked like
every other identifier. Only the database's per-company uniqueness
(`uq_exporter_gstin_customer_gstin`) exists — never a global one.

### 4.1 A GST registration is a branch

`exporter_gstin` grew in place rather than being copied into a `gst_registration`
table. A row is now a **branch**: a GSTIN plus the state it was issued in, the GST
portal's status, its address, a compliance flag, and whether the company still uses it.

> **Amendment, 14 October 2026.** A branch's address is its linked company address
> (`address_id`) only. `POST /exporters/{id}/gst-registrations` refuses a free-text
> `address` (422). The text stored before was turned into `CORRESPONDENCE` company
> addresses linked to their branches (city "Not recorded", for a person to correct) by a
> one-off command, and migration 0061 dropped the column.

Three facts that are easy to confuse, kept apart:

| Column | Whose answer it is |
|---|---|
| `status` (`UNVERIFIED` / `ACTIVE` / `CANCELLED` / `SUSPENDED`) | the **GST portal's**. `UNVERIFIED` is the default and means "nobody has checked", deliberately not `ACTIVE`, which would be a claim |
| `active` | **ours** — whether we still use this branch |
| `flag_status` (`NONE` / `FLAGGED`) | **compliance's** |

`state_code` and `state_name` are **derived** from the GSTIN's first two characters
(`domain/gst_states.py`) and never entered: a typed state could contradict the GSTIN
beside it. A state code this release does not know keeps `state_name = NULL` —
recorded as unknown rather than guessed, because the format check accepts any two
digits.

**A registration is never deleted.** `trg_exporter_gstin_no_delete` refuses it, and
`gstin_rows` no longer cascades `delete-orphan`. Before 0035 a company edit that
dropped a GSTIN deleted its row; once a deal records its invoicing branch that delete
hits `fk_deal_seller_gst_registration_id`'s `RESTRICT`, and where it succeeded it
destroyed the record of a branch the company really traded through. Dropping one is a
**deactivation**, and re-adding the same GSTIN reactivates that row rather than
inserting a second — so there is one row per `(company, GSTIN)` forever.

`PATCH /exporters/{id}` **no longer accepts `gstins`** (422). Adding,
deactivating and flagging a branch are three decisions with three routes under
`/exporters/{id}/gst-registrations` and `/gst-registrations/{id}`, each leaving its
own `gst_registration` history row with the GSTIN masked. `company.gstins` means the
**active** ones.

**Flagging is per branch and per company.** A company trading through five states may
have a problem in one of them, so a flag blocks handovers only for deals invoiced
through *that* branch. A reason is required to flag **and**
to unflag — the first is what the block will say, the second is why we decided the
problem was resolved — and `ck_exporter_gstin_flag_reason` holds the first at the
database. Because a GSTIN may legitimately sit on two companies, flagging one
company's row does **not** touch the other's; the flag response names the other
holders so nobody believes they have stopped trade that is still running.

**DEVELOPER is not served flags** (decided 4 October 2026): a flag is a
compliance judgement, withheld for D8's reason. On `GET …/gst-registrations` its
`flag_status` and `flag_reason` are `null` and `flagged_count` is `null`; its history
omits the flag and unflag rows and the `flag_status` detail. OPERATIONS keeps them —
a flag blocks the deals it works on, and the refusal names it.

Flag and unflag are **COMPLIANCE and ADMIN only**. Recording and deactivating a
branch stay with STAFF: which branches a company trades through is a record a
relationship manager keeps.

A "verify on the GST portal" link is served only to a role that sees the full GSTIN,
because the link contains it.

**Bulk import matching** (assumption A14) matches an incoming row to an
existing company on PAN, then GSTIN via its embedded PAN, then IEC, then CIN,
and reports every row as accepted, rejected, or possible duplicate. It never
merges two companies on its own.

**As built** — one algorithm, `CompanyMatcher`, for bulk import
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
manual creation, editing and import. An imported row is `accepted` (`created` as a
`LEAD` or `matched`), `rejected` or `possible_duplicate`; RXIL refuses a
conflict or possible duplicate with 409. Neither ever makes a `CUSTOMER`.

**Import files.** `POST /onboarding/imports/companies` takes a CSV (UTF-8) or an Excel
workbook (`.xlsx`, read from its *Companies* sheet, or its only sheet). An old `.xls`
is refused with a 422 that says to save it as `.xlsx` or `.csv`.
`GET /onboarding/imports/companies/template?format=xlsx` is the Excel template: an
*Instructions* sheet (every column: whether a value is needed, what to enter, an
example, the allowed values), a *Companies* sheet with dropdowns for country and
source, and identifier columns stored as text; `format=csv` (the default) is the
header row as before. In a row, `country` may be the ISO code or the country's name,
and `source` the code or its label ("Existing customer"); both become the code before
any rule runs. `POST /onboarding/imports/companies/preview` reads a file exactly as
the import would and returns its columns, first rows, row count and header problems
(`missing_columns`, `unknown_columns`, `duplicate_columns`, `ready`), saving nothing;
a file it cannot read at all is the same 422 the import gives.

---

## 5. Who may see and do what

Unchanged from what Developer 1 built (architecture §3.7, decision 12):

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
  item O4, confirmed by the lead on 4 October 2026). There
  is no CIN search filter yet.
- **Name search** (case-insensitive, partial) is open to every reader.
- **Being a company's relationship manager changes none of this**: an RM sees their own
  companies' identifiers masked, and reads every company the role may read (§2.5).
- **Stale edits.** `PATCH /exporters/{id}` takes an optional `seen` map: each edited field's
  value as the screen showed it, masked where it was masked. Under the row lock, a field
  someone else changed since refuses the whole edit (409 `COMPANY_FIELD_CHANGED`, naming who
  and when from the field's last history row, and the current value as the caller may see it).
  Field-level on purpose: the gauges share the row, so a record-level check would refuse an
  RM's edit whenever compliance moved the check.

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
| `profile` | each edit of an identity or descriptive field | old value → new value | — |
| `qualification` | see `criterion-result.md` §6 | | |

**Event types.** The journey keeps the names its rows have always had —
`lifecycle_initial` / `lifecycle_transition` — because a downstream consumer
(ANER-4.2-S1T2) polls for them (history contract §3). Every other Developer 2
dimension uses the contract's derived names (`marker_transition`,
`profile_transition`, ...). Since migration 0020 every journey row — the `LEAD` row at
creation, the `LEAD` -> `PROSPECT` move a `QUALIFIED` outcome makes, and an
RXIL intake's rows — uses these two names, and carries `terminal` in its
details: `false` for `LEAD` and `PROSPECT`; `true` for the move to `CUSTOMER`
(§3.2). Rows written before 0020 for the ten old
statuses are kept as they were.

**Allowed moves are served, not copied.** Each company response carries
`allowed_marker_moves` — the marker values this viewer may set from here, each
with `reason_required` — and the qualification response carries
`allowed_outcomes` and `can_record_results`. The frontend offers exactly those
and holds no transition table. The journey has no allowed moves: it is never
moved by hand. The cross-gauge allowed-moves endpoint remains open item O6.

**How a `profile` row is written** (built). One row per field whose
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
`cin` and `registration_number` are written masked (`registration_number` since 4 October 2026;
before it the full value was written), and the history route masks them again when it
serves a row, so a row written before then is served masked too without being rewritten
(the log is append-only).

**`identity_type` follows the edit**: it is recomputed whenever `pan` or
`registration_number` changes, by the same rule as on create. An edit that touches
`country`, `pan` or `registration_number` must leave the company identifiable:
moving a PAN-less company abroad without a number, or clearing a foreign company's
number, is refused (422). A buyer the buyer migration created with no number keeps its
exemption from the identity rule until one is added. Migration 0043 corrected the rows edited before this.

**The completion list** (unidentified buyers go "to the completion
list"). `GET /companies/identity-completion?limit=&offset=` (every CRM reader, DEVELOPER
included; API_USER 403) lists the companies with `identity_type` NULL — neither a PAN
nor a registration number — that are not `ENDED`. Each item says what the company lacks,
`missing`: `COUNTRY` when it has none, `REGISTRATION_NUMBER` outside India, `PAN` in
India; and `required`, which is true for the first two and false for a PAN, which
is only worth having. Required ones come first, then oldest first. An item carries
`company_id`, `name`, `country`, `pipeline_status`, `created_via` and `created_at`, and
**no identifier** (the companies have none), so nothing in it is masked. It is a work
list, not a pipeline filter: completing a company is the ordinary edit on its own page,
and because that edit recomputes `identity_type`, the company leaves the list at once.
The company page shows the same gap as a notice while `identity_type` is NULL. Limit
1–200, default 50.

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
| O2 | The ANER-4.2-S1T2 consumer watches `lifecycle_transition` rows for `ONBOARDED` (the `terminal` flag). That status is gone (migration 0020). Journey rows keep the `lifecycle_*` event types and the `terminal` flag, which only `CUSTOMER` will set — confirm that `CUSTOMER` is the replacement | Programme lead, with whoever owns that consumer |
| O3 | ~~Do Developer 4's `CLEAR` and Developer 2's `CUSTOMER` move commit in one transaction?~~ **Implemented as one transaction** (§3.2, 29 September 2026) — confirmed by the lead on 4 October 2026 | Programme lead, Dev 2, Dev 4 |
| O4 | Is CIN masked like PAN/GSTIN/IEC? Recommendation: **yes** until decided — widening later is safe, narrowing later is not | Programme lead (decision 12's scope) |
| O5 | ~~Profile-history rows for tax identifiers: masked in the row, or stored in full and masked on read?~~ **Settled for the prototype: masked in the row** (§6). Revisit only if the history read route gains role-based masking | Dev 2 with Dev 1 — Dev 1 to acknowledge |
| O6 | ~~Who owns the allowed-moves endpoint~~ **Resolved in practice:** there is no single endpoint — each gauge's owner serves its own allowed moves (`allowed_marker_moves`, qualification's `allowed_outcomes`, the conversation's and background check's `allowed_moves`, the deal's `allowed_stage_moves`, `can_open_deal`), and the frontend keeps no copy | Programme lead |
| O7 | ~~How a `profile` history row records an empty value.~~ **Settled: values in `event_metadata`, `to_status` names the field** (§6) | Dev 2 with Dev 1 — Dev 1 to acknowledge |

---

## 10. What is implemented today

Stated separately so nobody reads this contract as a description of the code.

| Item | State |
|---|---|
| Company id (as `customer_id`), `source` immutability, descriptive fields | **implemented** |
| IEC column | **implemented**, format not yet checked |
| Server-side masking and identifier-search refusal | **implemented** (Dev 1) |
| `journey` history rows (`lifecycle_*`, with `terminal`) | **implemented** — for the three journey stages; older rows for the ten statuses are kept |
| `name` / `country` / `cin` as columns on the company record | **implemented** (0014). The transitional identity store is deleted; no CRM code reads a company's identity from `onboarding_request` |
| `onboarding_history` on the company detail | **removed** |
| Retiring the ten old statuses | **implemented** (migration 0020): `lifecycle_status`, its enum, the transition route and the frontend's copy of the graph are gone |
| The move to `CUSTOMER` | **implemented** — both orders, in the completing move's transaction, announced after the commit (§3.2) |
| `allowed_marker_moves` on company responses; `allowed_outcomes` / `can_record_results` on qualification | **implemented** |
| `gstins` (several, `exporter_gstin`), PAN format and uniqueness, GSTIN format and PAN cross-check, duplicate-GSTIN warnings | **implemented** (0014) |
| `marker` and `marker_reason`, the marker route, ENDED off the default list | **implemented** (0014) |
| List filters (`country`, `industry`, `background_check`, `trade_role`, `has_open_deals`) and `total` on the search response | **implemented** (§3.4). The background-check state is blanked, and its filter refused, for a role that may not read background checks; `has_open_deals` reads the selling side |
| `journey` (`LEAD`/`PROSPECT`/`CUSTOMER`) and `qualification` columns | **implemented** (0017); the old `lifecycle_status` beside it was dropped in 0020. Qualification moves it `LEAD` -> `PROSPECT` |
| `conversation`, `background_check` fields | **implemented** — Dev 3A's 0016 and Dev 4A's 0015 (see §2.4) |
| The ORM declares every index and constraint 0014/0017 created (PAN unique, the outcome chain) | **implemented** — checked by `test_orm_matches_the_onboarding_schema.py` |
| `website` | **retired**. No write path accepts one — the request schemas refuse the field (422) and the CSV importer reads the old `website` column and ignores it — and no response carries one. The column and every stored value are kept: nothing is destroyed, nothing is shown |
| `registration_number` | whatever the company's own registrar issued, for a company not identified by a PAN. **Required for a company outside India** that holds no PAN; stored as the registrar writes it and compared with everything but the ASCII letters and digits removed, upper-cased — exactly the unique index's expression, so a lookup and an insert can never disagree — so one number cannot be entered twice per country (`uq_exporter_profile_country_registration_number`). A number with no ASCII letter or digit is refused (422). A duplicate is refused with 409 `DUPLICATE_REGISTRATION_NUMBER` naming the holder, like a PAN — unlike a GSTIN, which stays warn-only. Masked like CIN |
| `profile` history on edits; clearing a field | **implemented** |
| Real links from contacts, activities, screening items, GSTINs and history | **implemented** (0014, `ON DELETE RESTRICT`); `verification_result.entity_reference` deliberately has none |
| `name` required by the database | **not built** — waits for the unnamed create path to go |
