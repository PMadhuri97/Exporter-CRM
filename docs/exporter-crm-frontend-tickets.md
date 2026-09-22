# Exporter CRM Frontend — Design Principles & Build Tickets (Phase 1)

## Context

`frontend/` exists only as an empty module-facade skeleton (`frontend/src/modules/onboarding/{api,components,hooks,model,pages,services,types}/index.ts`,
each `export {}` or `// TODO: implement.`, plus a `routes.tsx` returning `null`) — **no
`package.json`, no build tool, no styling system, no component library is chosen yet.** This is
a from-zero bootstrap, not a "fill in the blanks" situation. The one real signal already present:
whoever scaffolded this intended the same module-facade discipline the backend enforces with
import-linter (`api/index.ts` as the only import surface for a module) to carry over to the
frontend — new tickets should preserve that shape, not flatten it.

A wireframe set ("Exporter CRM (Financer View)") was reviewed against the actual backend surface
(EXP-1 `exporter_router.py`, EXP-2 `verification.py`, `ExporterLifecycleStatus`'s permitted-
transition graph) on 2026-09-21. Several screens assume backend capability that doesn't exist yet
(SSO, Buyers, Credit/ITFS decisioning) or a state taxonomy that doesn't match
`ExporterLifecycleStatus`. Decisions below resolve those gaps for Phase 1; see
`fintech-epic4-verification-trust-ledger-model` memory for the verification/trust-ledger
architecture this UI has to represent correctly.

## Resolved product decisions (2026-09-21)

1. **Stage taxonomy:** the backend's 10-state `ExporterLifecycleStatus` (`LEAD, CONTACTED,
   DATA_COLLECTION, VERIFICATION_IN_PROGRESS, COMPLIANCE_REVIEW, ONBOARDED, FINANCING_ELIGIBLE,
   ACTIVE, SUSPENDED, OFFBOARDED`) is **not** simplified. The Pipeline kanban groups it into fewer
   visual columns, each showing a secondary status chip for the underlying state — the backend
   states carry real workflow meaning (which check is outstanding) that a flattened label would
   lose. Suggested grouping (confirm during EXP-F2): `New` = LEAD, `Contacted` = CONTACTED,
   `Onboarding` = DATA_COLLECTION + VERIFICATION_IN_PROGRESS + COMPLIANCE_REVIEW, `Approved` =
   ONBOARDED + FINANCING_ELIGIBLE, `Active` = ACTIVE, plus a separate filter (not a kanban column)
   for SUSPENDED/OFFBOARDED since those are exits, not pipeline stages.
2. **Credit & ITFS Status / Buyers:** out of Phase 1 entirely. No backend exists for
   `Buyer`/credit-decisioning (deferred to a future `underwriting` module per
   `fintech-epic4-verification-trust-ledger-model`). Cut the "Contacts & Buyers" wizard step and
   the "Credit & ITFS" tab from Phase 1 tickets — don't even stub them; re-add once that module has
   a real API.
3. **Auth:** password + refresh-token login for Phase 1, matching `app/platform/authentication`
   as it actually exists today (`User.hashed_password`, `RefreshToken`). Google/Microsoft SSO is
   explicitly out of scope here — no OAuth integration exists on the backend; treat it as a
   separate, later ticket if/when needed.
4. **PAN/GSTIN masking:** the earlier role-masking decision holds **everywhere**, including the
   Exporters List table — `OPERATIONS` (Relationship Manager) sees masked identifiers (e.g. last-4)
   in every view; `COMPLIANCE`/`ADMIN` see them unmasked. No screen gets an exception.

## Known backend gaps this surfaces (not frontend tickets — track separately)

- No field for `country` or `sector` on `ExporterProfile` today (only `industry`). Wireframe's Add
  Exporter form assumes both exist.
- No "consent to be contacted" field/schema anywhere.
- `ExporterSource` enum (`MANUAL, SALES, REFERRAL, RXIL, PARTNER, API, BROKER, EVENT,
  EXISTING_CUSTOMER`) has no member matching a specific list name like "EEPC List" — likely needs
  a two-level field (source type + free-text list name) rather than a new enum member per list.
- No deal-value/volume field backing the "$X/mo" figures shown on pipeline cards.
- `relationship_manager` is a bare string by deliberate design (see EXP-1 ticket) — an
  avatar/people-picker UI implies resolving against real `User` rows. Decide whether to keep it a
  free string with an autocomplete-from-`Users` suggestion, or change the column to a real FK —
  don't silently assume the latter in frontend code.
- No aggregate/stats endpoint for KPI tiles or a "Pipeline by Stage" chart — moot for now: the
  agreed build sequence (below) has no Dashboard/KPI ticket in it at all. Revisit if one gets added
  later.
- Activity Timeline mixing human-logged `ExporterActivity` rows with system events ("Stage changed
  to Interested", "Document uploaded") needs a merged read across `ExporterActivity` and
  onboarding's audit/state-transition history — no such merged endpoint exists yet.

---

## Design principles for this build

**The real tension to resolve, explicitly:** "modern and sleek" (generous whitespace, soft
shadows, minimal chrome — the wireframe's aesthetic) versus what this tool actually is — a
compliance-adjacent ops CRM where people scan dense tables of PAN numbers, verification statuses,
and SLA deadlines all day. Resolve it as **quiet chrome, expressive data** — not by cutting
either dimension:

- Navigation, headers, cards: restrained — one brand color, generous spacing, soft borders instead
  of heavy shadows/gradients. This is where "sleek" lives.
- Tables, status chips, timelines: dense, high information-per-pixel, strong typographic hierarchy
  (tabular numerals for identifiers/amounts, consistent column alignment). This is where the actual
  work happens — don't sacrifice scanability for whitespace here.

**A consistent semantic status language, defined once, reused everywhere** (kanban columns, list
chips, detail-page badge, timeline icons) — not re-invented per screen:
- Lifecycle: neutral gray (LEAD/CONTACTED) → blue (onboarding/verification states) → green
  (ONBOARDED/FINANCING_ELIGIBLE/ACTIVE) → amber (SUSPENDED) → red/gray (OFFBOARDED).
- Verification: `PASSED` = green, `FAILED` = red, `REVIEW` = amber, `PENDING` = neutral.
- Risk level: `LOW` = green, `MEDIUM` = amber, `HIGH` = red — never reuse these hues for anything
  else on the same screen, so risk is instantly scannable.

**"Show your work" for every verification-derived fact.** Given the trust-ledger model (RXIL +
ANER re-checks both land in `VerificationResult`, most-recent wins), **never show a bare status**
— always pair it with `provider` and `performed_at` ("KYB: Passed — Middesk, 2 hours ago"), and make
older results for the same check type reachable via an expandable "History (N)" affordance, not
hidden. A user should never have to wonder whether they're looking at RXIL's original result or
ANER's own re-check.

**Masked-by-default, reveal-with-a-reason — an eye icon, not an always-visible toggle.** Every
masked PAN/GSTIN/identifier field renders with a small eye icon beside it. The icon itself is only
present for roles permitted to ever reveal that field — a role that can't reveal doesn't get a
disabled eye icon (which would leak "this data exists, you're just not allowed"), it gets no icon
at all, same as if the field were a plain string. Clicking it swaps the masked value for the real
one client-side; this sets up the backend eventually logging each reveal as an audit event
(matching this codebase's existing "audit event on every write" discipline extended to sensitive
reads), even though that logging isn't built yet — flag it as a near-term backend follow-up once
this ships, not a someday item.

**Role capability matrix (resolved 2026-09-21):**

| Role | Sees masked value by default | Can reveal (eye icon present) |
|---|---|---|
| `COMPLIANCE` | No — unmasked always | N/A |
| `ADMIN` | No — unmasked always | N/A |
| `OPERATIONS` | Yes | **Only on exporters where this user is the assigned `relationship_manager`** — no icon at all on any other exporter's record |
| `DEVELOPER` (new role, distinct from `API_USER`) | Yes | No, never — no eye icon rendered at all, no exception |

`API_USER` stays reserved for external/system API callers (relevant once Epic 4.4's paused
customer API resumes) — kept separate from `DEVELOPER` (internal technical staff) so the two don't
get conflated under one name later.

**This makes `OPERATIONS`'s reveal permission ownership-scoped, not just role-scoped** —
`can_reveal = role in {COMPLIANCE, ADMIN} OR (role == OPERATIONS AND current_user "is" this
exporter's relationship_manager)`. That last check is a real backend blocker, not just a frontend
detail: `ExporterProfile.relationship_manager` is currently a bare display string by deliberate
EXP-1 design ("an actor identifier... plain string, not a FK to a user table"), which is fine for
*display* but not sufficient to reliably answer "is the logged-in user this exporter's RM?" —
string-matching a display name against `current_user.full_name`/email is fragile (renames,
duplicates, casing). Before EXP-F0's `maskIdentifier`/reveal logic can be implemented correctly,
the backend needs one of:
- `relationship_manager` stores a stable identifier (e.g. `User.id` or `User.email`) rather than a
  free display string, with display name resolved at read time, or
- a separate, real FK column added alongside the existing string (keeps the string for historical/
  display purposes, adds an `relationship_manager_user_id` for the ownership check).

Flag this to whoever owns the backend `onboarding` module before EXP-F0 locks in the masking
utility's API shape — the frontend can't build ownership-scoped reveal against a field that can't
reliably answer "is this me?" today.

**Design every async state on purpose, not as an afterthought** — this is an ops tool talking to
real vendor APIs (verification triggers can be slow/pending) and a strict state machine (kanban
drops can be legitimately rejected). Skeleton loaders over spinners; empty states that name the
next action ("No exporters yet — Add Exporter"); an illegal kanban drop should be visually
prevented (greyed-out column) before the user tries it, not a toast after a 409.

**Accessibility is not optional for a compliance tool.** WCAG AA minimum. The kanban needs a
non-drag path to change stage (a "Move to…" menu on the card) — both for keyboard/screen-reader
users and because it's the natural place to show *why* a column is disabled (illegal transition)
with real text, not just a greyed-out drop target.

---

## Build sequence (confirmed 2026-09-21)

Ten tickets, in this order, each a working vertical slice before the next starts. No Dashboard/KPI
ticket exists in this sequence — dropped, not deferred silently (see the backend-gaps note above).
Documents (the wireframe's Documents tab) also isn't in this list — treated as **out of this
sequence** until explicitly requested; flag before folding it into EXP-F4 as an extra tab.

1. **EXP-F1 — Auth Shell** — ✅ built 2026-09-21
2. **EXP-F2 — Exporters List** — ✅ built 2026-09-21
3. **EXP-F3 — Add Exporter** — ✅ built 2026-09-21
2. **EXP-F2 — Exporters List**
3. **EXP-F3 — Add Exporter**
4. **EXP-F4 — Exporter Detail**
5. **EXP-F5 — Contacts + Activity**
6. **EXP-F6 — Lifecycle "Move to…" Action**
7. **EXP-F7 — Follow-ups**
8. **EXP-F8 — Verification Results (read-only)**
9. **EXP-F9 — Verification Actions (trigger + review)**
10. **EXP-F10 — Pipeline (kanban)**

---

## EXP-F1 — Auth Shell — **Built 2026-09-21**

Vite + React + TS + Tailwind + Radix + TanStack Query + RHF/Zod + generated OpenAPI client +
password auth + module-boundary lint, all real and passing (`npm run build`, `npm run lint`,
`npm run test`, `npm run dev` all verified). Not verified against a live backend (no Postgres
running in this environment) — the silent-refresh-on-boot and login flows are implemented per
the backend's actual `/api/v1/auth/*` contract (read directly from `schemas.py`/`router.py`) but
haven't been exercised against a real running server yet.

**Two things discovered while building this that the plan below didn't anticipate:**

1. **The OpenAPI schema doesn't need a live server.** `app.openapi()` can be dumped straight from
   a Python one-liner (`from app.main import app; app.openapi()`) without a database connection —
   `npm run generate:api:schema` does exactly this. `openapi.json` and the generated
   `src/lib/api/schema.ts` are both gitignored (regenerated, not hand-edited) — a fresh clone must
   run `npm run generate:api` once before typecheck/build will pass.
2. **`eslint-plugin-boundaries` silently does nothing without a resolver it can use for path
   aliases.** The `import/resolver` setting (pointed at `eslint-import-resolver-typescript`) is
   required for the plugin to resolve this project's `@/...` aliased imports (and even
   extension-less relative imports) as "local" elements at all — without it, `boundaries/entry-point`
   evaluates against an unresolved dependency and never reports anything, which looks identical to
   "the rule is satisfied." **Confirmed by testing a deliberate violation before and after adding
   the resolver** — it was not caught until the resolver was configured. If this rule is ever
   touched again, re-run that check (temporarily import a non-index file of a module from outside
   it, confirm eslint reports it, then revert) rather than trusting a clean `eslint` run alone —
   a misconfigured version of this rule reports zero errors on a correct codebase AND on a broken
   one.

A `DEVELOPER` role was also added to the backend (`UserRole` enum +
`auth_0002_developer_role` migration) as part of this ticket, not a later one — the frontend's
role capability matrix above needed it to exist to type `useCurrentUser().role` correctly.

---

## EXP-F1 — Auth Shell

**Goal:** everything needed before any screen ticket is buildable, landing as a real authenticated
shell — not just tooling in the abstract. Nothing here is a "modern and sleek" style choice made in
isolation — each pick is justified against what the backend already is.

- **React + TypeScript + Vite.** `.tsx` files already exist; Vite over CRA/webpack for build speed
  and because nothing here needs SSR (internal ops tool, no SEO concern).
- **Tailwind CSS + unstyled primitives (Radix), not a prebuilt component kit.** Gives full control
  over the "quiet chrome, expressive data" look above without fighting a kit's opinions; Radix
  handles accessibility primitives (focus trapping, keyboard nav) that a from-scratch build would
  get wrong.
- **TanStack Query for all server state.** Every screen here is CRUD/list/detail against a REST
  API with real latency (verification triggers, provider polling) — Query's cache/loading/error
  states map directly onto "design every async state on purpose" above, instead of hand-rolled
  `useEffect` fetch logic per component.
- **React Hook Form + Zod**, with Zod schemas generated to mirror the backend's Pydantic
  `extra="forbid"` request models where practical — the backend already rejects unknown fields
  with a 422; matching that client-side avoids a whole class of "worked in dev, 422'd in prod"
  bugs.
- **Generate the API client from the backend's own OpenAPI schema** (`GET /api/v1/openapi.json`,
  confirmed working per `RUNNING.md`) via `openapi-typescript`, rather than hand-writing response
  types — this build already found half a dozen frontend/backend field mismatches by manual
  inspection (see "Known backend gaps" above); a generated client makes the next mismatch a build
  error, not a silent bug.
- **Auth:** password login against the real `User`/`RefreshToken` model (decision #3 above);
  `useCurrentUser()` hook exposing `role: UserRole`.
- **A masking utility used everywhere PII is rendered** (`maskIdentifier(value, { role, isOwner })`
  — `isOwner` answers "is the current user this record's assigned relationship_manager," see the
  ownership-scoped reveal rule below), not reimplemented per component — the single place decision
  #4 is enforced. Blocked on a backend decision about how `relationship_manager` identifies a user
  reliably — see the role capability matrix below.
- **Module-boundary lint rule** (e.g. `eslint-plugin-boundaries`) enforcing that each
  `modules/<name>/` only gets imported via its own `index.ts` from outside — the frontend
  equivalent of the backend's import-linter contracts, matching the scaffold's own intent.
- **Design tokens file** (color roles, spacing scale, type scale) implementing the semantic status
  language above, defined once and consumed everywhere — not per-component magic values.

### Acceptance criteria
- `npm run dev` boots an authenticated shell (sidebar nav, empty content area) against a running
  backend.
- A deliberately-wrong API call (e.g. omit a required field) surfaces the backend's 422 detail in
  the UI, proving the generated client's types and the form validation are both wired end to end.
- `maskIdentifier` has a unit test proving an `OPERATIONS`-role render masks and a
  `COMPLIANCE`-role render doesn't, for the same input.

---

## EXP-F2 — Exporters List — **Built 2026-09-21**

Shipped as designed below, but it needed three backend additions the original ticket didn't
anticipate — the search endpoint's response literally could not render this screen without them:

1. **`legal_name` didn't exist anywhere in the search response.** `ExporterProfileResponse` never
   carried it (deliberately — see `exporter_profile.py`'s docstring), and `search_profiles` only
   used `OnboardingRequest.legal_name` as a *filter*, never returned it. Fixed by adding
   `ExporterProfileRepository.search`'s "most recent `OnboardingRequest` per `customer_id`"
   window-function join — the exact same pattern `ExporterActivityRepository.list_pending` already
   uses for `PendingActivityView.exporter_display_name` — plus a new `ExporterProfileListItem`
   view / `ExporterProfileListItemResponse` schema so this doesn't touch the shape
   create/update/detail already return.
2. **The ownership-scoped reveal check had nothing real to compare against.** Per
   `fintech-epic4-frontend-role-masking-model` memory, this was a known, flagged blocker — resolved
   now, not deferred further: `onboarding_0009_relationship_manager_user` adds
   `exporter_profile.relationship_manager_user_id` (a bare, nullable `UUID`, **no FK to
   `auth.users`** — matches this codebase's established `assigned_to`/`actor_id` convention, see
   the migration's own docstring). Nothing sets it yet (no ticket has built an "assign RM" action);
   application-layer active-user validation is deferred to whichever ticket first writes to it.
3. **Multiple `lifecycle_status` values can't be filtered server-side in one call** — the backend's
   `status` query param is a single exact match, not "any of these." Rather than widen that
   endpoint for a display-only grouping, EXP-F2's stage tabs filter **client-side** over an
   unfiltered-by-status fetch — a documented simplification (see `api/index.ts`'s
   `searchExporterProfiles` docstring), not a hidden one. Revisit if page sizes stop making a full
   fetch reasonable.

Built inside `src/modules/onboarding/` for real (previously an empty scaffold) — `types.ts`,
`constants.ts` (the stage-grouping table from decision #1, plus static Tailwind chip classes —
interpolating a color name into a class string doesn't work with Tailwind's JIT, learned while
building `StageChip`), `api/`, `hooks/`, `components/`, `pages/`, `routes.tsx`, and the module's
`index.ts` facade. `AppRouter` now mounts `/exporters/*` through it.

Verified: `tsc -b`, `eslint .`, `vitest run` (12 tests, including 3 new render tests proving the
masking acceptance criterion in context — `OPERATIONS`-non-owner masks, `OPERATIONS`-owner and
`COMPLIANCE` don't), and `npm run build` all pass. Still not exercised against a live backend/DB.

---

## EXP-F2 — Exporters List

**Goal:** find an exporter. The first real screen, and the one every other ticket links back to.

- `GET /onboarding/exporters` search: table with Company Name, masked PAN/GSTIN (role-aware, per
  the capability matrix above — this is the screen that most needs it right, it's the widest
  exposure surface), grouped Stage chip (decision #1), Owner. No Next-Follow-up column yet — that
  needs EXP-F7's data, wire it in then rather than stubbing it now.
- Filter tabs by grouped stage; free-text search wired to `legal_name`/`gstin`/`pan`/`iec` query
  params; `source`/`status` filters.

### Acceptance criteria
- Same exporter, `OPERATIONS` vs `COMPLIANCE` login, renders different PAN/GSTIN visibility —
  screenshot-tested, not just unit-tested, since this is a real product risk if it regresses
  silently.
- Search returns results for each of `gstin`/`pan`/`iec`/`legal_name`/`source`/`status` filters
  independently.
- Empty search result state names the next action, per the design principles above (not a bare
  empty table).

---

## EXP-F3 — Add Exporter — **Built 2026-09-21**

Bigger backend gap than expected: `POST /onboarding/exporters` only ever called
`create_or_get_profile`, which **cannot set a `legal_name`** at all (no `OnboardingRequest` gets
created) — the only method that actually can is `ExporterProfileService.create_lead`
("the actual fix for 'Add Exporter has nowhere to put a name'", per its own docstring), and
nothing routed to it. Fixed by extending `CreateExporterProfileRequest` with optional
`legal_name`/`incorporation_country`/`initial_user_email` (all-or-nothing, enforced by a
`model_validator`) — supplying all three now routes the same endpoint through `create_lead`
instead, keeping one endpoint rather than adding a parallel one.

That surfaced a second gap: `create_lead` requires `tenant_id`, a field with **no default
anywhere in this codebase** — every test just uses `uuid.uuid4()`. Confirmed with the user: ANER
is a single financier here, not a multi-tenant SaaS, so this is now one fixed platform constant
(`Settings.ANER_TENANT_ID`, `app/platform/configuration/config.py`) — never a form field, never
caller-supplied. Don't reopen this as a UI decision; it's resolved.

`initial_user_email` is **not** the exporter's future login — it's a reachable contact for the
Lead (Sales rep's own address, a lead-intake mailbox, whatever channel sourced it), per
`OnboardingRequestService.initiate_onboarding`'s own documented reasoning, which `create_lead`
reuses. Labeled "Contact Email" in the form, not "Login Email", for exactly this reason.

Creating a Lead this way requires the `Idempotency-Key` header (unlike the `create_or_get_profile`
path, where it's optional) — a fresh `OnboardingRequest` row has no other natural uniqueness to
dedupe a retried submit against. The frontend generates one (`crypto.randomUUID()`) on every
submit, not left to the caller.

Form fields, deliberately trimmed further than the backend allows: `export_markets`/`products`/
`year_established` are all nullable and left off this first pass — easy to add later, not worth
the extra UI surface now.

Verified: `tsc -b`, `eslint .`, `vitest run` (still 12/12 — the two prior test files needed a
`MemoryRouter` wrapper added once `ExportersListPage` grew real `<Link>`s), `npm run build` all
pass.

**Now also verified against a live backend/DB** (2026-09-21) — running Postgres via the existing
`epic4-reference-postgres` container, `alembic upgrade head`, `uvicorn`. This caught one real bug
neither typecheck nor unit tests could: `onboarding_0009`'s original revision id,
`onboarding_0009_relationship_manager_user` (41 chars), overflowed `alembic_version.version_num`
(`varchar(32)` — every prior revision id in this repo is quietly ≤32 chars already). Worse, because
`migrations/env.py` runs a whole `alembic upgrade head` invocation in one transaction, that failure
rolled back the bookkeeping for the *previous* migration too (`auth_0002_developer_role`) — except
its `ALTER TYPE ... ADD VALUE` ran inside `autocommit_block()`, which isn't transactional, so
`DEVELOPER` was for-real added to `user_role_enum` while `alembic_version` still claimed otherwise.
Fixed by shortening the revision id to `onboarding_0009_rm_user_id` (26 chars) and re-running
`alembic upgrade head` — safe, since `ADD VALUE IF NOT EXISTS` is idempotent. Full detail in the
migration file's own docstring. **Lesson for every future migration in this repo: keep the
revision id ≤32 characters, not just descriptive.**

**A second real bug, also only findable by running it: the 200-vs-201 status code on
`POST /onboarding/exporters` was never actually implemented, for either path.** The endpoint's own
`responses` doc declares 200 for an idempotent replay / existing profile — but both the
pre-existing `create_or_get_profile` branch and this ticket's new `create_lead` branch discarded
the `created` boolean they got back (`_created`, underscore-prefixed — deliberately unused) and
always returned the decorator's default `201`. Found by resubmitting the same `Idempotency-Key`
against a live server and getting `201` twice. Fixed on both branches: `create_lead` now returns
`(request, profile, created)` (previously just the 2-tuple — the missing flag *is* the bug), the
router takes a `Response` parameter and sets `response.status_code = 200` when `created` is
`False`. Confirmed against the live server: fresh create → `201`, replay → `200`, for both
branches.

**Full manual verification performed** (2026-09-21), not just automated checks: `alembic upgrade
head` against the existing `epic4-reference-postgres` container, `uvicorn` boot, then real HTTP
traffic — registered an `OPERATIONS` and a `COMPLIANCE` user, logged in as each, created an
exporter Lead through the actual `create_lead` path, searched for it (confirming the `legal_name`
join), hit the transition endpoint (confirmed 409 on `LEAD→ACTIVE`, 200 on `LEAD→CONTACTED`).
Then the frontend: booted `vite dev`, confirmed its `/api` proxy reaches the live backend, and ran
a throwaway (deleted afterward) unmocked integration test that logs in for real, renders
`ExportersListPage` against real data, and submits the real `AddExporterPage` form — all three
passed, including PAN masking flipping correctly between the two real logged-in users. Both
servers were left running after this session for interactive use — see the end of this doc for
login credentials.

---

## EXP-F3 — Add Exporter

**Goal:** create one, limited to what the backend actually accepts today.

- Single-step or short form against `CreateExporterProfileRequest`'s real fields only: `source`,
  `lifecycle_status` (default `LEAD`, not user-editable at creation beyond that default),
  `gstin`/`pan`/`iec`, `relationship_manager`, `industry`, `export_markets`, `products`,
  `year_established`, `website`. **No** Country/Sector/Consent/Buyers fields — those aren't in the
  backend gap list's "resolved" column yet (see above); don't invent client-side-only fields that
  silently no-op on submit.
- `source` shown as a plain enum select for now — the "EEPC List"-style two-level field
  (source type + free-text list name) from the backend-gaps list isn't resolved, so don't build a
  richer picker implying a capability that doesn't exist server-side yet.

### Acceptance criteria
- Submitting creates a profile and lands on its EXP-F4 detail page.
- Every field the backend's `extra="forbid"` would reject is simply absent from the form, not
  present-and-silently-dropped.
- A duplicate `customer_id` (or idempotent replay via the `Idempotency-Key` header) surfaces the
  existing profile rather than erroring confusingly.

---

## EXP-F4 — Exporter Detail

**Goal:** see everything about one exporter — the hub every later ticket (contacts, activity,
lifecycle, verification) attaches its section to.

- `GET /onboarding/exporters/{customer_id}`: profile fields, lifecycle status badge (semantic
  color per design principles), onboarding history. Masked/unmasked PAN/GSTIN per the capability
  matrix, with the eye-icon reveal where permitted.
- Structure this as a shell with clearly-marked extension points for EXP-F5 (contacts/activity),
  EXP-F6 (the "Move to…" action), and EXP-F8/F9 (verification) rather than a monolithic page built
  once and re-opened repeatedly — each later ticket should be able to add its section without
  restructuring this one.
- No Buyers/Credit tabs (decision #2). No Documents tab — out of this sequence entirely for now
  (see "Build sequence" above); flag before adding it in.

### Acceptance criteria
- Loads correctly for an exporter with zero contacts/activities/history yet (the common case right
  after EXP-F3 creates one) — empty sections, not broken ones.
- `OPERATIONS` viewing an exporter they are not the `relationship_manager` for sees masked
  identifiers with no reveal icon at all, per the capability matrix.

---

## EXP-F5 — Contacts + Activity

**Goal:** the relationship-history core of the CRM, on the EXP-F4 detail page.

- **Contacts**: list + add, primary-contact toggle. The server already demotes the existing
  primary atomically on a race — the UI reflects the resulting state, it doesn't implement the
  demotion logic itself.
- **Activities**: quick-add (type, subject, notes, optional `due_at`) + list, filterable by
  `activity_type`. Append-only per the backend (`ExporterActivity` rejects UPDATE/DELETE) — no
  edit/delete affordance in the UI at all, not just a disabled one.

### Acceptance criteria
- Setting a second contact primary in the UI correctly shows only one primary afterward — no
  client-side race where both briefly show primary.
- A logged activity has no edit or delete control anywhere in the UI.
- Activity list correctly filters by type and paginates against the backend's `limit`/`offset`.

---

## EXP-F6 — Lifecycle "Move to…" Action

**Goal:** the one legal way `lifecycle_status` changes, surfaced on EXP-F4.

- A "Move to…" control offering **only** the legal next states for the exporter's current status —
  not a free-form dropdown of all ten. The permitted-transition table needs to be available
  client-side (mirrored as a constant for now, hand-copied from `exporter_profile_service.py`'s
  `PERMITTED_LIFECYCLE_TRANSITIONS` — flag this as a drift risk; a future backend ticket could
  expose it as data instead of requiring the frontend to hardcode it).
- This is the same control EXP-F10's kanban will reuse as its non-drag fallback — build it as a
  standalone, reusable component now rather than inline page logic, so F10 doesn't rebuild it.

### Acceptance criteria
- Attempting an illegal transition is impossible from the UI (the option isn't offered), not just
  handled after a 409.
- `COMPLIANCE_REVIEW → DATA_COLLECTION` (the one backward edge in the graph) is reachable and
  clearly labeled as a rejection/send-back, not presented identically to a forward move.

---

## EXP-F7 — Follow-ups

**Goal:** the cross-exporter pending-work view — a straight build, since the backend already
anticipated it (`GET /onboarding/exporters/activities/pending`, EXP-1's "Piece 2").

- A list (own page, or a widget — either is fine, no Dashboard ticket exists to host it in this
  sequence) of pending/follow-up activities across every exporter: `exporter_display_name`,
  `subject`, `due_at`, `is_overdue`. Filters: `actor_id` (team-wide vs. mine), `activity_type`,
  `due_before`/`due_after`.
- Once this ships, go back and wire EXP-F2's list with a "Next Follow-up" column sourced from this
  same endpoint, per the note left there.

### Acceptance criteria
- `is_overdue` items are visually distinct from upcoming-but-not-due ones (not just a text
  difference).
- Omitting `actor_id` shows every user's pending items; passing it scopes to one person's.
- Each row links through to that exporter's EXP-F4 detail page.

---

## EXP-F8 — Verification Results (read-only)

**Goal:** make the trust-ledger model (RXIL + ANER re-checks, most-recent-wins) legible, before any
write action exists for it.

- A verification section on EXP-F4, one card per `verification_type` present for that exporter
  (`entity_type=EXPORTER`): the **most recent** result prominent (status, risk_level, provider,
  `performed_at` — "show your work," per the design principles), with an expandable history of
  older results for the same type, never hidden entirely.
- Pure read against `GET /onboarding/verifications?entity_type=...&entity_reference=...` — no
  trigger button, no review action yet. An exporter with zero verification results yet shows an
  honest empty state, not a hidden/missing section.

### Acceptance criteria
- Two `VerificationResult` rows for the same exporter/check type (different providers, different
  `performed_at`) render with the later one as "current" and the earlier reachable via history —
  never both shown as equally current.
- `raw_result` is never requested or rendered — it's already excluded from
  `VerificationResultResponse` server-side; the UI shouldn't assume or work around a field that
  isn't there.

---

## EXP-F9 — Verification Actions (trigger + review)

**Goal:** the two mutations on `VerificationResult`, added once F8 makes the read side trustworthy
to build against.

- **Trigger verification**: today this can only mean `provider="manual"` (`ManualEntryAdapter`),
  the only adapter that exists — build the control honestly scoped to that (a form to record a
  manually-observed result), not a provider dropdown implying vendor choices that don't exist yet.
  Extend once `kyb`'s adapters are wrapped into `VerificationAdapter` and `RxilAdapter` exists.
- **Record review** (compliance-role-gated): sets `reviewed_by`/`review_status` on a result.
  One-time and immutable per `VerificationResultAlreadyReviewedError` — no "edit review"
  affordance anywhere, since the backend rejects a second attempt outright.

### Acceptance criteria
- A non-`COMPLIANCE` user cannot see the "Record review" action at all (not just disabled).
- Attempting to re-review an already-reviewed result is prevented client-side, matching the
  backend's immutability guarantee — no error toast needed for a path the UI shouldn't offer.
- Triggering a manual verification immediately updates EXP-F8's card for that type without a full
  page reload (TanStack Query cache invalidation, not a manual refetch call scattered per-component).

---

## EXP-F10 — Pipeline (kanban)

**Goal:** last, deliberately — the most complex UI in this sequence (drag-and-drop against a
non-trivial legal-transition graph), built last so every primitive it needs (grouped-stage colors,
the "Move to…" component from EXP-F6, masked/unmasked identifier rendering) already exists and is
proven elsewhere first.

- Grouped columns per decision #1. Cards show masked/unmasked identifiers per role, same component
  as EXP-F2's list. Drag is constrained to legal transitions only — illegal columns visually
  disabled the moment a drag starts, not rejected after a drop. EXP-F6's "Move to…" control is the
  non-drag fallback on every card, not a separate reimplementation.
- SUSPENDED/OFFBOARDED are not kanban columns (decision #1) — reachable via EXP-F6's control and a
  separate filter, not a drop target.

### Acceptance criteria
- Dragging a card to an illegal column is impossible — the column shows a disabled state from
  drag-start, not a rejected-drop toast.
- Every action reachable by drag is also reachable via the "Move to…" menu, unmodified from
  EXP-F6 — proving there's one implementation of "what's legal," not two that could drift.

---

## Running this locally (as of 2026-09-21)

Postgres: reuse the existing `epic4-reference-postgres` Docker container (port 5556) — don't spin
up a new one, `backend/.env` already points at it. `alembic upgrade head` from `backend/` if new
migrations have landed since. Backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port
8000` from `backend/`. Frontend: `npm run dev` from `frontend/` (port 5173, proxies `/api` to
`:8000`).

Two real test users exist in that database from this session's manual verification:

| Email | Password | Role |
|---|---|---|
| `rm@aner.example` | `Passw0rd123` | `OPERATIONS` (a Relationship Manager) |
| `compliance@aner.example` | `Passw0rd123` | `COMPLIANCE` |

Try both against the same exporter ("Acme Exports Pvt Ltd") to see the masking behavior differ —
that's the whole point of the role model above.
