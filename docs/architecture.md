# Exporter CRM — architecture

What the CRM is, how it is put together, the rules each part enforces, and who owns
what. It describes the code as it stands, and the exact shapes each part promises the
others are the contracts in [`contracts/`](contracts/). The design it was built from
was `Exporter-CRM-Architecture-and-Plan.pdf` (v1.0, 25 September 2026), retired on 4 October 2026 as outdated; recover it with `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf`.
Where this page says "§x.y" it means a section of that PDF; this page and
[`plan.md`](plan.md) now stand in for it.

---

## 1. What the CRM is, and is not

An internal CRM for exporters combined with a verification and compliance record.
Staff create companies, qualify them, run the sales conversation, record background
checks, open deals, gather their paperwork, and hand deals to the lending team.

Companies come from two kinds of source (§2.1):

- **RXIL**, a partner that sends exporters it has already filtered, with its own
  results. They arrive already qualified (decision 7) and RXIL's results are stored as
  given, never recomputed.
- **Everyone else** — found by staff, entered by hand or imported from a CSV file. For
  these the CRM does the qualification and the checks itself.

It does **not** decide whether to lend, keep money records, run the internal logic of
compliance checks, or process transactions (§2.3). It records outcomes; other teams own
their decisions.

**Principles that apply everywhere** (§2.6): history is never lost (a correction is a
new record pointing at the one it replaces); nothing but the history is permanent;
every decision records who or what made it and on what evidence; a problem stays where
it happened (a buyer's problem never touches the company); the server is the authority
(allowed moves, roles, masking and validation are enforced server-side, and the
frontend asks rather than keeping copies); anything not yet real is labelled as such.

## 2. Where it lives and how it is built

- **Backend:** FastAPI, SQLAlchemy (async), PostgreSQL, Alembic. The CRM is
  `backend/app/modules/onboarding` (its `exporter_profile` family of tables, services
  and routes under `/api/v1/onboarding`). The same module also holds a **legacy**
  onboarding path — `onboarding_request`, an 18-state machine and a Temporal
  workflow — which is out of scope and not built on (§2.4).
- **Frontend:** Vite, React 18, TypeScript, TanStack Query, Tailwind. The CRM screens
  are `frontend/src/modules/onboarding`.
- **The generated API contract.** `frontend/openapi.json` and
  `frontend/src/lib/api/schema.ts` are generated from the backend and committed;
  `backend/tests/contract/test_openapi_artifact_is_current.py` fails when they drift.
- **This checkout contains more than the CRM.** It began as a pruned copy of a wider
  platform; `ledger`, `settlement`, `rails`, `fx`, `reconciliation`, `payments`,
  `reporting` and `orchestration` are schema only. [`../RUNNING.md`](../RUNNING.md)
  explains what was kept and why.

**The module rule, and its one exception** (§2.5). All connecting code lives in the
`onboarding` module. No file in `kyb`, `cases`, `customers` or `compliance` is edited;
`onboarding` may use them and nothing may use `onboarding`. The single exception —
role checks on two compliance read routes — is recorded in
[`module-rule-exceptions.md`](module-rule-exceptions.md) (EX-001), and no other
exception is allowed without the same written record. Module boundaries are enforced
by import-linter (`backend/importlinter.ini`, one private-internals contract per
module).

**Platform patterns the CRM relies on:**

- *Append-only by the database, not by discipline.* Decisions, reviews, history rows,
  activities and follow-up completions are protected by triggers that refuse `UPDATE`
  and `DELETE` (`public.prevent_mutation()`). Documents and verification results are
  never deleted, a document's identity is fixed once set, and a `HANDED_OVER` or
  `WITHDRAWN` deal no longer changes (migration 0022). Every such rule has a test that
  tries the violation in raw SQL.
- *Ports owned by the consumer.* Verification adapters, storage and the scanner are
  `Protocol`s defined where they are used; implementations satisfy them structurally.
- *One transaction per operation.* A service validates everything before it assigns
  anything, writes the history row through the shared writer (which flushes and never
  commits), and commits once.

## 3. The model

Every company has **one record** (`exporter_profile`, keyed by `customer_id`). On it
sit the **journey**, a **marker**, and the current value of each of **three gauges**;
**deals** hang off the company. Every change to any of them writes a row to **one
shared history log**, so the full story of a company is one query (§3.1). Each gauge
moves independently of the others — only the rules below connect them.

| Part | Values | Owner |
|---|---|---|
| Journey | `LEAD` → `PROSPECT` → `CUSTOMER` | Developer 2 |
| Marker | `NONE`, `PAUSED`, `ENDED` | Developer 2 |
| Qualification gauge | `NOT_YET_REVIEWED`, `QUALIFIED`, `NOT_QUALIFIED` | Developer 2 |
| Conversation gauge | `NOT_CONTACTED`, `REACHING_OUT`, `SPOKE_TO_THEM`, `INTERESTED`, `NOT_NOW`, `READY_NOW` | Developer 3A |
| Background-check gauge | `NOT_STARTED`, `IN_REVIEW`, `MORE_INFO`, `CLEAR`, `FLAGGED`, `ON_HOLD` | Developer 4A |
| Deal (per deal) | `OPEN`, `GATHERING_PAPERWORK`, `HANDED_OVER`, `WITHDRAWN` | Developer 3B |

Every child record has a real foreign key to its company (`ON DELETE RESTRICT`). PAN
is unique across companies; a company may hold several GSTINs, and a GSTIN held by
another company is a warning, not a refusal (decision 4). Contract:
[`contracts/company-record.md`](contracts/company-record.md).

A company created as a deal's buyer is **not in the pipeline** (`pipeline_status =
NOT_IN_PIPELINE`, plan P4-1, P4-2): nobody is selling to it, so it has no journey history
and stays out of the pipeline's lists until someone brings it in (P4-9). A company is
identified by its PAN or, outside India, by its registration number (`identity_type`,
IQ-7); one with neither is listed for completion. Each GSTIN is a **branch** of its
company (P6-1): it is deactivated, never deleted, and Compliance may flag it, which blocks
the deals invoiced through that branch only (BQ-6).

## 4. The state machines

Each is enforced by its owner's service, and the allowed next moves are served to the
screen by the server rather than copied into the frontend.

### Journey — forward only, never by hand

- `LEAD` → `PROSPECT`: when a qualification outcome is recorded as `QUALIFIED`
  (including an RXIL delivery, decision 7).
- `PROSPECT` → `CUSTOMER`: when the company is a `PROSPECT` **and** its background
  check is `CLEAR`, whichever becomes true second (decision 2). See §5.
- The journey never moves backwards. A reopened, flagged or held check leaves a
  customer a customer (assumption A5). Leaving or pausing a relationship uses the
  marker.

### Marker — commercial pauses and endings, not compliance

`NONE` → `PAUSED` or `ENDED`, `PAUSED` → `ENDED` (reason required), and either back to
`NONE`. `ENDED` companies are hidden from default lists but stay searchable. A
compliance concern is recorded on the background check, never as a marker.

### Qualification gauge — did they meet our requirements?

Criteria are settings (versioned rows ADMIN manages), not code. Staff record a result
per criterion with evidence; the server suggests an outcome, and a person records it.
`NOT_QUALIFIED` needs at least one reason code and stays a `LEAD`; it can be
re-reviewed. `QUALIFIED` is final in the prototype (assumption A2). Contract:
[`contracts/criterion-result.md`](contracts/criterion-result.md).

### Conversation gauge — how is the sales relationship going?

Applies from `PROSPECT` onward (assumption A4). Any value may follow any other except
itself (it is a judgement); `NOT_NOW` needs a check-back date that is not in the past
(compared with the UTC date). Opening a deal sets `READY_NOW` in the same transaction
(seam S1). Follow-ups are activities with a due date; completing one adds a locked
completion record, and the Follow-ups screen shows every due and overdue one to the
whole team. Contract: [`contracts/engagement.md`](contracts/engagement.md).

### Background-check gauge — is it safe and lawful to work with them?

Every move is a new, locked decision record that supersedes the previous one; nothing
is edited. The nine moves (§3.3), enforced both by the service and by the database
(`ck_background_check_decision_move`):

| From | To | Who | Needs |
|---|---|---|---|
| `NOT_STARTED` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | — |
| `IN_REVIEW` | `CLEAR` | COMPLIANCE, ADMIN | a reason, a risk rating, and the `CLEAR` prerequisites (§6) |
| `IN_REVIEW` | `MORE_INFO` | COMPLIANCE, ADMIN | a note of what is needed |
| `MORE_INFO` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | a note of what arrived |
| `IN_REVIEW` | `FLAGGED` | COMPLIANCE, ADMIN | a reason |
| `FLAGGED` | `ON_HOLD` | COMPLIANCE, ADMIN | a reason |
| `FLAGGED` or `ON_HOLD` | `IN_REVIEW` | COMPLIANCE, ADMIN | a reason (reassessment) |
| `CLEAR` | `IN_REVIEW` | COMPLIANCE, ADMIN | a reason (reopen, decision 5) |

There is no `CLEAR` → `FLAGGED`: new information about a cleared company is acted on
by reopening it first. **Risk** (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, decision 6) is
required on `CLEAR` and refused on every other move; the screen keeps showing the last
recorded risk, labelled as such, after a reopen (D6). Each move locks the company row,
pins an evidence snapshot (the verification results, screening rows and the company's
own `AVAILABLE` documents it rested on), writes one history row and commits once. A
screen that sends the value it was looking at gets a 409 if the gauge moved meanwhile.

**Two people for `CLEAR`, `FLAGGED` and `ON_HOLD`** (maker-checker, decision A, since 1
October 2026): one COMPLIANCE or ADMIN user proposes the move, the gauge shows "awaiting
approval" without moving, and a *different* one approves it (or rejects it; the
proposer may withdraw it). A `CLEAR` also needs KYB, AML and sanctions passed in the
current check cycle (rule B), and is current for one year (configurable): an expired
Clear still reads `CLEAR` but no longer promotes a company, and is listed as "Re-KYC
due". Contract: [`contracts/background-check.md`](contracts/background-check.md) §12.5–§12.7.

### Deal — is there a real, current need?

| From | To | Needs |
|---|---|---|
| `OPEN` | `GATHERING_PAPERWORK` | — |
| `OPEN` or `GATHERING_PAPERWORK` | `WITHDRAWN` | a reason |
| `GATHERING_PAPERWORK` | `HANDED_OVER` | a buyer, and the handover guard (§5) |

`HANDED_OVER` and `WITHDRAWN` are terminal: a terminal deal's buyer cannot be changed
and it takes no more documents. A company may have any number of deals, but **only a
`PROSPECT` or a `CUSTOMER` may have one opened** — a `LEAD` is refused with
`DEAL_COMPANY_NOT_READY` — because opening a deal moves the conversation, which does
not apply to leads. Each deal has at most one buyer (its own row, `deal_buyer`), and
checks about a buyer attach to the buyer, never to the company (decision 9). Contract:
[`contracts/deal-and-buyer.md`](contracts/deal-and-buyer.md).

**A deal's buyer is becoming a company record** (P4-4): `deal.buyer_company_id` names
the company the buyer *is*, set once, and the legacy `deal_buyer` row stays until every
environment has run the buyer migration (P4-6). "A handover needs a buyer" is satisfied
by either, so the migration is a data migration and not a behaviour change.

**What two companies have traded** is separate from the deal between them, and separate
from any judgement about it: a trade relationship is the ordered pair, its invoices are
what was billed, and an outcome is what became of each invoice — recorded after the
handover, because what happened to the money is not a deal stage. Amounts stay in the
currency they were invoiced in and nothing is totalled (IQ-4). Contract:
[`contracts/trade-history.md`](contracts/trade-history.md).

## 5. The move to CUSTOMER, and the handover

**The move to `CUSTOMER` is one transaction** with the move that completes its
condition (decision U4, implemented as the audit recommended; awaiting the programme
lead's written confirmation). `ExporterProfileService.promote_to_customer_if_ready`
flushes and never commits; it is called:

- by `BackgroundCheckService` when it records `CLEAR` (qualified first, cleared
  second), and
- by `QualificationService` when a `QUALIFIED` outcome moves a `LEAD` to `PROSPECT`
  whose check is already `CLEAR` (cleared first, qualified second).

Both callers lock the company row first, so a `CLEAR` and a `QUALIFIED` landing at the
same moment make the move exactly once, and no committed state is ever `PROSPECT` and
`CLEAR` at once. The move writes a journey row with `terminal: true` and, after the
commit, announces `company.became_customer`. It is idempotent: a customer that is
reopened and cleared again is not promoted or announced twice.

**The handover guard** (assumption A5, extended by plan P2-5b, P3-3b, P3-4, P4-7 and
P6-7): a deal may be handed over only when its company is a `CUSTOMER` whose background
check is `CLEAR` and not expired; its required documents are present and scanned clean;
the seller has no `FAILED` sanctions or AML result (BQ-3); the buyer's sanctions and AML
are both `PASSED` (BQ-4); and, when the seller has an active GST registration, the deal
records an invoicing branch that is neither flagged (IQ-20, BQ-6) nor deactivated
(R-19, decision D-04). Until then the deal names
every unmet condition (`domain/handover_conditions.py`, contract `deal-and-buyer.md`
§6.1). The guard share-locks both companies, in `customer_id` order, while the handover
commits (D10), so a concurrent flag or reopen waits. The
handover snapshots the deal's buyer and document ids, writes the history row, and after
the commit announces `deal.handed_over` to the lending team.

## 6. Checks behind the background check — verification and screening

The background check does not run checks; it records a decision **on inputs** owned by
Developer 4B, read through one read-only seam (`domain/compliance_inputs.py`, the
4A ↔ 4B contract):

- **Verification results** (`verification_result`). Recorded through adapters; in the
  prototype the route accepts `provider="manual"` only (D7) and an RXIL stub exists for
  the future intake. A manual `PASSED` needs a note or at least one evidence reference
  (D16); a manual `PENDING` is refused. Evidence references are documents (which must
  exist, belong to the subject and be `AVAILABLE`) or `http(s)` links. Reviews form an
  append-only chain: a later review must name the current one and give a note, or it is
  refused as stale (409). A reviewed result can never be changed by polling a provider
  (service rule and database trigger). Subjects are a company (`EXPORTER`) or a deal's
  buyer (`BUYER`, by `deal_buyer.id`); a new check on a buyer of a closed deal is
  refused (D17). Each result says where it came from (`MANUAL`, `STUB`, `PROVIDER`) and
  whether it is a placeholder.
- **The screening checklist** — seven items served by the server
  (`SCREENING_CATALOGUE`; `website-reviewed` was retired on 1 October 2026, plan P2-4a:
  its rows are kept and readable, a new answer to it is refused), each decision
  `PASSED`, `FAILED`, `EXEMPT` or `NEEDS_REVIEW`, recorded as a new row with its own
  history (D9) and optional `{type, ref}` evidence (P2-1b). COMPLIANCE and ADMIN decide.
- **Check cycles** (1 October 2026, plan P2-3) — every result, answer and decision
  belongs to a KYC/KYB round (`check_cycle`); the check decides on the current one only.
  A Re-KYC / Re-KYB starts the next cycle (COMPLIANCE, ADMIN) and, on a `CLEAR` company,
  reopens it in the same transaction. Rows recorded before cycles read as cycle 1
  (`contracts/background-check.md` §12.3).
- **Bank activity** — the panel is honest: no provider feed is connected
  (`NOT_CONNECTED`), and no findings are invented.

**What `CLEAR` requires** (A3, as settled in D1–D4 on 28 September 2026 and carried by
`CLEAR_POLICY`): a risk rating; no check still pending (`PENDING`; `REVIEW` without an
`ACCEPTED` or `REJECTED` review; any placeholder); every screening item of the
catalogue (seven since 1 October 2026; eight before — a decision's `rules_version` says
which) `PASSED` or `EXEMPT` (a `FAILED` item means `FLAGGED`, not `CLEAR`); and at least
one pinned evidence id — all read from the company's **current check cycle**. A `FAILED` verification does not block `CLEAR` by itself — compliance
weighs it. The details are in `contracts/background-check.md` §14 and
`contracts/verification-and-screening.md` §11 (Developer 4B's decisions).

## 7. Documents and storage

A document belongs to exactly one company or one deal. Categories are a fixed list the
server checks; document types within them are settings
(`deployments/gitops/reference-data/crm/documents/document-types.yaml`). Only a
relative storage key is stored, never a cloud address. Every upload lands
`PENDING_SCAN` and cannot be opened; a clean scan makes it `AVAILABLE`, an infected or
failed scan makes it `QUARANTINED` or `SCAN_FAILED`, never served. Downloads use signed,
expiring links and the caller's role. In the prototype the storage is local disk and
the scanner is a clearly labelled pass-through. Contract:
[`contracts/storage-and-documents.md`](contracts/storage-and-documents.md).

## 8. History and events

- **History** — one append-only table, `exporter_lifecycle_history`, with a
  `dimension` per part of the model (`journey`, `qualification`, `marker`, `profile`,
  `conversation`, `deal`, `background_check`, `verification`, `screening`). Every state
  change writes its row in the same transaction, with the actor from the login session.
  Rows written in one transaction share a timestamp, so their order between themselves
  is not chronological. Read through `GET /exporters/{id}/history` and
  `GET /deals/{id}/history`. Contract: [`contracts/history-row.md`](contracts/history-row.md).
  The History tab says what changed, not only the value reached: a buyer change reads
  "Buyer recorded" or "Buyer updated: …", and a screening, criterion or check row names
  its item, criterion or check type — from the details keys the contract guarantees
  (§3) and the labels the server serves.
- **Who acted, by name.** Records store the actor as a user id. Every response a person
  reads it from — history rows, background-check decisions, activities, follow-ups and
  their completions, screening decisions and verification reviews — also carries the name
  (`actor_name`, `decided_by_name`, `reviewed_by_name`, `completed_by_name`), resolved
  when read through the platform's auth facade (`display_names`, called from
  `api/actor_names.py`) rather than by giving staff the user list. OPERATIONS, COMPLIANCE and ADMIN get the account's full name or, failing
  that, its email; DEVELOPER gets the full name only. No actor reads "By the platform".
- **Events** — two announcements, each published after the commit that made it true
  and best effort (the history row is the source of truth): `company.became_customer`
  and `deal.handed_over`. The default bus is in memory and no receiver is built yet
  (decision 10). Contract: [`contracts/event-envelope.md`](contracts/event-envelope.md).

## 9. Roles and masking

Five roles (§3.7). Staff are OPERATIONS, COMPLIANCE and ADMIN; DEVELOPER is read-only;
`API_USER` — what public sign-up grants — reaches nothing in the CRM (asserted by
`test_api_user_reaches_nothing_in_the_crm`).

| Can… | OPERATIONS | COMPLIANCE | ADMIN | DEVELOPER |
|---|---|---|---|---|
| See companies, contacts, deals, documents, history | yes | yes | yes | read, masked |
| See full PAN / GSTIN / IEC / CIN; search by them | no (masked) | yes | yes | no (masked) |
| Create and edit companies, contacts, activities; set the marker | yes | yes | yes | no |
| Record qualification results and outcomes; import a CSV | yes | yes | yes | no |
| Manage qualification criteria; RXIL company intake | no | no | yes | no |
| Set the conversation; open and move deals; record buyers; upload documents | yes | yes | yes | no |
| Start a background check; answer `MORE_INFO` | yes | yes | yes | no |
| Other background-check moves; screening decisions; record and review verification results | no | yes | yes | no |
| Read the background check, verifications and screening | yes | yes | yes | **no** (D8) |

**Masking is done by the server** (`api/schemas/masking.py`), never only by the
browser: a caller reading the JSON directly must not get what the matrix hides. Tax
identifiers show only their last four characters to roles that may not reveal them;
contact emails and phones, and a deal buyer's identifiers and contact details, are
masked the same way; a profile-history row stores identifiers already masked. An exact
search of the company list by PAN, GSTIN or IEC is refused to those roles. Matching a
buyer is the one exception (BQ-2): `POST /companies/match` names the company that holds a
full PAN, GSTIN or registration number the user typed — never the identifier itself — and
every such lookup is audited. DEVELOPER does not receive `background_check`,
`verification` or `screening` history rows, nor the risk rating and clearing decision
recorded on the `CUSTOMER` journey row, since D8 refuses it that data on those gauges'
own routes; for the same reason a deal response gives DEVELOPER no stage moves and no
handover-blocked reason. GST branch flags are withheld from DEVELOPER the same way (R-47, decision
D-05): a registration's `flag_status` and `flag_reason`, the list's `flagged_count`, the
flag and unflag history rows and the `flag_status` detail on the others.

**Design principle:** a role that cannot reveal a value gets no reveal control at all,
not a disabled one — a disabled eye icon would still leak "this data exists, you're
just not allowed".

**The screens fail closed** (`frontend/src/platform/access`, R-33 Phase 0): each role's
capabilities are an allowlist mirroring the groups above, and a role nobody listed has
none. A screen or control a role may not use is absent, and its address shows the same
"Page not found" as one that does not exist; the API user gets no workspace. This only
avoids offering what the server would refuse — the server still enforces every rule.

**Roles as data.** User and role management (`/api/v1/auth/users`,
`/api/v1/auth/roles`, the Settings screen) is gated by permissions, and built-in roles
are editable. The CRM routes, however, still check the five built-in roles; the
permission catalogue marks the CRM permissions as not enforced, so editing them changes
no CRM access today.

Accounts: `python -m app.platform.authentication.cli bootstrap` creates the first ADMIN
and COMPLIANCE user; `... cli promote <email> <ROLE>` changes a role
([`development.md`](development.md)). Both validate the address as the sign-in form does
(`EmailStr`), so neither makes an account that could never sign in.

**Sessions.** Sign-in returns a short-lived access token, held in the tab's memory, and a
refresh token, kept in `localStorage` and so shared by every tab. `POST /auth/refresh`
**rotates** the refresh token on every use: the one presented is revoked and a successor
issued, so a second exchange of the same token is refused. The server reads the token's
row `FOR UPDATE`, so two exchanges at once serialise — one succeeds, one gets 401 —
rather than both succeeding. The browser has one refresh function (`refreshSession` in
`lib/api/client.ts`) for the page load, an expiring token and a 401: callers in one tab
share a refresh in flight (so StrictMode's double effect costs one call), and tabs take
turns through the Web Locks API, each reading the stored token only once it holds the
lock. Only the server refusing the token (401) ends a session — a network error, such
as the aborted fetch of a page being reloaded, leaves the token alone — and only if the
stored token is still the one refused; if another tab has stored a newer one, it retries
once with that. On the server, a refresh whose caller has already disconnected when it
is about to commit is rolled back (`499`), so a page reloaded mid-refresh keeps a token
that still works. The window this leaves is decision D-13 in
[`remaining-work.md`](remaining-work.md).

## 10. Ownership

Architecture §8–9 assigned each part to one developer; the contract for a part was
changed only with the agreement of its owner and its users, and a shared file only
through a review by its owner. The table is that pre-demo split, kept because the code
and the contracts cite owners. Since 4 October 2026 one developer completes the project
([`remaining-work.md`](remaining-work.md)).

| Owner | Owns |
|---|---|
| Developer 1 | Security and shared foundations: route role gates, the history log and its routes, the event envelope and publisher, the migration register, the generated API types, and the shared files (`exceptions.py`, the entity and repository indexes, `alembic.ini`, `importlinter.ini`, the route-authorisation tests, `frontend/src/lib/api`, auth, routes, sidebar) |
| Developer 2 | The company record: identity, identifiers, journey, marker, qualification, the move to `CUSTOMER`, CSV import, RXIL company intake, sample data, the company page shell and lists |
| Developer 3A | Contacts and activities, the conversation gauge, follow-ups |
| Developer 3B | Deals, buyers, storage, documents, the handover |
| Developer 4A | The background-check gauge, its decisions, evidence snapshot, risk and read helper |
| Developer 4B | Verification results and reviews, the screening checklist, buyer checks, the 4A ↔ 4B seam, the verification workspace |

Where one owner's code calls another's, it goes through a published seam: seam S1
(`ConversationService.mark_ready_now_for_opened_deal`), the background-check read helper
(`background_check_reader.py`), the 4A ↔ 4B inputs reader (`compliance_inputs.py`), and
Developer 2's promotion (`promote_to_customer_if_ready`).

## 11. Decisions

- **The twelve prototype decisions** (§6.1), cited as "decision 1" … "decision 12":
  start fresh with sample data; a company becomes a customer when its check is `CLEAR`;
  ended/paused is a marker; block a duplicate PAN, warn on a duplicate GSTIN; one
  COMPLIANCE/ADMIN user may reopen a cleared check with a reason; the risk scale is
  `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`; RXIL exporters arrive as qualified prospects; a
  rejected lead may be re-qualified; buyers live on deals and lending owns
  transactions (decision 9, being replaced by buyer company records, P4-4 – P4-10; its
  rewrite is R-25); other teams are told by events only; the compliance route exception;
  only COMPLIANCE and ADMIN see full tax IDs.
- **Planning assumptions** A1–A14 (§6.3) — for example A5, the handover guard.
- **Developer 4's decisions D1–D17** are recorded in `contracts/background-check.md`
  §14 and `contracts/verification-and-screening.md` §11. The PDF's §6.2 also lists an *earlier* plan's
  decisions under the same labels (for example its D8 is "storage: local disk first,
  relative keys only"); a code comment citing "D8" beside storage means that one.
- **Implemented on the audit's recommendation, awaiting the lead's written
  confirmation:** U4 (the move to `CUSTOMER` is one transaction), the rule that only a
  `PROSPECT` or `CUSTOMER` may open a deal, and the D2 clarification and D5 amendment made
  in the Developer 4A review (`remaining-work.md` D-08 – D-11). Developer 4B's side of D4
  and Developer 1's compliance details were confirmed on 2 October 2026
  (`contracts/background-check.md` §14.2). Every decision still open is in
  [`remaining-work.md`](remaining-work.md) §4.

## 12. Known, intentional limitations

The prototype is built to be honest about what is not real yet.

- **Not for real documents or data** (§7.6): the scanner is a pass-through and storage is
  local disk (no S3, Object Lock, KMS or retention lock); tax identifiers have no
  field-level encryption.
- **Providers:** Middesk, Trulioo and Sumsub stay disconnected (A13); results are
  recorded manually. RXIL results intake — and the automatic start of a check when they
  arrive — waits for RXIL's package contract (D12). No bank feed is connected.
- **Events** reach no receiver yet, and a publish lost between the commit and the
  announcement is not retried (no outbox).
- **Legacy and out-of-scope code:** the legacy onboarding workflow is not started
  (`TEMPORAL_ENABLED=true` is unsupported), the case engine is not connected to
  background-check decisions (A6), and several modules are schema only
  ([`../RUNNING.md`](../RUNNING.md)).
- **Accepted, or open for the lead:** a company can be cleared with no document — the
  screening answers and rule B's three passed checks (KYB, AML, sanctions) are enough
  (confirmed 2 October, to be revisited before real data); a placeholder verification row
  blocks `CLEAR` only within its own cycle, and a new cycle leaves it behind; the
  handover snapshot includes deal documents whatever their scan status; masked roles are
  told which company holds a full PAN or GSTIN they typed (BQ-2), and the shared-GSTIN
  warnings name the other holder (D-07); changing a `NOT_NOW` check-back date takes two
  moves; there are no cross-company deal or document lists; documents cannot be deleted
  (seven-year retention argues against it, and the database refuses it); there is no CI.
  [`remaining-work.md`](remaining-work.md) tracks each.

## 13. Further reading

- The contracts: [`contracts/`](contracts/) — company record, criterion results,
  engagement, deal and buyer, trade history, storage and documents, background check,
  verification and screening, history row,
  event envelope, migration register.
- What is done, what is left and what needs a decision, in one list:
  [`remaining-work.md`](remaining-work.md).
- Running, testing and migrating: [`development.md`](development.md). The demo walk-through:
  [`demo.md`](demo.md).
