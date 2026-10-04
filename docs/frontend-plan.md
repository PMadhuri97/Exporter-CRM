# Aner Labs Exporter CRM — Frontend Plan

| | |
|---|---|
| Date | 4 October 2026 |
| Branch audited | `feature/company-foundation-and-compliance-guard` @ `451ef97` |
| What this file is | A design and engineering plan for the CRM's frontend: an access model that only ever shows a role what it may use, a new design language, and a screen-by-screen redesign, delivered in phases. No code was changed to write it |
| Sources read | `docs/architecture.md`, `docs/plan.md` (incl. §19.0 decisions), `docs/open-items.md`, `docs/demo.md`, the contracts, the design PDF (*Exporter-CRM-Architecture-and-Plan.pdf* v1.0, read from git), `backend/.../test_route_authorization.py` (the role matrix), `frontend/openapi.json`, and every file in `frontend/src` |
| Decisions taken for this plan (4 Oct) | **Direction "Ink & Paper"** (colour only ever means a state); **type: Instrument Serif + Instrument Sans + JetBrains Mono**; **frontend-first**, with backend additions listed as owned *asks* that each have a fallback; **light-first with full dark parity** |
| Feedback this answers | The TL's: the app looks generic and AI-made (purple/teal accents, slate greys, Inter, a card around everything, tables and long forms) |

---

## Contents

1. [Summary](#1-summary)
2. [The product, in the terms a screen needs](#2-the-product-in-the-terms-a-screen-needs)
3. [The frontend today](#3-the-frontend-today)
4. [Access: only what a role may use, failing closed](#4-access-only-what-a-role-may-use-failing-closed)
5. [Design language: Ink & Paper](#5-design-language-ink--paper)
6. [Signature components](#6-signature-components)
7. [Shell, navigation and the command bar](#7-shell-navigation-and-the-command-bar)
8. [Screens](#8-screens)
9. [No generic forms: the replacement for each one](#9-no-generic-forms-the-replacement-for-each-one)
10. [No table views: the replacement for each one](#10-no-table-views-the-replacement-for-each-one)
11. [Accessibility](#11-accessibility)
12. [Engineering: structure, dependencies, performance](#12-engineering-structure-dependencies-performance)
13. [Backend asks](#13-backend-asks)
14. [Delivery phases](#14-delivery-phases)
15. [Definition of done and QA](#15-definition-of-done-and-qa)
16. [Risks](#16-risks)
17. [Open questions](#17-open-questions)
18. [Appendices](#18-appendices)

---

## 1. Summary

**Today** the frontend's behaviour is in good shape. It asks the server what is allowed (`allowed_moves`, `allowed_stage_moves`, `allowed_marker_moves`, `capabilities`), the server does the masking, the query layer is tidy, and there are 45 test files with 435 tests, all passing (run 4 October). What lets it down is how it looks and how it is put together:

- **It looks like a starter template.** Inter on slate greys, a teal accent, violet "Awaiting approval" badges and `rounded-lg border shadow-card` on every surface. Twenty-one component files bypass the tokens and use raw Tailwind colours (`slate-*`, `violet-*`, `emerald-*`, `red-*`, `amber-*`).
- **Everything is a box.** Each screen is a stack of `Panel`s. Companies, qualification, criteria, required documents and the import report are `<Table>`s. Twenty-four files hold a hand-built form.
- **Role-based visibility has gaps** (§3.3). API users see the whole CRM navigation, DEVELOPER is offered "Add company" and "Import CSV", and the admin-only pages announce themselves ("Administrators only") rather than not existing.

**The plan** has three parts:

1. **An access layer that fails closed** (§4). One capability manifest drives the navigation, the routes, the queries, the command bar and the keyboard shortcuts. If a role cannot use a module, its row is absent, its URL reads exactly like a URL that does not exist, its code is never downloaded and its queries never fire. An unknown role, a role still loading, or a failed permissions request all get nothing.
2. **A design language with an opinion** (§5–§6). *Ink & Paper* uses warm paper neutrals and an ink-black primary, and the chrome has **no brand hue**, so every coloured pixel on screen means a state. An editorial serif sets company names and big numbers. One signature object, the **Standing strip** (the PDF's "one company, several gauges" drawn as a single glyph), appears wherever a company does.
3. **Screens built around verbs, not records** (§8–§10). Each role gets its own desk. Companies are dossiers, not rows. The conversation is a track you click along, and the handover guard is a pre-flight checklist. History is a ledger with lanes. Forms become inline edits, smart entry, segmented decisions and composers. ⌘K reaches everything a role may use.

It ships in **six phases** (§14). **Phase 0 closes the access gaps on the current screens, before any visual work**, so the security fix does not wait on the redesign.

---

## 2. The product, in the terms a screen needs

What the architecture says, and what each part means for a screen:

| The model says | So the screen must |
|---|---|
| One company record; a **journey** (`LEAD → PROSPECT → CUSTOMER`), forward only, **never moved by hand** | Show the journey as progress, never as a control. There is no drag on the board, and nothing on screen looks movable |
| Three **gauges** that move independently: qualification, conversation, background check. Plus a **marker** (`NONE / PAUSED / ENDED`) | Show the four positions together, side by side and never merged into one label. That is the PDF's "the same dashboard, three companies". This is the **Standing strip** (§6.1) |
| **The server is the authority**: allowed moves, roles, masking, validation | Offer exactly the moves the server listed, and never compute a move. Show a refusal in the server's words. Send `from_value` and treat a 409 as "someone moved it; look again" |
| **History is never lost**: corrections are new records, decisions are append-only, rows written together share a timestamp | Show history as a ledger. Bundle rows that share a timestamp into one event. Nothing offers "edit" or "delete" on a decision, a review, a document or a history row |
| **A problem stays where it happened**: a buyer's problem never touches the company's gauge, but the handover guard reads both parties | On the deal, show seller and buyer as two separate parties, each with its own standing, and give the guard its own view |
| **Maker-checker** on `CLEAR`, `FLAGGED`, `ON_HOLD`: a proposal waits for a *different* officer | Show "awaiting a second signature" as its own visual state (not a seventh gauge value), with the two signatures drawn |
| **Clear expires** after a year; an expired Clear still reads `CLEAR` but no longer promotes or hands over | Show the Clear with its expiry, and make "Re-KYC due" an attention state on the Clear rather than a different value |
| **Check cycles** (Re-KYC / Re-KYB); the decision reads the current cycle only | Show cycles as a short timeline. Earlier cycles are read-only, and the server says so through `capabilities` |
| **Masking by role**; a role that cannot reveal gets **no reveal control at all** | Render identifiers in one component that owns this rule. Copy is only possible on a revealed value |
| **Anything not yet real is labelled** (pass-through scanner, `NOT_CONNECTED` bank feed, placeholders, legacy buyer) | Keep every honesty label. Restyle them as a quiet "prototype" tag, never delete them |
| **CRITICAL risk must look different on screen** (PDF §3.3) | CRITICAL is the only filled, hatched risk mark (§5.2) |
| No cross-company deal or document list; the search has no `total` | Do not fake either one. Each has a backend ask (§13) and an honest fallback ("200+", or the section hidden) |

The **roles** that matter (architecture §9, route matrix in `test_route_authorization.py`). The UI says **RM** for `OPERATIONS` (IQ-13, `roleLabel()`).

| Role | In one line |
|---|---|
| **RM** (`OPERATIONS`) | Finds, qualifies and talks to companies; opens and moves deals; uploads paperwork; may start a background check and answer "more info". Identifiers masked |
| **Compliance** | Everything an RM does, plus every background-check decision, screening, verification results and reviews, approval of a colleague's proposal, Re-KYC cycles and GST branch flags. Sees full identifiers |
| **Admin** | Everything, plus qualification criteria, required documents, RXIL intake, and users and roles |
| **Developer** | Reads the CRM, masked. **Never** sees the background check, verifications or screening (D8), and gets no stage moves or handover reason |
| **API user** | What public sign-up grants. **Reaches nothing in the CRM** |

---

## 3. The frontend today

### 3.1 What to keep, exactly as it behaves now

These are deliberate and tested. The redesign changes how they look, not how they behave:

- **Server-served actions**: `allowed_moves`, `allowed_stage_moves`, `allowed_marker_moves`, `allowed_cycle_actions`, `allowed_outcomes`, `can_record_results`, `can_open_deal`, `capabilities.can_record_decision`, `allowed_actions` on proposals. The redesign renders these. It never re-derives them.
- **`from_value` on background-check moves**, with a 409 handled as "reload and decide again".
- **Server masking**, and `MaskedValue`'s rule that a masked role gets no eye icon.
- **`paths.ts`** as the single source of URLs. The **legacy `/exporters/*` redirects**. **`?tab=`** deep links on the company page. The tab keys (`overview`, `qualification`, `conversation`, `deals`, `documents`, `background-check`, `history`) stay valid.
- **Query invalidation across the journey** (`journey-invalidation.test.tsx`).
- **Honesty rules**: "200+" and "100+" caps; follow-ups and check-backs kept as **two** lists (a check-back cannot be completed); no drag on the pipeline; no reveal control for masked roles; ENDED hidden by default *by the server*; labels on the pass-through scanner, the bank feed and placeholders.
- **Session handling** in `lib/api/client.ts` (single refresh, Web Locks). Not touched.
- **The stack**: Vite, React 18, TypeScript, TanStack Query, Tailwind, Radix, React Hook Form, Zod and sonner all stay.

### 3.2 What is wrong

| Area | Finding | Evidence |
|---|---|---|
| Look | Inter, slate neutrals, teal `brand-*`, violet badges: the default shadcn/Tailwind look | `tailwind.config.ts`, `index.css`, `BackgroundCheckGauge.tsx` (`bg-violet-50`) |
| Token drift | 21 files use raw palette classes instead of tokens. They look different from the rest and break in dark mode. All are in the compliance, verification and deal-outcome areas | `AwaitingApproval`, `BackgroundCheckGauge`, `BackgroundCheckMoveDialog`, `BankActivityPanel`, `BuyerChecks`, `CheckCycleActions`, `CompanyComplianceSummary`, `ComplianceCheckChip`, `DecisionHistory`, `EvidenceList`, `HomeCards`, `ManualResultForm`, `ProposalHistory`, `ProposalResolveDialog`, `RecordDealOutcomeForm`, `ReviewDialog`, `RiskChip`, `ScreeningChecklist`, `ScreeningItemHistory`, `VerificationSection`, `BackgroundCheckPanel` |
| Boxes | Every section is a bordered, shadowed `Panel`, often a panel inside a tab inside a sticky card | `ExporterDetailPage.tsx` Deals tab: four stacked panels |
| Tables | Six table screens (five use `<Table>`, Users uses a raw `<table>`); the company list is a six-column grid of masked IDs | `ExportersListPage`, `QualificationPanel`, `QualificationCriteriaPage`, `DealRequiredDocumentsPage`, `CompanyImportPage`, `UsersTab` |
| Forms | 24 files hold hand-built forms, many opened as a `FormPanel` box in the middle of the page | §9 lists every one |
| Tabs | The company page has seven tabs of equal weight, and nothing says what to do next | `ExporterDetailPage.tsx` |
| Home | A generic card grid, the same for every role (except two compliance cards) | `HomePage.tsx` |
| Bundle | One ~589 kB chunk (build warning); no route-level splitting | `vite build` |
| Icons | lucide, the default icon set of generated UIs | `package.json` |

### 3.3 Role-visibility gaps, which Phase 0 fixes

Each one shows a module, or announces one, to a role that may not use it:

| # | Gap | Who sees what they should not | Where |
|---|---|---|---|
| G1 | The main navigation is the same for every authenticated user | **API user** sees Home, Companies, Follow-ups, Pipeline. Every one of them 403s | `layout/Sidebar.tsx` (`NAV_ITEMS`, no role filter) |
| G2 | Home renders the follow-ups, check-backs and pipeline cards for every role | **API user** gets three cards that each fire a refused request | `pages/HomePage.tsx` |
| G3 | "Add company" and "Import CSV" buttons are unconditional | **Developer** (and API user) are offered two write screens the server refuses | `ExportersListPage.tsx` header actions |
| G4 | `/companies/new` and `/companies/import` have no route or page guard | **Developer / API user** reach the full forms by URL | `modules/onboarding/routes.tsx`, `AddExporterPage.tsx`, `CompanyImportPage.tsx` |
| G5 | Admin pages guard *inside* the page and render "Administrators only" | **Any non-admin** with the URL learns that the screen exists and that they are excluded. This is the leak the masking principle rejects ("a disabled eye icon would still leak…") | `QualificationCriteriaPage.tsx`, `DealRequiredDocumentsPage.tsx`, `RxilIntakePage.tsx` |
| G6 | Role checks are spread across files, one of them inline | A change of rule must be made in many places, and missing one leaks | `ExporterDetailPage.tsx` (`role === 'COMPLIANCE' \|\| role === 'ADMIN'`), plus the `is*Role` helpers in eight other files |
| G7 | All admin and compliance code ships in the one bundle | Every role downloads screens it can never open | single chunk |

---

## 4. Access: only what a role may use, failing closed

The requirement is: show only the modules that apply to a role, and never place the others even if a check goes wrong. This section defines how. The server stays the authority: it refuses what a role may not do whatever the screen shows. The frontend's job is to never *offer*, *mention*, *fetch* or *download* what the server would refuse.

### 4.1 The role matrix, by module

Taken from the route gates (`STAFF`, `COMPLIANCE_OR_ADMIN`, `ADMIN_ONLY`, `READERS` in `test_route_authorization.py`) and the settings permissions (`users:view`, `roles:view`). "—" means absent: no nav row, no route, no button, no shortcut, no command.

| Module / surface | RM | Compliance | Admin | Developer | API user |
|---|---|---|---|---|---|
| **Desk** (`/`) | RM desk | Compliance desk | Admin desk | Read-only desk | **No workspace** screen |
| **Companies**: register and board (`/companies`, `/pipeline`) | ✓ | ✓ | ✓ | read, masked | — |
| Add company, import CSV | ✓ | ✓ | ✓ | — | — |
| RXIL intake | — | — | ✓ | — | — |
| **Company dossier**: profile, qualification, conversation, deals & trade, documents, ledger | ✓ act | ✓ act | ✓ act | read | — |
| Dossier: **background check** chapter | ✓ read; start; answer more-info | ✓ decide, propose, approve | ✓ decide, propose, approve | — (the chapter does not exist) | — |
| Screening decisions, verification results and reviews, Re-KYC cycles | — | ✓ | ✓ | — | — |
| GST branch: add, deactivate | ✓ | ✓ | ✓ | — | — |
| GST branch: flag, unflag | — | ✓ | ✓ | — | — |
| Bring a buyer-only company into the pipeline | ✓ | ✓ | ✓ | — | — |
| **Deal room** (`/deals/:id`) | ✓ act | ✓ act | ✓ act | read; no stage moves, no handover reason | — |
| Parties' compliance on the deal | ✓ | ✓ | ✓ | — | — |
| Trade history: read / record outcome | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | read / — | — |
| **Agenda** (`/follow-ups`) | ✓ complete | ✓ complete | ✓ complete | read | — |
| **Review** queue (`/review`, new) | — | ✓ | ✓ | — | — |
| Re-KYC due list | ✓ read | ✓ | ✓ | — | — |
| **Settings → My profile, sessions** | ✓ | ✓ | ✓ | ✓ | ✓ |
| Settings → Users / Roles | by permission | by permission | by permission (default ✓) | by permission | by permission |
| Settings → Qualification criteria | — | — | ✓ | — | — |
| Settings → Required documents | — | — | ✓ | — | — |
| Reveal identifiers | — | ✓ | ✓ | — | — |
| Find a company by full PAN/GSTIN/IEC in ⌘K | — (name only) | ✓ | ✓ | — (name only) | — |

Two deliberate choices to note:

- **Criteria and required documents are readable by every CRM role at the API** (`READERS`), but the settings screens are **Admin only**. Other roles already see the criteria inside a company's qualification scorecard, and the required categories inside the deal's pre-flight check. A screen whose only purpose is editing is a module only Admin uses.
- **The RM sees the background-check chapter.** The RM may start a check and answer "more info", and the deal's pre-flight check depends on it. The RM sees no decision, screening or verification *controls*, because the server's `allowed_moves` and `capabilities` leave them out.

### 4.2 One manifest, read by everything

A new `src/platform/access/` holds the single client-side copy of the role groups. It replaces `isStaffRole`, `isAdminRole`, `isComplianceRole` and every inline `role === …`.

```ts
// src/platform/access/capabilities.ts — sketch
export type Capability =
  | 'crm.read'            // READERS
  | 'crm.write'           // STAFF
  | 'company.create' | 'company.import'
  | 'company.rxilIntake'  // ADMIN_ONLY
  | 'compliance.read'     // STAFF  (D8: never DEVELOPER)
  | 'compliance.decide'   // COMPLIANCE_OR_ADMIN
  | 'compliance.queue'    // COMPLIANCE_OR_ADMIN  (GET /background-check/proposals?status=open)
  | 'gst.flag'            // COMPLIANCE_OR_ADMIN
  | 'identifiers.reveal'  // COMPLIANCE_OR_ADMIN
  | 'settings.criteria' | 'settings.requiredDocuments'   // ADMIN_ONLY (write screens)
  | 'settings.users' | 'settings.roles';                // from /auth/me/permissions

// An allowlist per role. No default branch, no denylist: a role nobody listed has nothing.
const ROLE_CAPABILITIES: Readonly<Record<UserRole, readonly Capability[]>> = {
  OPERATIONS: ['crm.read', 'crm.write', 'company.create', 'company.import', 'compliance.read'],
  COMPLIANCE: [/* …RM… */ 'compliance.decide', 'compliance.queue', 'gst.flag', 'identifiers.reveal'],
  ADMIN:      [/* …Compliance… */ 'company.rxilIntake', 'settings.criteria', 'settings.requiredDocuments'],
  DEVELOPER:  ['crm.read'],
  API_USER:   [],
};
```

**The modules table** (`src/app/modules.tsx`) declares each module once: its path, a lazy element, the capabilities it requires, its nav row (label, icon, group) and its shortcuts. The router, the rail, ⌘K and the shortcut map are all **generated from this table**, so none of them can disagree with another.

```ts
{ id: 'review', path: '/review', requires: ['compliance.queue'],
  load: () => import('@/modules/onboarding/review'), nav: { label: 'Review', icon: 'Seal', group: 'work' },
  shortcut: 'g r' }
```

### 4.3 The failure modes, all closed

| Situation | What renders |
|---|---|
| Role not in the manifest (a new backend role, a typo, `undefined`) | Zero capabilities: the **No workspace** screen |
| `/auth/me` still loading | The shell's skeleton only. No rows, no module |
| `/auth/me/permissions` loading or failed | No permission-derived capability, so no Users/Roles rows. Role capabilities are unaffected |
| URL for a module the role lacks | **The same `NotFound` as a URL that does not exist**: same component, same copy, same document title. Never "Administrators only" or "You don't have access" |
| Module code for a role that lacks it | Never downloaded. `React.lazy` sits *inside* the gate, so the import only runs once the gate passes |
| Data for a section the role lacks | Never requested. Gated hooks take `enabled: can(cap)`; a console with no 403s is the test |
| The server says 403 anyway (manifest drift) | The section renders the neutral "This isn't available" inline state, never partial content. In development a `console.warn('[access drift]', route, role)` makes the drift loud |
| A nav row, a button, a command and a shortcut for the same thing | All derived from the same capability, so they appear and disappear together |
| A disabled control for something the role may never do | Not allowed. It is **absent**. Disabled is reserved for "allowed, but not right now" (for example a save button while a request is in flight) |

**No workspace.** API user, an unknown role, or a role with no CRM capability gets one quiet page with no rail, no CRM words and no counts: the brand mark, "Your account doesn't have access to a workspace yet. Ask an administrator.", a link to *My profile* (permitted for every role) and *Sign out*.

### 4.4 Guards in code, and what keeps them honest

- **`<Gate requires={…}>`** wraps every module route and returns `NotFound` when unmet. **`useCan(cap)`** covers individual controls. Both are exported only from `@/platform/access`.
- **A lint rule** bans `role ===`, `role !==`, `.role ==` and imports of the old `is*Role` helpers outside `src/platform/access/**` (ESLint `no-restricted-syntax` + `no-restricted-imports`). A new screen *cannot* invent its own role check.
- **A generated matrix test** iterates over 5 roles × every module in the table and asserts, for each pair: the rail row is present or absent; the route renders the module or the generic `NotFound`; and **no gated request fires** (fetch spy). It replaces and extends `Sidebar.test.tsx` and `routes.test.tsx`.
- **A per-role "nothing forbidden in the DOM" test** renders each desk and each dossier chapter as Developer and as API user, and asserts that none of a fixed list of forbidden strings appears ("Background check", "Approve", "Record a decision", "Reveal value", "Qualification criteria", …).
- **A drift check against the server's table** (ask A7, §13). The backend exports its gated-route table as JSON, and a vitest asserts every manifest capability's routes have exactly the roles the server allows. Until A7 lands, the manifest carries a comment block listing the route-table rows it mirrors, and Phase 0 review checks it by hand.

### 4.5 The two layers, kept apart

1. **Module visibility**: the client manifest, by role, coarse. It answers "does this role have this module at all?"
2. **Action availability**: served by the server, per record. It answers "what may this user do to *this* company or deal *now*?" (`allowed_moves` and friends).

The redesign never uses layer 1 to decide an action the server serves through layer 2. The one exception is a *module* whose every action needs a capability (the Review queue), and that is layer 1 by definition.

---

## 5. Design language: Ink & Paper

### 5.1 Principles

1. **Colour is information.** The chrome is ink on paper, with no brand hue anywhere. Green, red, amber and the one blue are each spent on a single meaning, so a glance at a screen says what is wrong with it.
2. **Paper, not panels.** Structure comes from typography, whitespace and hairlines, not from boxes. A border has to earn its place, and a box inside a box is never needed.
3. **One signature object.** A company is always drawn the same way, as its **Standing** (§6.1): in a list row, on a board card, in a search result, on a deal, in the dossier header. Learn it once and read it everywhere.
4. **Verbs over forms.** The screen asks "what do you want to do?" and opens the smallest surface that does it: an inline edit, a segmented choice, a composer, a step sheet. A long form is a design failure (§9).
5. **Every role gets its own desk.** The home screen answers "what is mine to do now?" for the person signed in, not "here are some numbers".
6. **Keyboard-first, mouse-friendly.** Every action has a pointer path. The frequent ones also have a key (§7.4).
7. **Motion explains change.** When a gauge moves, its lamp travels along its track. When a list filters, rows settle instead of popping. Nothing moves for decoration.
8. **Honest states.** Skeletons are shaped like what they replace. Errors give the server's words and a retry. Prototype limits wear a "prototype" tag. A missing count says "200+", never a guess.

**Never** (this is the list that keeps it from looking generated): purple, violet, indigo or any gradient · glassmorphism or backdrop blur · emoji or sparkles · a row of four KPI tiles · uppercase tracked-out micro-labels on every field · pills on everything · drop shadows on resting surfaces · centred empty states with a large icon in a circle · Inter · cards inside cards · a six-column data table as the main view of anything.

### 5.2 Colour tokens

Every token is a CSS variable holding an RGB triplet, as today, so Tailwind opacity modifiers keep working. The **names change** (`brand-*`, `slate`-like greys and `status-info` go). §14 Phase 1 does the rename with a codemod.

**Neutrals: paper and ink**

| Token | Light | Dark | Use |
|---|---|---|---|
| `paper` | `#F5F3EE` | `#12110E` | App background |
| `surface` | `#FFFFFF` | `#1A1915` | Sheets, dossier body, composer |
| `raised` | `#FFFFFF` | `#201F1A` | Popovers, menus, ⌘K (with the one floating shadow) |
| `sunken` | `#EEEBE4` | `#24221D` | Wells, segmented tracks, hover fill, code |
| `line` | `#E3DFD5` | `#2E2C25` | Hairlines, dividers |
| `line-strong` | `#CFC9BC` | `#3E3B33` | Input borders, the focus offset |
| `ink` | `#17160F` | `#F2EFE6` | Primary text, **primary button fill**, focus ring, selection |
| `ink-2` | `#4A473E` | `#CFCABD` | Secondary text |
| `ink-3` | `#6B675C` | `#A39E90` | Labels, metadata (AA on `surface` in both themes) |
| `ink-4` | `#9C978A` | `#6E695E` | Placeholders and decorative glyphs only, never text that must be read |

**Meaning: each hue spent once.** Each meaning has three roles: `fg` for text and icons (AA on `surface`), `tint` for backgrounds, and `solid` for dots, fills and the gauge lamps.

| Meaning | Used for | Light fg / tint / solid | Dark fg / tint / solid |
|---|---|---|---|
| `positive` | passed, qualified, clear, ready now, paid, scanned-clean | `#1D6B3F` / `#E6F2EA` / `#2F9E5B` | `#6CCB8F` / `#17291E` / `#3FAE6A` |
| `negative` | failed, not qualified, flagged, on hold, quarantined, overdue | `#A8231B` / `#FBE9E7` / `#D83A2E` | `#F08A80` / `#2E1715` / `#E0493C` |
| `attention` | needs review, more info, not now, paused, Re-KYC due, missing | `#7A5300` / `#FBF0D6` / `#E0A526` | `#E9C065` / `#2D2412` / `#D9A33A` |
| `progress` | in review, reaching out, in flight, pending scan | `#2F5D8C` / `#E8EFF6` / `#4A7DB5` | `#8DB6E2` / `#16212D` / `#5A8CC4` |
| `idle` | not started, not contacted, not yet reviewed, ended | `ink-3` / `sunken` / `#A7A193` | `ink-3` / `sunken` / `#6E695E` |

**Deliberately not coloured:**

- **The journey** is *progress*, not *state*: ink dots filled 1/3, 2/3, 3/3 (`●○○ Lead`, `●●○ Prospect`, `●●● Customer`). A buyer-only company shows a dashed empty ring, "Outside pipeline".
- **Awaiting approval** is a dashed ink outline around the gauge lamp plus a two-signature glyph. It is **not** a colour, because nothing has happened yet. (This replaces today's violet.)
- **Selection, focus and the active nav row** are ink, never a hue.

**Risk** (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, decision 6) has a meter glyph so it never depends on colour alone. `CRITICAL` is the only filled mark, as the PDF requires:

| Risk | Mark |
|---|---|
| LOW | `▂▁▁▁` positive fg on positive tint, "Low risk" |
| MEDIUM | `▂▄▁▁` attention fg on attention tint, "Medium risk" |
| HIGH | `▂▄▆▁` negative fg on negative tint, hairline negative outline, "High risk" |
| CRITICAL | `▂▄▆█` **white on solid negative, 45° hatch, leading "!"**, "Critical risk" |

### 5.3 Typography

| Role | Face | Sizes (px / line height) | Used for |
|---|---|---|---|
| Display | **Instrument Serif** 400 (and italic) | 40/44 · 30/36 · 24/30 · 20/26 | Desk greeting and big numerals; company name in the dossier; page titles; deal reference title; empty-state lines |
| UI | **Instrument Sans** (variable) 400/500/600 | 15/22 lead · **14/20 body (default)** · 13/18 secondary · 12/16 caption | Everything else |
| Data | **JetBrains Mono** (variable) 400/500 | 12.5/18 | PAN, GSTIN, IEC, CIN, registration numbers, deal references, invoice numbers, ids |

- Labels are **12px sentence case in `ink-3`**, not uppercase with tracking.
- Numbers are tabular everywhere. *Verify in Phase 1* that Instrument Sans exposes `tnum`. If it does not, counts and amounts use JetBrains Mono at matching size.
- *Verify* the `₹` glyph in both families. The fallback stack (`ui-sans-serif, system-ui`) covers it.
- Self-hosted through `@fontsource` (no external font requests from an internal app). The serif is display-only, so only its regular and italic are loaded.

### 5.4 Space, shape, depth, motion

- **Space**: 4px base; scale 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 56 · 72. Reading width 1240px for the dossier and deal room; boards and the register use the full width.
- **Radius**: 4 tags · 6 controls · 10 sheets and popovers · 14 dialogs. Fully round only for dots, lamps and avatars. **No pill buttons, no pill chips.**
- **Depth**: resting surfaces have hairlines and **no shadow**. Floating layers (popover, menu, ⌘K, sheet) get the one shadow: `0 1px 0 var(--line), 0 16px 40px -16px rgb(23 22 15 / .22)` (dark: black at .6).
- **Motion**: 120 ms for hover and press, 180 ms for popovers and sheets, 240 ms for a lamp travelling along a track. Easing `cubic-bezier(.2,.8,.2,1)` for enter and `cubic-bezier(.4,0,1,1)` for exit. Route changes use the browser's View Transitions through React Router 7's `viewTransition` prop: the company name morphs from a register row into the dossier title. Under `prefers-reduced-motion` all of it becomes instant.

### 5.5 Icons

lucide is replaced by **Phosphor** (regular weight, 1.5px look) behind a single `Icon` map in `src/design/icons.ts`. Screens name icons semantically (`Icon.followUp`, `Icon.seal`), so the set can change in one file. Glyphs carry meaning only together with a label or a shape.

### 5.6 Voice

- Plain verbs on buttons: "Log a call", "Open a deal", "Propose Clear", "Hand over". Never "Submit", never "Proceed".
- Sentence case everywhere. The number comes before the noun: "3 overdue".
- A refusal is shown **in the server's words** (the API's `message`), introduced by what the person tried: "Couldn't hand over: the seller's background check is not clear."
- RM in the UI, never "Operations" (IQ-13). "Aner Labs" as the product name (P1-4).
- No exclamation marks and no "Oops". An empty state is one sentence and, if the role may act, one verb.

### 5.7 Brand mark

A solid ink square with a lower-case italic *a* set in Instrument Serif, knocked out in paper, beside the wordmark "Aner Labs" in Instrument Sans 600. The favicon is the square alone. No hue, no gradient.

---

## 6. Signature components

These are the domain primitives the screens are built from. Each lives in `modules/onboarding/components/` (domain) or `src/design/` (generic) and gets a test and a dev-only style-guide entry (§12.4).

### 6.1 Standing: one company, several gauges

The PDF's concept view ("the same dashboard, three companies") drawn as a component. **Three sizes, one grammar**:

```
inline   ●●○ Prospect   ✓ Qualified   ◕ Interested   ◔ In review
card     ●●○  ✓  ◕  ◔        (lamps only, label on hover)
hero     ┌ Journey ───────┬ Qualification ─┬ Conversation ──┬ Background check ───────┐
         │ ●●○ Prospect   │ ✓ Qualified    │ ◕ Interested   │ ◔ In review  · cycle 2  │
         │ next: Clear    │ 12 Sep         │ log a call     │ 3 of 7 screened         │
         └────────────────┴────────────────┴────────────────┴─────────────────────────┘
```

- **Lamp grammar** (shape and colour, never colour alone):
  - Qualification: `◌` not yet reviewed (idle) · `✓` qualified (positive) · `✕` not qualified (negative).
  - Conversation: `◌` not contacted · `◔` reaching out · `◑` spoke to them · `◕` interested (all progress, the quarter-fill is the warmth) · `‖` not now (attention, with the check-back date) · `●` ready now (positive).
  - Background check: `◌` not started · `◔` in review (progress) · `?` more info (attention) · `●` clear (positive, with the risk meter) · `▲` flagged (negative) · `■` on hold (negative). A dashed ring overlay means awaiting approval. An attention dot means Re-KYC due.
- **Marker**: `‖ Paused` (attention) or `— Ended` (idle, name struck through in lists).
- **Role-aware**: for Developer, **the background-check lamp is not rendered** (D8). Absent, not greyed.
- **Hero is interactive**: each segment opens its chapter. The "next" line comes **only** from served data (for example `allowed_moves` includes `IN_REVIEW` → "start the check"). It is never computed from rules held on the client.
- **Data** (fallback until ask A1): list items carry `journey`, `qualification`, `marker`, `pipeline_status` but **not** `conversation` or `background_check`. Until A1, `inline` and `card` show journey, qualification and marker, plus the other two lamps where the page already has them. `hero` always has all four, because the dossier loads them.

### 6.2 Gauge track: the conversation as something you move along

```
  Not contacted ── Reaching out ── Spoke to them ── Interested ──┬── Ready now
        ◌               ◔              ◑             ◕ (you are here)   ●
                                                                 └── Not now ‖  [ check back on ▾ 12 Nov ]
```

- Nodes the server lists in `GET …/conversation/moves` are clickable. The others are drawn but inert. When there are no moves, the track has no clickable node and no explanation is needed.
- Choosing **Not now** opens a date popover inline (not in the past, as the server checks). Choosing **Ready now** offers "Open a deal" in the same popover, as `OpenDealPrompt` does today.
- On success the lamp travels to the new node (240 ms) and a ledger line appears.

### 6.3 Check runway: the background check as a state map

```
 Not started ─▶ In review ◀──▶ More info
                   │  ╲
                   │   ╲──▶ Flagged ──▶ On hold
                   ▼          ╲________╱──▶ (back to In review)
                 Clear ┄┄ awaiting ✍︎ second signature (proposed by R. Mehta, 11:02)
                   │
                   └──▶ (reopen) In review
```

- The current node is solid. **Outgoing edges are drawn only for `allowed_moves`**. Choosing an edge opens the decision composer (§6.10) for that move.
- An `open_proposal` draws a **dashed** target node with two signature slots: proposer ✓, approver ○. For a second officer the slot reads "Approve" / "Reject" (`allowed_actions`); for the proposer it reads "Withdraw".
- Below it, **Required for Clear**: KYB, AML and Sanctions as three lamps, from `required_checks`. Beside them, the server's `clear_blocked_reasons` as a short "still needed" list.

### 6.4 Pre-flight: the handover guard as a checklist

```
 Ready to hand over?                                  4 of 6
 ✓ Seller is a customer
 ✓ Seller's background check is clear and current (until 3 Oct 2027)
 ✓ A buyer is recorded
 ✕ Buyer's AML is not passed                          Record on buyer ▸
 ✓ Invoicing branch recorded — Maharashtra
 ✕ Pre-shipment document missing                      Upload ▸
```

- **With ask A3** (structured conditions): one row per condition, each with an optional deep link to where it is fixed. The link appears only if the role may act there.
- **Fallback (today)**: one attention callout with `handover_blocked_reason` verbatim: "Not ready to hand over: …". The plan does **not** split the server's string on `;` to fake rows.
- Developer gets neither, because the server gives Developer no reason (D8).

### 6.5 Ledger: history in lanes

```
 Filter  [All] [Journey] [Qualification] [Conversation] [Deals] [Background check] [Documents]
 ─ 3 Oct 2026 ───────────────────────────────────────────────────────────────────────────
 11:04  ● Background check   Clear · Low risk           approved by A. Khan, proposed by R. Mehta
        ●●● Journey          Prospect → Customer        (same moment)
 10:12  ◕ Conversation       Spoke to them → Interested  by R. Mehta
 ─ 2 Oct 2026 ───────────────────────────────────────────────────────────────────────────
 16:40  ▤ Deal DL-0041       Open → Gathering paperwork  by R. Mehta
```

- Lanes come from the history row's `dimension`, and a lane filter uses the route's existing `?dimension=` parameter, so filtering is done by the server. Lane chips are generated from the dimensions actually present, so Developer never sees a "Background check" chip (the server sends Developer no such rows).
- **Rows that share a `created_at` are one event** (they were one transaction, architecture §8) and render as one entry with sub-lines, honestly labelled "same moment". Their order within the event is not presented as chronological.
- Hovering an entry with evidence (a decision) opens its evidence in a hover card (P2-1a's resolved evidence).

### 6.6 Identifier

`<Identifier kind="PAN" value={…} />` replaces `MaskedValue` at every call site. It renders in mono; it shows the eye **only** for `identifiers.reveal`; it offers copy **only** once revealed (copying bullets is useless, and a copy button beside a masked value invites the question). Values arrive masked from the server for masked roles, as now.

### 6.7 Party card

The company mini-dossier for any place a second company appears: the deal room's seller and buyer, trade relationships, match results. Shows the name (serif 18), country, the Standing `inline`, and for staff the compliance summary (`CompanyComplianceSummary`, restyled). It links to the dossier.

### 6.8 Shelf: documents by category

Documents grouped by category as a shelf of file tiles (name, type, size, uploaded by and when, scan state). `PENDING_SCAN` has a slow progress pulse. `QUARANTINED` and `SCAN_FAILED` are negative and never downloadable. The "pass-through scanner" prototype tag sits on the shelf, not on each file. Uploading is a drop zone on the shelf: drop a file, choose its type in a popover, done. On a deal, the shelf marks **required categories** (from `/settings/deal-required-documents`) with ✓ or ✕.

### 6.9 Smart entry

One input that understands what was typed: a PAN (`AAAAA9999A`), a GSTIN (15 characters with an embedded PAN), an IEC, a CIN, or a name. It shows the detected kind as a tag, and live-checks it with `POST /companies/match` (debounced; staff only). Used by *Add company* and by *Choose buyer* on a deal. The masked-role rule (BQ-2) holds: an exact identifier may *name* a company, with its identifiers still masked.

### 6.10 Composer

The bottom sheet (or right sheet on wide screens) that replaces the `FormPanel` box. It has a title verb, the fewest fields, a footer with one primary action, and server errors placed against their field when the error names one. Variants: **activity** (type, subject, optional due), **decision** (move, reason, risk, evidence, with a summary step for Clear: "this Clear will rest on: KYB ✓, AML ✓, Sanctions ✓, 7 of 7 screened, 2 documents"), **verification result**, **review**, **withdraw a deal**, **marker** (pause or end, with reason).

### 6.11 Other primitives (generic, `src/design/`)

`Button` (primary ink, secondary hairline, quiet, destructive outline; sizes 32/36) · `Segmented` (Radix ToggleGroup) · `Tag` (replaces `Chip`: 4px radius, leading glyph, three tones per meaning) · `Field` · `Input` / `Textarea` / `Select` / `DatePopover` · `Editable` (click-to-edit text, number, select) · `Sheet` · `Popover` · `HoverCard` · `Toast` (sonner, restyled) · `Skeleton` (shaped) · `EmptyLine` · `InlineError` · `Kbd` · `Count` (serif numeral with "+" honesty) · `NotFound` · `NoWorkspace`.

---

## 7. Shell, navigation and the command bar

### 7.1 The shell

```
┌──────┬──────────────────────────────────────────────────────────────────────────────┐
│  ■a  │  Companies / Bharat Precision Metals / Background check     ⌘K Find…    RM ◐ │
│      ├──────────────────────────────────────────────────────────────────────────────┤
│  ⌂   │                                                                              │
│  ▦   │                                                                              │
│  ◷   │                                (page)                                         │
│  ✍︎   │                                                                              │
│      │                                                                              │
│      │                                                                              │
│  ⚙   │                                                                              │
└──────┴──────────────────────────────────────────────────────────────────────────────┘
```

- **Rail**: 64px of icons by default, which expands to 232px on hover or pin (state kept per viewer in `localStorage`, guarded as today). It holds the role's work modules, then a gap, then Settings at the foot. The active row is an ink bar on the left plus ink text, with no tinted fill.
- **Context bar** (52px): the breadcrumb trail (each step a link) · ⌘K · the avatar menu (name, role label, theme: system/light/dark, My profile, Sign out). This replaces today's separate top bar.
- **Narrow screens** (<1024px): the rail becomes a bottom bar of up to five icons for the role's modules. Settings moves into the avatar menu.

### 7.2 Navigation per role

| Rail | RM | Compliance | Admin | Developer | API user |
|---|---|---|---|---|---|
| Desk `g h` | ✓ | ✓ | ✓ | ✓ | (no shell) |
| Companies `g c` (register + board) | ✓ | ✓ | ✓ | ✓ | |
| Agenda `g f` | ✓ | ✓ | ✓ | ✓ | |
| Review `g r` | | ✓ | ✓ | | |
| Settings (foot) `g s` | ✓ | ✓ | ✓ | ✓ | |
| Settings → criteria, required documents | | | ✓ | | |

**Pipeline becomes the Board view of Companies.** `/pipeline` stays as a route and opens the board directly, so links and `demo.md` keep working. The rail loses one row that duplicated another.

### 7.3 URLs

Every current URL keeps working. New: `/review` (Compliance, Admin), `/companies?view=board` (with `/pipeline` as its permanent alias), and `/settings/*` sub-routes for its sections (`/settings/profile`, `/settings/users`, `/settings/roles`; the existing `/settings/qualification-criteria` and `/settings/deal-required-documents` stay). The dossier keeps `?tab=` with the current keys. A filtered register is a URL (`?journey=PROSPECT&q=…`), so a filter can be shared.

### 7.4 Keyboard

`⌘K` / `Ctrl K` command bar · `/` focus the page's search · `g` then `h c f r s` go to a module (only the role's) · `j` / `k` move through any list · `Enter` open · `e` edit the focused field (dossier) · `l` log an activity (dossier, staff) · `c` complete (agenda, staff) · `a` / `x` approve or reject (review, compliance; both confirm) · `?` the shortcut sheet, listing **only this role's** keys. Shortcuts never fire inside inputs.

### 7.5 The command bar (⌘K)

```
┌ ⌘K ─────────────────────────────────────────────────────────┐
│  bharat|                                                     │
├──────────────────────────────────────────────────────────────┤
│  Companies                                                   │
│   ●●● Bharat Precision Metals          IN · Customer   ↵     │
│   ●○○ Bharat Agro Overseas             IN · Lead             │
│  On this company                                             │
│   Log a call                                          l      │
│   Open a deal                                                │
│  Go to                                                       │
│   Agenda                                              g f    │
└──────────────────────────────────────────────────────────────┘
```

- Built on `cmdk` (unstyled; styled with the tokens).
- **Find a company**: by name for every reader. By **full** PAN/GSTIN/IEC only for `identifiers.reveal` (the API refuses an identifier search for masked roles, decision 12). For RM, typing something shaped like a PAN shows a hint: "To match a company by PAN, use Add company or Choose buyer", which leads to the BQ-2 match flow.
- **On this company / deal**: actions built from the record's served moves only (for example "Open a deal" appears iff `can_open_deal`).
- **Go to**: the role's modules. **Recent**: the last eight companies opened, kept per viewer (id and name only) and cleared on sign-out.

---

## 8. Screens

Each screen below gives its purpose, who sees it, the layout, the interactions, its data and its fallbacks. Roles not mentioned see the screen as the matrix in §4.1 says.

### 8.1 Sign in

Paper background. The left half (≥1024px) holds a single serif line ("Every company, one record.") over a slow, faint line drawing of the journey track. The right half holds the form: email, password, *Sign in* (ink). Errors are inline. The theme follows the system. No illustration, no gradient, no "Welcome back!".

### 8.2 Desk: one per role

The desk answers one question: **what is mine to do now?** Every section is hidden, not empty, when the role lacks it or an ask has not landed.

**RM desk**

```
 Good afternoon, Ritu                                         Fri 4 Oct
 3 follow-ups overdue · 2 companies to check back on · 1 Re-KYC due

 Up next ─────────────────────────────────────────────── Mine | Team
  ⚑ overdue 2d  Call back about bank statements     Aarav Textiles        c ↵
  ⚑ overdue 1d  Send revised term sheet             Coastal Seafood       c ↵
  ‖ today       Check back (parked "not now")       Deccan Spices           ↵
  ◷ tomorrow    Site visit                          Bharat Precision        ↵

 Pipeline                                   Re-KYC due
   48       21       9                      Bharat Precision   expires 12 Oct
   Leads    Prospects Customers             (read only — Compliance acts)
   ─────────────────────────────── Board ▸
```

- **Up next** merges overdue and due-soon follow-ups (`/follow-ups`, `actorId` for Mine) and due check-backs into **one time-ordered queue**, still labelled by kind. A check-back opens the conversation and is never "completed" (the two-section rule from `FollowUpsPage.tsx`, kept as two kinds in one list). `c` completes a follow-up through a popover holding its outcome.
- **Pipeline** is three serif numerals ("200+" when capped). With ask A2 they become exact.
- **Deals in paperwork** (ask A5) appears only once a cross-company deal list exists.

**Compliance desk**

```
 Good morning, Aisha
 2 decisions await your signature · 4 companies in review · 1 Re-KYC due

 Awaiting your signature ─────────────────────────────────────────────
  ● Propose Clear · Low risk   Bharat Precision    by R. Mehta 11:02   [Approve] [Reject]
  ▲ Propose Flag               Coastal Seafood     by S. Rao   09:40   [Approve] [Reject]

 In review (ask A4)                     Re-KYC due
  Deccan Spices     3 of 7 screened     Bharat Precision   expires 12 Oct   [Start Re-KYC ▸]
```

- Approve and reject keep today's two-click confirm (`ProposalResolveDialog`) and become a popover anchored to the row.
- **In review** needs ask A4 (a `background_check` filter on company search). Until then the section is not shown.
- The RM sections (Up next, Pipeline) sit below, because Compliance holds every RM capability.

**Admin desk**: the Compliance desk plus one line of **Setup** (active criteria versions, required document categories, users awaiting a role). Each item links to its setting.

**Developer desk**: "Read-only access. Identifiers are masked." Then Pipeline, the team's Up next as a read-only list (no `c`), and nothing from compliance.

**API user**: the **No workspace** page (§4.3). It never reaches the shell.

### 8.3 Companies: the register and the board

**Register** (default view). Rows, not a table:

```
 Companies                                       [ Register | Board ]    + Add company ▾
 [All] [Leads 48] [Prospects 21] [Customers 9]   Qualification ▾  Relationship ▾  Outside pipeline
 ───────────────────────────────────────────────────────────────────────────────────────────
  Bharat Precision Metals            ●●● Customer  ✓ Qualified  ● Clear ▂▁▁▁        IN · R. Mehta
  Precision engineering · 2 branches  PAN ••••••1234F
  ───────────────────────────────────────────────────────────────────────────────────────────
  Coastal Seafood Exports            ●●○ Prospect  ✓ Qualified  ▲ Flagged          IN · S. Rao
  Seafood · Kochi                     PAN ••••••7781K
  ───────────────────────────────────────────────────────────────────────────────────────────
  Deccan Spices                      ●○○ Lead      ◌ Not yet reviewed                IN · —
```

- Each row: serif name; Standing `inline`; one muted line of identity (industry, city or branches); the primary identifier through `Identifier`; country and RM on the right.
- **Filters are lenses**: the journey segmented control with counts (capped), plus qualification, relationship and "outside pipeline" toggles. All filtering stays on the server, as today. Lenses live in the URL.
- **Hover** on a row prefetches the dossier (TanStack `prefetchQuery`) and shows a hover card with the hero Standing. **`j` / `k`** move the focus and **Enter** opens.
- **Paging**: "Show more" loads the next 50. With no `total`, the footer reads "50 shown" (exact count after ask A2).
- **+ Add company ▾** (staff only): *Add one* · *Import a CSV* · *RXIL intake* (Admin only, inside the same menu).
- **Bulk anything**: none. The API has no bulk action, so the screen does not invent one.

**Board** (`?view=board`, alias `/pipeline`): three columns (Leads, Prospects, Customers) of Standing `card`s. **No drag**, because the journey is never moved by hand. Each column header says what moves a company out of it: "Qualify to move to Prospect" and "Clear to become a Customer". With ask A1 each card shows the gauge holding it back (Lead: qualification lamp; Prospect: background-check lamp, hidden for Developer).

### 8.4 Add a company: smart entry

```
 Add a company
 ┌──────────────────────────────────────────────────────────────┐
 │ 27AAAPL1234C1ZV                                    [GSTIN]   │
 └──────────────────────────────────────────────────────────────┘
  ✓ Not in Aner yet.   PAN AAAPL1234C will be taken from this GSTIN.

  Name     [ Lakshmi Polymers Pvt Ltd           ]
  Country  [ India ▾ ]                           Source  [ Sales ▾ ]
                                                          [ Create lead ]
  Everything else (contacts, branches, industry) is added on the company itself.
```

- Step 1 is one field. The kind is detected (§6.9) and `POST /companies/match` answers live: **matched** ("Already in Aner: *Bharat Precision Metals*. Open ▸", identifiers masked per role), **possible duplicate** (candidates as Party cards), **conflict** (the server's reason), or **new**.
- Step 2 asks only what the create needs: name, country, source, plus the registration number for a foreign company (IQ-7). A duplicate PAN is refused by the server and shown in its words, with "open the other company" (the holder as a link, as today).
- After creation the dossier opens on the profile chapter, which says what is missing.
- **CSV import** is a drop zone. Client-side it only reads the header row and the first five lines into a preview, so the person sees what they are sending. The server's report then comes back as a list of row lines (✓ created / ⚠ warning / ✕ refused, in the server's words). The client re-implements none of the server's checks. With ask A8 (`dry_run`), the preview becomes the server's own report before commit.

### 8.5 Company dossier

```
 Companies /
 Bharat Precision Metals                                                    ‖ Pause ▾
 Precision engineering · Mumbai · since 2009 · RM R. Mehta     PAN ••••••1234F  GSTIN 2 ▾
 ┌ Journey ─────────┬ Qualification ───┬ Conversation ────┬ Background check ───────────┐
 │ ●●● Customer     │ ✓ Qualified      │ ● Ready now      │ ● Clear ▂▁▁▁ until 3 Oct 27 │
 │ since 3 Oct      │ 12 Sep · R.Mehta │ open a deal      │ cycle 2 · KYB ✓ AML ✓ San ✓ │
 └──────────────────┴──────────────────┴──────────────────┴─────────────────────────────┘
 ┌──────────────┐
 │ Now          │   ◉ Ready now, and no open deal.                          [Open a deal]
 │ Profile      │
 │ Qualification│   Profile ───────────────────────────────────────────────────────────
 │ Conversation │   Industry       Precision engineering          (click to edit)
 │ Deals & trade│   Export markets AE, DE, NL
 │ Documents  3 │   Year founded   2009
 │ Background ● │   Branches       ◉ Maharashtra 27AAA…1ZV    ◉ Gujarat 24AAA…1ZK  ⚑ flagged
 │ Ledger       │
 └──────────────┘
```

- **Header**: serif name; one metadata line; identifiers on the right; the marker as a quiet menu built from `allowed_marker_moves` (absent when there are none). It **compresses on scroll** to an 18px name with the `card` Standing, and stays sticky.
- **Hero Standing**: four segments, each opening its chapter.
- **Chapters**: a sticky left rail on ≥1280px, horizontal tabs below that. Keys and `?tab=` are unchanged. Developer's rail has no *Background check* entry (unchanged rule, now through the manifest).
- **Now** (top of the Overview chapter): at most three next actions, each built **only** from served fields: `can_record_results`, `allowed_outcomes`, the conversation moves, `can_open_deal`, `allowed_moves`, `open_proposal.allowed_actions`, `rekyc_due`. When nothing applies: "Nothing waiting on you here."

**Chapter: Profile** (`overview`). Facts are inline `Editable` fields (staff only; read-only text otherwise), so there is no edit form. **Branches** (GST registrations) is a strip of branch tiles (state, mono GSTIN, active/flagged). Add a branch through smart entry; deactivate on staff; flag/unflag with a reason on `gst.flag` only. A GSTIN another company holds shows the server's warning with a link. Buyer-only companies show "Outside pipeline" and the *Bring into pipeline* verb (staff).

**Chapter: Qualification**: a **scorecard**:

```
 Suggestion: Qualified — every required criterion passes.         [Qualified] [Not qualified]
 ─────────────────────────────────────────────────────────────────────────────────────────
 Annual revenue      ≥ USD 100,000,000   observed [ 140,000,000 ]   [Pass|Fail|Unknown] ✎ note
 Years in business   ≥ 5                 observed [ 17 ]            [Pass|Fail|Unknown] ✎ note
 Export history      optional            —                          [Pass|Fail|Unknown]
```

- One row per criterion, with a `Segmented` result, an inline observed value and an evidence note (PASS/FAIL need evidence; the server says so). Changed rows collect into a sticky "Record 2 results" bar. Nothing is sent per keystroke.
- The outcome buttons are exactly `allowed_outcomes`. *Not qualified* opens reason-code chips (served codes, `other` asks for a note).
- Earlier outcomes and results form a small version trail under the card.

**Chapter: Conversation**: the **Gauge track** (§6.2) on top. **People**: contacts as person tiles (name, role, primary star, masked email and phone per role) with *Add a person* as a composer. **Thread**: activities as a chronological log with a composer pinned at the bottom ("Log a call… / meeting / email / note / task / follow-up"; a follow-up asks for a due date). Filter by type with tags. Today's pagination stays (8 per page, "earlier").

**Chapter: Deals & trade**:

```
 Selling ───────────────────────────────────────────────────────────── [Open a deal]
  DL-0041  Rotterdam shipment   Open ━━●━━ Paperwork ━━○ Handed over    → Rotterdam Trading BV
  DL-0033  Hamburg order        Open ━━━━━ Paperwork ━━● Handed over    → Hanse Metall GmbH
 Buying ─────────────────────────────────────────────────────────────────────────────
  DL-0052  (from Lakshmi Polymers)  Paperwork                           ← Lakshmi Polymers
 Trade ──────────────────────────────────────────────────────────────────────────────
  Bharat Precision → Hanse Metall GmbH     ● ● ● ◐ ○   5 invoices · EUR, USD
```

- Deals are rows with a mini route of their stage and the buyer. *Open a deal* appears iff `can_open_deal`.
- **Trade**: relationship rows with one dot per invoice, coloured by its latest outcome (paid, partial, unpaid, disputed, unknown, and a hollow dot for "nobody looked yet", which `TradeOutcomeChip` already keeps apart). Opening a relationship expands its invoices and outcome chains. Amounts stay in their own currency and are **never totalled** (IQ-4).

**Chapter: Documents**: the **Shelf** (§6.8) for company documents, with upload on staff.

**Chapter: Background check** (`compliance.read`; absent for Developer):

```
 ◔ In review · cycle 2 (Re-KYC, started 1 Oct)                 Cycle  1 · [2]
 ─ Check runway ─────────────────────────────────────────────────────────────────────
   (§6.3 map, edges only for allowed_moves)
 ─ Required for Clear ──────────────────────────  ─ Still needed ───────────────────────
   KYB ✓   AML ◔ in review   Sanctions ◌          AML has no accepted review
                                                   Sanctions not recorded
 ─ Screening  5 of 7 ─────────────────────────────────────────────────────────────────
   ✓ Sanctions lists checked            passed · A. Khan · 1 Oct      📎 1
   ✓ Bank statements reviewed           passed · A. Khan · 1 Oct
   ◌ Suspicious bank indicators         [Pass] [Fail] [Exempt] [Needs review]   (p f e n)
   …
 ─ Verifications ─────────────── [All] [Manual] [Automated] [Needs review] ───────────
   KYB        ✓ Passed   manual · A. Khan · 30 Sep   evidence: registry extract   ⋯ review
   AML        ◔ Review   manual · S. Rao · 1 Oct     awaiting review              [Review]
 ─ Decisions (by cycle) ──────────────────────────────────────────────────────────────
   Ledger-style list; each opens its pinned evidence.
```

- The **screening runway** gives Compliance one row per item and keyboard decisions (`p f e n`, then an optional comment and evidence). It is read-only for RM, from `capabilities.can_record_decision` as today.
- **Verifications** are cards grouped by check type, with provenance tags (`Manual`, `Stub`, `Provider`, and "placeholder" stays loud). *Record a result* and *Review* are composers, offered only on `compliance.decide` and the server's capabilities.
- **Bank activity** stays one honest line: "No bank feed is connected." It is not a panel.
- `VerificationSection`, `ScreeningChecklist`, `DecisionHistory`, `ProposalHistory`, `AwaitingApproval` and `CheckCycleActions` keep their logic and tests. They are re-skinned and re-composed, not rewritten. Their raw palette is removed in Phase 1.

**Chapter: Ledger** (`history`): the **Ledger** (§6.5).

### 8.6 Deal room

```
 Bharat Precision Metals / Deals /
 Rotterdam shipment                                     DL-2026-0041
 Open ━━━━━━● Gathering paperwork ━━━━━━○ Handed over                 [Withdraw]  [Hand over ▸]
 ┌ Seller ───────────────────────────┐       ┌ Buyer ───────────────────────────────────┐
 │ Bharat Precision Metals           │  ───▶ │ Rotterdam Trading BV            NL       │
 │ ●●● Customer  ● Clear ▂▁▁▁        │       │ Outside pipeline · Sanctions ✓  AML ◌    │
 │ invoicing from: Maharashtra ▾     │       │ (chosen once — withdraw to change)       │
 └───────────────────────────────────┘       └──────────────────────────────────────────┘
 Pre-flight (§6.4)                               │  Ledger (deal)
 Paperwork (Shelf, required categories marked)   │  16:40 Open → Gathering paperwork
 Trade between these two (after a buyer company) │  16:41 Buyer recorded
 What was handed over (sealed receipt, once)     │
```

- **Stage moves** are exactly `allowed_stage_moves`. *Hand over* is the one primary action and keeps its confirmation ("This cannot be undone…"). *Withdraw* opens the reason composer. Developer gets none of it and no line saying so; the room reads as a record.
- **Buyer**: *Choose buyer* opens smart entry (match-or-create, set once, as today). The legacy "record details instead" path and `BuyerChecks` stay for legacy buyers until P4-10, visually demoted to a "Legacy buyer record" fold.
- **Invoicing branch** is an inline select on the seller card (`PUT /deals/{id}/invoicing-branch`, staff).
- **What was handed over** is a sealed, read-only receipt: hairline double border, mono references, "taken at the handover" or "reconstructed" in the server's words.
- **Record outcome** (after handover, staff) is the outcome composer, unchanged in logic.

### 8.7 Agenda (follow-ups)

```
 Agenda                                                        Mine | Team   [Overdue ▾]
 ─ Overdue ─────────────────────────────────────────────────────────────────────────
  2d  Call back about bank statements     Aarav Textiles       R. Mehta     [Done ▾]  c
 ─ Today ───────────────────────────────────────────────────────────────────────────
 ─ This week ───────────────────────────────────────────────────────────────────────
 ─ Later ───────────────────────────────────────────────────────────────────────────
 ─ Done (last 14 days) ─────────────────────────────────────────────────────────────

 Parked — check back on                     (companies at "not now")
  Deccan Spices        due today      → conversation
  Konkan Cashew        12 Nov
```

- **Time buckets** replace today's state tabs. The `OVERDUE / OUTSTANDING / DONE` server filters stay, mapped to the buckets. `state` and `is_overdue` are still read from the server, never computed.
- **Complete** is a popover holding the outcome options, or `c`. Staff only; Developer reads.
- **Check-backs** are a separate rail with no complete action (the rule in `FollowUpsPage.tsx`'s header, kept).

### 8.8 Review (new; Compliance, Admin)

A split view for the compliance working day.

```
 Review                                   ┌──────────────────────────────────────────────┐
 Awaiting your signature  2               │ Bharat Precision Metals                      │
  ▸ Bharat Precision — Clear · Low        │ (the dossier's Background check chapter,     │
    Coastal Seafood — Flag                │  embedded, with Approve / Reject at the top) │
 In review (ask A4)  4                    │                                              │
    Deccan Spices — 5 of 7                │                                              │
 Re-KYC due  1                            │                                              │
    Bharat Precision — 12 Oct             │                                              │
                                          └──────────────────────────────────────────────┘
```

- Queue on the left (`j` / `k`), the case on the right (the same chapter component as the dossier, so the two stay identical). `a` / `x` approve or reject, each confirmed.
- Sources: `GET /background-check/proposals?status=open` (`compliance.queue`) and `GET /background-check/due`. **In review** waits for ask A4 and is hidden until then.
- RM and Developer: the module does not exist (§4.1).

### 8.9 Settings

A settings frame with its own left list, showing only the role's sections:

- **My profile** (everyone): name and email as `Editable`; password change as a composer with the existing strength meter; sessions as a list of devices with *Sign out of this one*.
- **Users** (`settings.users`): people tiles (initials avatar, name, email, role tag, active/inactive), with search and a role filter as lenses. *Add a user* and *Reset password* are composers.
- **Roles** (`settings.roles`): role tiles. Opening one shows its **permission grid**, a matrix of toggles grouped by module. This is an editor, not a data view, and the one place a grid is the right tool. Built-in roles are labelled. CRM permissions marked "not enforced" by the catalogue say so in-line ("changes no CRM access today", architecture §9).
- **Qualification criteria** (Admin): rule cards (label, kind, threshold and unit, required, active), each with a **version trail**. *New version* is a composer pre-filled from the current version. The open item about `created_by` showing an id is noted for ask A9.
- **Required documents** (Admin): the document categories as toggles, with their append-only history beneath and the 409 `DEAL_REQUIRED_DOCUMENT_CHANGED` handled as "someone changed this; here is the current rule".

### 8.10 Not found, errors, loading

- **Not found**: serif "Nothing here." and a link back to the Desk. **Used identically for forbidden modules** (§4.3).
- **Errors**: inline in the section that failed, with the server's message and *Try again*. A section's failure never blanks the page (error boundaries per chapter).
- **Loading**: shaped skeletons, never a spinner in the middle of a page. Buttons show their own pending state.

---

## 9. No generic forms: the replacement for each one

Every form surface in `src` today, and what it becomes. Validation keeps Zod at the edge and the server's errors as the authority. A 422 that names a field (`detail[].loc`) is placed on that field; anything else goes in the composer footer.

| Today | Becomes | Pattern |
|---|---|---|
| `LoginPage` | Two fields, split layout | (kept minimal) |
| `AddExporterPage` (long create form) | One field, then two or three | Smart entry §8.4 |
| `CompanyImportPage` | Drop zone, preview, report lines | §8.4 |
| `RxilIntakePage` (paste JSON) | Paste box with a parsed preview card, then *Take in* (Admin) | Composer |
| `CompanyPanel` edit form | Inline `Editable` facts | §8.5 Profile |
| `GstRegistrationsSection` add / flag | Branch strip; add by smart entry; flag reason popover | §8.5 |
| `MarkerControl` (pause/end reason) | Header menu, then reason popover | Composer (marker) |
| `QualificationPanel` results + outcome | Scorecard with segmented results and a sticky record bar | §8.5 |
| `ConversationGaugeControl` (select + date) | Gauge track with date popover | §6.2 |
| `ConversationPanel` contact form | Person composer | Composer |
| `ConversationPanel` activity form | Pinned thread composer | Composer (activity) |
| `OpenDealForm` / `OpenDealPrompt` | One-line popover: reference, then *Open* | Popover |
| `DealDetailPage` buyer form | *Choose buyer* smart entry (legacy form folded) | §6.9 |
| `DealDetailPage` withdraw reason | Reason composer | Composer |
| `CompanyPicker` | Smart entry results as Party cards | §6.9 |
| `DocumentUpload` | Drop on the shelf, type popover | §6.8 |
| `RecordDealOutcomeForm` | Outcome composer (invoice + outcome in one step) | Composer |
| `BackgroundCheckMoveDialog` | Decision composer from a runway edge | §6.3, §6.10 |
| `ProposalResolveDialog` | Approve / reject popover with confirm | Popover |
| `ManualResultForm` | Verification composer | Composer |
| `ReviewDialog` | Review composer (names the current review, as now) | Composer |
| `ScreeningChecklist` item decision | Segmented row + keys | §8.5 |
| `CheckCycleActions` | *Start Re-KYC / Re-KYB* popover with reason | Popover |
| `FollowUpsPage` completion | Done popover / `c` | §8.7 |
| `QualificationCriteriaPage` version form | Rule card, then *New version* composer | §8.9 |
| `DealRequiredDocumentsPage` | Category toggles | §8.9 |
| `UserFormDialog`, `RoleFormDialog`, `ResetPasswordDialog` | Composers | §8.9 |
| `MyProfileTab` | `Editable` + password composer | §8.9 |

---

## 10. No table views: the replacement for each one

| Today | Becomes |
|---|---|
| `ExportersListPage` (6-column table) | The register: dossier rows with Standing (§8.3) |
| `QualificationPanel` results table | The scorecard (§8.5) |
| `QualificationCriteriaPage` table | Rule cards with version trails (§8.9) |
| `DealRequiredDocumentsPage` table | Category toggles and history (§8.9) |
| `CompanyImportPage` report table | Report lines grouped by created / warning / refused (§8.4) |
| `UsersTab`, `RolesTab` | People tiles, role tiles, and the permission grid as an editor (§8.9) |

`components/ui/Table.tsx` is deleted once its last caller moves (Phase 4).

---

## 11. Accessibility

- **WCAG 2.2 AA** in both themes. The token table (§5.2) gives AA text pairs. `ink-4` is never used for meaningful text.
- **Never colour alone.** Every state has a shape (§6.1 lamp grammar, §5.2 risk meter) and a text label, at least as an accessible name.
- **Focus**: a 2px ink ring with a 2px paper offset on everything focusable. Focus never disappears on a composer opening or closing; it returns to the trigger.
- **Keyboard parity**: every pointer action has a key path. Shortcuts are listed per role and never fire inside inputs.
- **Live regions** announce async results ("Decision recorded", "Couldn't hand over: …").
- **Reduced motion** turns every transition off.
- **Tests**: an axe check (`vitest-axe`) on each desk, the register, each dossier chapter, the deal room and settings, in both themes.

---

## 12. Engineering: structure, dependencies, performance

### 12.1 Structure

```
src/
  app/                 modules.tsx (the module table §4.2), AppRouter from it, providers
  platform/
    access/            capabilities.ts, Gate.tsx, useCan.ts, NoWorkspace.tsx, tests (matrix)
    auth/              unchanged API; roleLabel() stays; is*Role() removed after Phase 0
    theme/             unchanged mechanism, new tokens
  design/              tokens (CSS), icons.ts, primitives (§6.11), dev-only style guide
  layout/              Rail, ContextBar, CommandBar, Shortcuts
  modules/onboarding/  unchanged layout (api, hooks, components, pages, paths.ts)
    components/standing/  Standing, GaugeTrack, CheckRunway, Preflight, Ledger, PartyCard, Shelf, SmartEntry
    review/            the Review module (new)
  modules/settings/    sections become sub-routes
```

The ESLint `boundaries` rules stay. `design/` and `platform/` are importable from modules, and modules export only through `index.ts`, as today.

### 12.2 Dependencies

| Add | Why |
|---|---|
| `@fontsource/instrument-serif`, `@fontsource-variable/instrument-sans`, `@fontsource-variable/jetbrains-mono` | Self-hosted type (§5.3) |
| `cmdk` | The command bar |
| `@radix-ui/react-popover`, `@radix-ui/react-toggle-group`, `@radix-ui/react-hover-card` | Popovers, segmented controls, hover previews (same family as the Radix already used) |
| `@phosphor-icons/react` | Icons (§5.5) |
| dev: `vitest-axe` | Accessibility assertions |
| dev, optional: `@playwright/test` | Visual snapshots per role (§15) |

| Remove | When |
|---|---|
| `@fontsource-variable/inter` | Phase 1 |
| `lucide-react` | Phase 2, once `Icon` covers every use |

### 12.3 Performance

- **Route-level code splitting** through the module table (`React.lazy` inside `Gate`). This removes the ~589 kB single-chunk warning, and forbidden modules are never downloaded (§4.3).
- **Budget**: initial JS ≤ 250 kB gzip-equivalent on the Desk. Fonts preloaded (serif regular, sans variable latin subset).
- **Prefetch on intent**: hovering or focusing a company row prefetches its detail. The dossier opens with data already in the cache.
- **No optimistic state transitions** for anything the server decides (gauges, stages, decisions). The lamp moves when the server answers. Optimistic only for an activity appearing in the thread, rolled back on error.

### 12.4 The style guide

A dev-only route (`/__design`, mounted only when `import.meta.env.DEV`, so it is **not in the production bundle**) renders every token, primitive and signature component in both themes, with every state. It replaces the need for Storybook and doubles as the visual review page for the TL.

---

## 13. Backend asks

None of these blocks a phase. Each unlocks a richer version, and until it lands the fallback in the right-hand column ships. Owners follow `developer-allocation.md` lanes. Every ask that changes a schema regenerates `openapi.json` and `schema.ts`.

| # | Ask | Owner (lane) | Unlocks | Fallback until then |
|---|---|---|---|---|
| A1 | Company list items carry `conversation`, `conversation_check_back_on`, and for staff only `background_check`, `awaiting_approval`, `rekyc_due` (omitted for Developer, D8) | Dev 3 (company record) with Dev 1 (compliance read) | Full Standing in register, board, ⌘K, hover cards | Journey + qualification + marker only |
| A2 | `total` on `GET /exporters` search | Dev 3 | Exact counts on Desk, register, board | "200+" / "50 shown" |
| A3 | Structured `handover_conditions: [{key, met, message}]` beside `handover_blocked_reason` (the guard is already an ordered list, `domain/handover_conditions.py`) | Dev 2 | Pre-flight checklist with deep links | The server sentence in one callout |
| A4 | `background_check` filter on company search (staff only) | Dev 3 with Dev 1 | "In review" on the Compliance desk and Review queue | Section hidden |
| A5 | Cross-company `GET /deals?stage=…` (staff + Developer, masked) | Dev 2 | "Deals in paperwork" on the RM desk; a deals lens | Section hidden |
| A6 | `relationship_manager_user_id` written (it is never written today) and a `relationship_manager_user_id` filter | Dev 3 | "My companies" lens; RM avatars | RM shown as free text; no "mine" for companies |
| A7 | Export the gated-route table (`method, path, roles`) as a JSON artifact, guarded like `openapi.json` | Dev 1 | Automated drift check of the access manifest (§4.4) | Manual check in review |
| A8 | `dry_run=true` on `POST /imports/companies` | Dev 3 | Server-validated CSV preview | Header and first lines previewed client-side |
| A9 | Criteria versions carry `created_by_name` (`remaining-work.md` R-36) | Dev 3 | Names instead of ids on the criteria trail | The id, labelled "user id" |

---

## 14. Delivery phases

Each phase merges on its own and leaves the app working. Gates for every phase: `npx tsc -b --noEmit` · `npx eslint .` (0 errors) · `npx vitest run` (no test removed without its replacement) · `npx vite build`. Do **not** run prettier over existing files (there is no prettier config; the repo is hand-formatted, single quotes, ~100 columns).

### Phase 0: Access, failing closed (on the current screens)

- `platform/access` (manifest, `Gate`, `useCan`, `NoWorkspace`) and the module table driving router and rail.
- Fix G1–G7: rail and Desk filtered by capability; API user gets No workspace; `Add company` / `Import CSV` and their routes gated on `company.create` / `company.import`; criteria, required documents and RXIL guarded **at the route**, rendering the generic `NotFound` (the in-page "Administrators only" goes); all `role ===` and `is*Role` call sites moved to `useCan`; lazy module loading.
- Lint rule (§4.4) and the matrix tests (5 roles × every module: rail, route, no forbidden fetch, no forbidden text).
- **Done when**: signed in as each of the five roles, the rail, the routes and the network tab match §4.1, and the matrix test proves it.
- **Status: built 4 October 2026** (`remaining-work.md` R-33). One deviation: the module
  table is `src/routes/modules.ts`, beside the router it drives, rather than a new
  `src/app/modules.tsx`. The matrix test is `src/routes/access.matrix.test.tsx`. The
  drift check against the server's table still waits on ask A7; until then
  `capabilities.ts` lists the route-table rows it mirrors, as §4.4 says.

### Phase 1: Tokens, type, primitives

- New tokens (§5.2) in light and dark; Tailwind config maps them; fonts (§5.3); the brand mark; `Icon` map.
- Codemod: every raw palette class in the 21 files (§3.2) moved to meaning tokens; `brand-*` and `status-info` retired; a lint rule (`no-restricted-syntax` on class strings matching `(slate|gray|zinc|violet|purple|indigo|emerald|teal|blue|red|amber|orange|green)-\d`) stops new ones.
- Primitives (§6.11) and the dev-only style guide.
- **Done when**: no raw palette class remains; both themes pass the axe check on the style guide; the current screens render in the new look with no behaviour change (the existing 435 tests pass).

### Phase 2: Shell

- Rail, context bar and breadcrumbs, avatar menu (theme here), ⌘K, shortcuts and the `?` sheet, sign-in, No workspace, NotFound, the bottom bar on narrow screens. Pipeline folded into Companies as a view, with `/pipeline` as an alias.
- **Done when**: every role's ⌘K, shortcuts and rail come from the module table (matrix test extended), and lucide is gone.

### Phase 3: Signature components

- Standing (three sizes, role-aware), Gauge track, Check runway, Pre-flight (fallback mode), Ledger, Party card, Shelf, Smart entry, Composer variants.
- **Done when**: each has unit tests for every state, including Developer's absent lamp, and a style-guide page.

### Phase 4: Screens

In this order, because each step reuses the one before it:

1. **Companies** register and board (§8.3); add company and import (§8.4).
2. **Dossier** header, hero, Now, and the Profile, Qualification, Conversation, Deals & trade, Documents and Ledger chapters (§8.5).
3. **Background check** chapter, re-composed from the existing Dev 1 components (§8.5).
4. **Deal room** (§8.6).
5. **Desks** for each role (§8.2) and the **Review** module (§8.8).
6. **Agenda** (§8.7).
7. **Settings** sections (§8.9).

**Done when** (each screen): §15's checklist passes, and its old tests are updated in the same change. Accessible names and `data-testid`s are kept where tests rely on them, and changed deliberately where the structure changed.

### Phase 5: Polish

- View transitions (register to dossier name morph), lamp travel, settle animations, reduced-motion check.
- Performance budget, prefetch on intent, font subsetting.
- Optional Playwright visual snapshots: 5 roles × Desk, register, dossier (each chapter), deal room, agenda, settings, in light and dark, on the sample data (`demo.md` §1).
- Each backend ask (§13) that has landed: switch its fallback off.

**Ownership.** Shared frontend files (`lib/api`, `platform/auth`, `routes`, `layout`, the sidebar) belong to Developer 1 (architecture §10), so Phases 0 and 2 need Developer 1's review. Phase 4 screens touch every lane's panels, so each screen's change is reviewed by that panel's owner. The design work itself (tokens, primitives, signature components) belongs to whoever owns this plan.

---

## 15. Definition of done and QA

For every screen, before it merges:

- [ ] **Roles**: walked as RM, Compliance, Admin, Developer and API user; what shows matches §4.1; no forbidden request in the network tab; the matrix test covers it.
- [ ] **Server authority**: every action rendered from a served list or capability; no move, outcome or stage computed on the client; refusals shown in the server's words; `from_value` and 409 handled where they apply.
- [ ] **Masking**: identifiers only through `Identifier`; no reveal or copy control for masked roles.
- [ ] **States**: loading (shaped), empty (one line, one verb if permitted), error (inline, retry), and the prototype labels present.
- [ ] **Both themes**: light and dark checked; axe clean.
- [ ] **Keyboard**: every action reachable; focus visible and returned; this screen's shortcuts in `?`.
- [ ] **Widths**: 1440, 1280, 1024, 768 and 390; no horizontal page scroll.
- [ ] **Tokens only**: no raw palette class; no new shadow on a resting surface; no pill button.
- [ ] **Copy**: verbs on buttons, sentence case, "RM" not "Operations", "Aner Labs".
- [ ] **Gates**: tsc, eslint, vitest, build, all green.

---

## 16. Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| The access manifest drifts from the server's route gates | A role is shown something that 403s, or misses something it may use | One manifest; lint ban on role checks elsewhere; matrix test; drift check with A7; dev-mode drift warning |
| Redesign changes break the 435 existing tests | Tests assert accessible names, copy and test ids | Keep names and ids where possible; update tests in the same change; never delete a test without a replacement |
| Touching every lane's panels at once causes merge conflicts | Five lanes own panels | Phase 1 is a mechanical codemod in one change; Phase 4 goes screen by screen with each owner reviewing |
| "Ink & Paper" reads as too quiet | Little colour by design | Colour is reserved for state, so the screens with problems are the ones that light up; serif numerals and the Standing glyph carry the character. The style guide is reviewed with the TL at the end of Phase 1, before screens move |
| Instrument Sans lacks tabular figures or ₹ | Misaligned numbers, a missing glyph | Verified in Phase 1; mono numerals and the system fallback are ready |
| Fallbacks look unfinished while asks are pending | Hidden sections can feel missing | Hidden, never empty; each desk section names nothing it cannot fill |
| Motion feels gimmicky | Undermines "calm" | Motion only explains a change; 240 ms maximum; off under reduced motion |

---

## 17. Open questions

None of these blocks Phase 0 or Phase 1.

1. **The brand mark.** The italic serif *a* in an ink square is a placeholder for a wordmark the business may already have. Is there an Aner Labs logo to use?
2. **The Developer desk.** Is a read-only desk useful to the people with that role, or should Developer land on Companies?
3. **Review for Admin.** Admins hold every compliance capability. Should Review be in an Admin's rail by default, or only once the Admin has acted on a proposal?
4. **Which asks to schedule.** Recommended order: A1 and A3 (the two most visible), then A2, A4, A7.

---

## 18. Appendices

### 18.1 Current to new: component map

| Current | New |
|---|---|
| `Panel`, `Card` | Section headings with hairlines; `Sheet` for floating |
| `Chip`, `JourneyChip`, `QualificationChip`, `MarkerBadge`, `DealStageChip`, `VerificationStatusChip`, `ScanStatusBadge` | `Tag` + lamp grammar; Standing |
| `BackgroundCheckGauge`, `AwaitingApproval` | Standing lamp + Check runway |
| `RiskChip` | Risk meter mark (§5.2) |
| `MaskedValue` | `Identifier` |
| `HistoryTimeline`, `DealHistory` | `Ledger` |
| `FormPanel` | `Composer` |
| `Table` family | Removed (§10) |
| `Sidebar`, `AppShell` top bar | `Rail`, `ContextBar`, `CommandBar` |
| `HomeCards` | Desk sections per role |
| `PipelinePage` | Companies board view |
| `isStaffRole`, `isAdminRole`, `isComplianceRole`, inline `role ===` | `useCan(capability)` |

### 18.2 Lamp grammar, at a glance

| Gauge | idle | progress | attention | positive | negative |
|---|---|---|---|---|---|
| Qualification | `◌` not yet reviewed | — | — | `✓` qualified | `✕` not qualified |
| Conversation | `◌` not contacted | `◔ ◑ ◕` reaching out, spoke, interested | `‖` not now | `●` ready now | — |
| Background check | `◌` not started | `◔` in review | `?` more info | `●` clear (+ risk) | `▲` flagged, `■` on hold |
| Overlays | dashed ring = awaiting approval · attention dot = Re-KYC due | | | | |
| Journey (not a state) | `●○○` lead · `●●○` prospect · `●●●` customer · dashed ring = outside pipeline | | | | |

### 18.3 Where each decision in this plan comes from

| Rule in this plan | Source |
|---|---|
| Absent, never disabled, for what a role may not do | architecture §9 ("a disabled eye icon would still leak…"); `SettingsPage.tsx` comment |
| The server decides moves; the screen asks | architecture §1, §4; PDF §2.6 |
| CRITICAL looks different | PDF §3.3 |
| One company, several gauges, drawn together | PDF poster, "The same dashboard, three companies" |
| No drag on the journey | architecture §4 (journey never moved by hand) |
| Follow-ups and check-backs stay two kinds | `FollowUpsPage.tsx` header; `engagement.md` |
| RM, not Operations; Aner Labs | plan.md P1-4, P1-5; IQ-13 |
| Developer never sees background check, verification or screening | D8 (`contracts/background-check.md` §14) |
| API user reaches nothing | `test_api_user_reaches_nothing_in_the_crm` |
| Masked roles cannot search by identifier; exact match may name a company | decision 12; BQ-2 |
| Amounts never totalled, kept in their currency | IQ-4; `trade-history.md` |
