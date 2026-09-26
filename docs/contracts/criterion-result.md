# Contract — qualification criteria, criterion results and outcomes

**Owner:** Developer 2 · **Implemented by:** L2-09 (criteria), L2-10 (results and outcomes), migration 0017 · **Status:** agreed shape, **not built** — nothing of it exists today

Qualification answers one question: *did this company meet our requirements?*
(architecture §3.3, gauge 1). This contract fixes the shape of the three
things that answer it — the **criterion** (a requirement, held as a setting),
the **result** (one criterion checked against one company), and the
**outcome** (a person's overall decision) — and the rules that tie them to the
company's `qualification` gauge.

It fixes **vocabulary and rules**, not storage. Table layout, column types and
indexes are migration 0017's to decide, as long as they honour what is written
here.

Readers: Developer 4 (the RXIL parser hands over the qualification part of a
package), later automation, and anyone rendering qualification on screen.
Changing this contract needs the agreement of Developer 2 and those readers.

---

## 1. Not the screening checklist

The existing eight-item **screening checklist** (`screening_review_item`,
`ScreeningReviewService`, statuses `NEEDS_REVIEW`/`PASSED`/`FAILED`/`EXEMPT`)
is a compliance list inside the **background check**. It belongs to Developer 4
(architecture §5.5).

Qualification does not reuse it: not its table, not its item keys, not its
statuses, not its service, not its routes. The value sets are deliberately
different (`PASS`/`FAIL`/`UNKNOWN` below) so that a value can never be read as
belonging to the other list. Anything called "checklist" is compliance;
the sales gauge is always called **qualification**.

---

## 2. The criterion — a setting, not code

Criteria are data that ADMIN users manage without a code change or a deploy.
Thresholds live here, never in code: the CEO's "revenue of at least $100M" and
"at least five years in business" are **seed values**, not constants.

| Field | Meaning | Rule |
|---|---|---|
| `key` | Stable identifier, lower snake case (`revenue`) | Unique. **Never changes** once created; it is what results point at |
| `version` | Integer, starting at 1 | Increases by one on **every** change, `label` and `active` included. A result names the version it was judged against |
| `label` | What a person reads (`Annual revenue`) | Changed by adding a version, like every other field (as built: a version row is never edited, so even a relabel keeps the old label readable) |
| `kind` | `NUMBER_THRESHOLD`, `YES_NO`, `ALLOWED_VALUES` | Fixed for the life of the key; a different kind is a different criterion |
| `threshold` | For `NUMBER_THRESHOLD`: a comparison (`AT_LEAST` or `AT_MOST`), a number, and a unit (`USD`, `YEARS`, ...) | Required for that kind, absent otherwise |
| `allowed_values` | For `ALLOWED_VALUES`: the list of acceptable values | Required and non-empty for that kind, absent otherwise |
| `required` | Whether it must pass for the screen to suggest `QUALIFIED` | |
| `active` | Whether new results may be recorded against it | Inactive criteria are never deleted; their results stay visible |

**Old versions are kept.** Changing a criterion creates a new version; the
previous one remains readable, so a result recorded against version 2 still
shows the version-2 threshold it was judged against.

**Initial set** (seeded, then managed by ADMIN): `revenue`,
`years_in_business`, `export_history`, `export_licence`, `industry`,
`geography` (trade corridor), `deal_size`. Their kinds and thresholds are seed
data chosen at L2-09, not part of this contract.

**Who:** ADMIN creates, edits, activates and deactivates criteria. Everyone who
can read a company can read the criteria.

---

## 3. The criterion result

One criterion, checked against one company, once. Results are
**append-only**: never edited, never deleted. Checking again adds a new result.

| Field | Meaning | Required |
|---|---|---|
| `id` | The result's own id | server-set |
| `company_id` | The company (`company-record.md` §1) | yes |
| `criterion_key`, `criterion_version` | Which criterion, at which version | yes. **The server pins the criterion's current version**, which must be `active`; the caller names only the key |
| `result` | `PASS`, `FAIL` or `UNKNOWN` | yes. `UNKNOWN` means "could not establish", not "not yet looked at" |
| `observed_value` | What was found (`87000000 USD`, `true`, `"textiles"`) | no. Recorded as given; the service does not re-derive `result` from it |
| `source` | Where the result came from: `MANUAL`, `IMPORT`, `RXIL`, `AUTOMATED` | yes |
| `decided_by_kind` | Whether a **person** or a **computer** decided: `MANUAL` or `AUTOMATED` | yes. Separate from `source`: an imported row checked by a person is `source = IMPORT`, `decided_by_kind = MANUAL` |
| `evidence` | What it rests on: a note, and optionally references (document ids, verification-result ids, URLs) | a note **or** at least one reference is required when `result = PASS` or `FAIL` |
| `reason` | Why, in the decider's words | no |
| `confidence` | 0 to 1, for an automated result | only meaningful when `decided_by_kind = AUTOMATED`; absent otherwise |
| `recorded_by` | Who recorded it | from the login session, never the request body. `NULL` only for the platform itself (RXIL intake, automation) |
| `recorded_at` | When | server time, never supplied |

**The current result** for a criterion on a company is the most recent one
recorded against it. Earlier ones stay visible, with their version.

**Evidence references are ids, not copies.** A document id points at
Developer 3's document record; a verification-result id at Developer 4's. This
contract does not define those records and does not store their contents.

**Who:** OPERATIONS, COMPLIANCE and ADMIN record results. Everyone who can read
a company can read its results.

---

## 4. The qualification gauge

The company record's `qualification` field (`company-record.md` §2.4) takes
three values:

| Value | Meaning | Next allowed |
|---|---|---|
| `NOT_YET_REVIEWED` | Default for every new company | `QUALIFIED`, `NOT_QUALIFIED` |
| `QUALIFIED` | Meets requirements; the company becomes a `PROSPECT` | none in the prototype (assumption A2) |
| `NOT_QUALIFIED` | Does not meet requirements; stays a `LEAD` | `QUALIFIED` or `NOT_QUALIFIED` again, by re-review (decision 8) |

The gauge moves **only** by recording an outcome (§5). Recording results never
moves it.

`NOT_QUALIFIED` → `NOT_QUALIFIED` is a real move: a re-review that reaches the
same answer with new results and new reasons is recorded, not collapsed.

---

## 5. The outcome — a person's decision

After results are recorded, a reviewer records the overall outcome. **The
screen suggests; the person decides.**

| Field | Meaning | Required |
|---|---|---|
| `id` | The outcome's own id | server-set |
| `company_id` | The company | yes |
| `outcome` | `QUALIFIED` or `NOT_QUALIFIED` | yes |
| `reason_codes` | Machine-readable reasons (`revenue_below_threshold`) | **at least one** for `NOT_QUALIFIED`; optional for `QUALIFIED` |
| `note` | Free text | optional; required when a reason code is `other` |
| `suggested_outcome` | What the server suggested at the moment of decision (§5.1) | server-set, stored with the outcome |
| `result_ids` | The results the decision rested on | server-set: the current result for every active criterion at decision time. Later results do not change it |
| `source` | `MANUAL` or `RXIL` (later `AUTOMATED`) | yes |
| `decided_by_kind` | `MANUAL` or `AUTOMATED` | yes |
| `supersedes` | The outcome this one replaces, on a re-review | set by the server to the company's previous outcome, if any |
| `decided_by` | Who | from the login session; `NULL` only for RXIL intake |
| `decided_at` | When | server time |

Outcomes are **append-only**, like results. A re-review is a new outcome that
points at the one it replaces; the old one is never edited (architecture §2.6).

### 5.1 The suggestion

The server suggests `QUALIFIED` when every **active, required** criterion has a
current result of `PASS` recorded against its **current** version; otherwise it
suggests `NOT_QUALIFIED`. A result against an older version counts as not yet
checked for the suggestion and is shown as such.

The person may record either outcome regardless of the suggestion. Recording
the opposite of the suggestion is allowed and is visible afterwards, because
the suggestion is stored with the outcome.

### 5.2 Reason codes

Reason codes are a server-checked list held as settings alongside the
criteria, so a new code needs no code change. The seed list has one code per
initial criterion (`revenue_below_threshold`, `years_in_business_below_threshold`,
`no_export_history`, `no_export_licence`, `industry_not_supported`,
`geography_not_supported`, `deal_size_out_of_range`) plus
`insufficient_information` and `other`. An unknown code is refused.

**Who:** OPERATIONS, COMPLIANCE and ADMIN record outcomes and re-reviews.

---

## 6. What recording an outcome does

In **one transaction**, all written by Developer 2's service (so decision U4
does not apply — nothing crosses a service boundary):

1. Write the outcome.
2. Set the company's `qualification` field to the outcome.
3. Write a `qualification` history row: `from` the previous value, `to` the
   outcome, `reason` = the note, `event_metadata` carrying `outcome_id`,
   `reason_codes` and `source`.
4. If the outcome is `QUALIFIED` and the company is a `LEAD`: move the journey
   to `PROSPECT` and write its `journey` row (`company-record.md` §3.1).
5. If step 4 happened and the company's `background_check` is already `CLEAR`:
   move the journey on to `CUSTOMER` and write that row too.

After the commit, and only if step 5 happened, announce
`company.became_customer` (event contract §3–4: after the history row, best
effort, never rolling anything back).

An outcome that is not allowed by §4 — `QUALIFIED` again, or anything on an
already-`QUALIFIED` company — is refused before step 1 and leaves nothing
behind.

### 6.1 Results in the history log

Architecture L2-10 requires the history to show every result. Each recorded
result also writes a `qualification` history row with
`event_type = "qualification_result"`, `to` = `PASS`/`FAIL`/`UNKNOWN`,
`from` = `NULL`, and `event_metadata` carrying `result_id`, `criterion_key`,
`criterion_version` and `source`. A reader of the `qualification` dimension
separates gauge moves from results by `event_type`.

This is the one addition this contract makes to how the history log is used:
a third `event_type` on a dimension, which the history contract permits (§3)
but does not list. It needs Developer 1's acknowledgement, recorded against
L1-02, before L2-10 writes the first row.

---

## 7. RXIL and bulk import

- **RXIL intake** (L2-12, decision 7): the company arrives as `PROSPECT` with
  an outcome of `QUALIFIED`, `source = RXIL`, `decided_by = NULL`, and
  `decided_by_kind` as the package states it (open item Q4 — the format does
  not yet say whether RXIL's filtering is a person's or a computer's). No per-criterion
  results are required, and none are recomputed: we store what RXIL says and
  never recompute its work. RXIL's background-check results are
  Developer 4's (L4-10), not criterion results.
- **Bulk import** (L2-13): a row may carry values for criteria; each becomes a
  result with `source = IMPORT`. Import never records an outcome. *As built,
  the template carries no criterion columns yet — rows are identity only.*
- **As built for RXIL** (L2-12): `QualificationService.record_partner_decision`
  records the partner's results and outcome in one transaction, in the same
  tables and history as a local review. Nothing is recomputed: each result
  keeps RXIL's result, value, evidence, reason, confidence and per-result
  method (`decided_by_kind`), with `source = RXIL`; the outcome's
  `suggested_outcome` is RXIL's own decision and its `result_ids` are RXIL's
  results only. `decided_by` is `NULL` (RXIL decided); `recorded_by` on the
  results and the actor on the history rows is the signed-in user who
  submitted the package. A `PASS`/`FAIL` that RXIL sent without any evidence
  gets the note "As supplied by RXIL …; RXIL gave no further evidence", because
  an unevidenced `PASS`/`FAIL` is refused. RXIL's evidence ids may use the
  reference type `partner_reference`, which only partner intake can write. The
  package's `package_id`, when present, is kept on the outcome's history row as
  `partner_reference`, and a repeated `package_id` changes nothing.
- **Automation** (later): results with `source = AUTOMATED`,
  `decided_by_kind = AUTOMATED` and a `confidence`. The outcome stays a
  person's decision in the prototype.

---

## 8. Invariants

Any of these being false is a bug:

1. The company's `qualification` field equals the latest outcome's
   `outcome`, or `NOT_YET_REVIEWED` if there is none.
2. Every `NOT_QUALIFIED` outcome has at least one reason code.
3. No outcome follows a `QUALIFIED` outcome on the same company.
4. Every result names a criterion version that exists.
5. No result or outcome is ever updated or deleted — enforced by the database
   (`prevent_mutation()`), not only by the service, as for every locked table.
6. `recorded_by` / `decided_by` are never taken from a request body.

---

## 9. Open items

| # | Question | Decides |
|---|---|---|
| Q1 | Do `NUMBER_THRESHOLD` criteria need a range (both a minimum and a maximum) — `deal_size` may? Recommendation: add `BETWEEN` only if a seeded criterion needs it | Dev 2 at L2-09 |
| Q2 | Is `NOT_YET_REVIEWED` written as a `qualification_initial` history row at company creation? Recommendation: **yes**, so every dimension's timeline starts at creation, the way the journey's does | Dev 2 with Dev 1 |
| Q3 | Developer 1's acknowledgement of `event_type = "qualification_result"` (§6.1) | Dev 1 |
| Q4 | RXIL package shape (architecture §11) — how its qualification part is expressed | RXIL; parser shared with Dev 4 |
| Q5 | Do reason codes need an ADMIN route, or do they stay seeded settings changed by migration? | Programme lead |

---

## 9a. As built (L2-09, L2-10)

**Storage** (migration 0017): `qualification_criterion` (one immutable row per
version), `qualification_reason_code`, `qualification_result` and
`qualification_outcome`, plus `exporter_profile.qualification` and
`exporter_profile.journey`. The criterion, result and outcome tables are
append-only through `public.prevent_mutation()`. The database also enforces:
the kind-dependent shape of a criterion; evidence on every `PASS`/`FAIL`
result; a confidence only on an automated result, between 0 and 1; at least one
reason code on a `NOT_QUALIFIED` outcome; one outcome chain per company (a
single first outcome, and no outcome superseded twice).

A result's evidence is `evidence_note` plus `evidence_refs`, a list of
`{type, ref}` with `type` one of `document`, `verification_result`, `url`.

**Routes** (all under `/api/v1/onboarding`):

| Route | Who |
|---|---|
| `GET /qualification/criteria`, `GET /qualification/criteria/{key}/versions`, `GET /qualification/reason-codes` | every CRM reader |
| `POST /qualification/criteria`, `POST /qualification/criteria/{key}/versions` | ADMIN only |
| `GET /exporters/{id}/qualification` — gauge, journey, current suggestion, each criterion's standing, every result and outcome | every CRM reader |
| `POST /exporters/{id}/qualification/results`, `POST /exporters/{id}/qualification/outcome` | OPERATIONS, COMPLIANCE, ADMIN |

**What a request cannot say.** Who recorded or decided (always the signed-in
user), and `source`, `decided_by_kind` or `confidence`: a result or outcome
entered through the API is `MANUAL`, by a person. The other sources are for
the platform's own callers of `QualificationService` (import, RXIL,
automation), never a claim a request body can make.

**Once `QUALIFIED`** — final in the prototype (A2) — the service refuses
further results as well as further outcomes (409).

**History event types.** Results: `qualification_result`. Outcomes: the
derived `qualification_transition`, with `outcome_id`, `reason_codes`,
`suggested_outcome` and `re_review` in the details and the note as the reason.
The journey move a `QUALIFIED` outcome causes: dimension `journey`, event type
`lifecycle_transition` with `terminal: false` — the journey's own event names
(`company-record.md` §6). It was `journey_transition` until L2-04 retired the
ten-status rows that owned the `lifecycle_*` names.

**What a viewer may do is served.** The qualification response carries
`allowed_outcomes` (the outcomes this viewer may record now: both for
OPERATIONS, COMPLIANCE and ADMIN until the company is `QUALIFIED`, none after
or for other roles) and `can_record_results`.

**Reason codes** are seeded by 0017 and checked by the server; there is no
route to manage them yet (open item Q5).

## 10. What is implemented today

| Item | State |
|---|---|
| Criteria (versioned, ADMIN-managed, seven seeded), results, outcomes, re-review, suggestion | **implemented** (L2-09, L2-10, migration 0017) |
| The `qualification` gauge on the company, and the `LEAD` -> `PROSPECT` move it drives | **implemented** (0017) |
| `qualification` history rows (results and outcomes) | **implemented** |
| A `qualification_initial` row at company creation (Q2) | **not built** — the column default stands for it |
| Managing reason codes through the API | **not built** — Q5 |
| RXIL and import callers | **implemented** — L2-12, L2-13 |
| Qualification display and review screens | **implemented** — L2-14 |
| Anything reused from the screening checklist | **none, by design** (§1) |
