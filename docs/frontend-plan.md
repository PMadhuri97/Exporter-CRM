# Aner Labs Exporter CRM — Frontend Plan

| | |
|---|---|
| Date | 5 October 2026 (second version) |
| Code base | `main` @ `9ed6cb6`, with the "Ink & Paper" redesign merged (PR #19) |
| What this file is | The plan for the next pass on the CRM frontend. It replaces the "Ink & Paper" visual layer with a standard enterprise CRM look and layout. It keeps the access model and every behaviour the server drives. This is a plan only: no code was changed to write it |
| Replaces | The 4 October version ("Ink & Paper"), kept in git at `a77725d:docs/frontend-plan.md`. Its access section is built, so it is carried over under the **same section numbers (§4.1–§4.5)**. Code comments that cite §4.x stay correct. §13–§15 also keep their roles, because `remaining-work.md` cites them |
| Decisions (5 October) | (1) **Standard enterprise CRM look**, modelled on Salesforce Lightning, Dynamics 365, HubSpot and SAP Fiori. (2) **No data-table views and no generic forms.** The rule from 4 October stays. (3) From the redesign, **keep only what enterprise CRMs also do** (§3.3). (4) **Plan first.** The TL reviews this plan, and the style guide at the end of Phase 1, before screens change |
| Feedback this answers | The TL did not like the redesign. It reads as AI-generated, and the UI before it was closer to what is wanted |

---

## Contents

1. [Summary](#1-summary)
2. [The product, in the terms a screen needs](#2-the-product-in-the-terms-a-screen-needs)
3. [The frontend today](#3-the-frontend-today)
4. [Access: only what a role may use, failing closed](#4-access-only-what-a-role-may-use-failing-closed)
5. [Design language: standard enterprise](#5-design-language-standard-enterprise)
6. [Components](#6-components)
7. [Shell, navigation and search](#7-shell-navigation-and-search)
8. [Screens](#8-screens)
9. [No generic forms: the replacement for each one](#9-no-generic-forms-the-replacement-for-each-one)
10. [No table views: the replacement for each one](#10-no-table-views-the-replacement-for-each-one)
11. [Accessibility](#11-accessibility)
12. [Engineering](#12-engineering)
13. [Backend asks](#13-backend-asks)
14. [Delivery phases](#14-delivery-phases)
15. [Definition of done and QA](#15-definition-of-done-and-qa)
16. [Risks](#16-risks)
17. [Open questions](#17-open-questions)
18. [Appendices](#18-appendices)

---

## 1. Summary

**Where we are.** The redesign merged on 5 October fixed real problems. Each role sees only what it may use, each screen loads its own code, and every colour comes from a token. The problem is how it looks. It uses:

- a cream "paper" background, a display serif and monospace identifiers;
- an ink-black primary button, and status drawn as glyphs (◔ ◑ ◕ ‖ ▲);
- invented names: Desk, Dossier, Ledger, Shelf, Runway, Pre-flight;
- a time-of-day greeting and Vim-style shortcuts.

Any one of these could be defended. Together they look like a generated demo, not a tool the RM and Compliance teams use all day.

**Where we are going.** The CRM should look and work like the enterprise CRMs people already know:

- An **app header** with search and a *New* menu, and a **labelled left navigation**.
- **Record pages**: a header with the key fields and actions, a stage **path**, **tabs**, and related records as **cards in a right-hand column**.
- An **activity timeline** with a composer for calls, meetings, notes and follow-ups.
- **Lists without data grids**: record lists, a pipeline board and a split view.
- **Quick create and quick actions in a side panel**, and **inline edit** on record details, instead of long forms.
- **Plain names**: Home, Companies, Pipeline, Follow-ups, Approvals, History. **Status in words.**
- **One brand colour** for actions, neutral greys, and the operating system's UI font.

**What does not change.** Access (§4), every server-driven behaviour (§3.1), every URL, and the tests that prove them.

**Delivery.** Three phases (§14). Phases 1 and 2 cover everything the demo walks through (`demo.md` §2–§5). The TL reviews the style guide and one real screen at the end of Phase 1, before the screens are re-laid out.

---

## 2. The product, in the terms a screen needs

| The model says | So the screen must |
|---|---|
| One company record. A **journey** (`LEAD → PROSPECT → CUSTOMER`), forward only, **never moved by hand** | Show the journey as a read-only path under the record header. It has no "mark as current" step and the pipeline board has no drag |
| Three **gauges** that move independently: qualification, conversation, background check. Plus a **marker** (`NONE / PAUSED / ENDED`) | Show them as separate worded badges side by side, in the record header and on list items. Never merge them into one label |
| **The server is the authority**: allowed moves, roles, masking, validation | Offer exactly the moves the server lists and never compute one. Show a refusal in the server's words. Send `from_value`, and treat a 409 as "someone changed it, look again" |
| **History is never lost** | The History tab is read-only. Rows that share a timestamp are one event. There is no edit or delete on a decision, review, document or history row |
| **A problem stays where it happened** | The deal shows seller and buyer as separate cards, each with its own status. The handover checklist reads both |
| **Maker-checker** on `CLEAR`, `FLAGGED`, `ON_HOLD` | An "Awaiting approval" badge shows the proposer and the time. *Approve* and *Reject* appear only for a different officer |
| **A Clear expires** after a year | The Clear badge carries "until <date>". "Re-KYC due" is its own attention badge, not a different value |
| **Check cycles** (Re-KYC / Re-KYB) | A cycle selector on the Background check tab. Earlier cycles are read-only, as the server's `capabilities` say |
| **Masking by role**; a role that cannot reveal gets **no reveal control at all** | One `Identifier` component owns the rule. Copy is offered only on a revealed value |
| **Anything not yet real is labelled** | Every "Prototype" label stays: pass-through scanner, bank feed, placeholders, legacy buyer |
| **CRITICAL risk must look different** (PDF §3.3) | Critical is the only solid risk badge (§5.2) |
| No cross-company document list; company search has no `total` (the Deals list, `GET /deals`, has both a cross-company list and a `total`) | Don't fake either one. Keep the "200+" caps, and hide a section until its backend ask lands (§13) |

The **roles** (architecture §9, route matrix in `test_route_authorization.py`). The UI says **RM** for `OPERATIONS`.

| Role | In one line |
|---|---|
| **RM** (`OPERATIONS`) | Finds, qualifies and talks to companies; opens and moves deals; uploads paperwork; may start a background check and answer "more info". Identifiers masked |
| **Compliance** | Everything an RM does, plus background-check decisions, screening, verification results and reviews, approving a colleague's proposal, Re-KYC cycles and GST branch flags. Sees full identifiers |
| **Admin** | Everything, plus qualification criteria, required documents, RXIL intake, users and roles |
| **Developer** | Reads the CRM, masked. **Never** sees the background check, verifications or screening (D8). Gets no stage moves and no handover reason |
| **API user** | **Reaches nothing in the CRM** |

---

## 3. The frontend today

### 3.1 What to keep, exactly as it behaves now

These are deliberate and tested. This plan changes how they look, not how they behave:

- **Server-served actions**: `allowed_moves`, `allowed_stage_moves`, `allowed_marker_moves`, `allowed_cycle_actions`, `allowed_outcomes`, `can_record_results`, `can_open_deal`, `capabilities.can_record_decision`, and `allowed_actions` on proposals. Screens render these and never re-derive them.
- **`from_value`** on background-check moves, with a 409 handled as "reload and decide again".
- **Server masking**, and `Identifier`'s rule: no reveal control for a masked role, and copy only on a revealed value.
- **`paths.ts`** as the single source of URLs. The legacy `/exporters/*` redirects. The **`?tab=`** keys on the company page, in display order (`overview`, `qualification`, `conversation`, `documents`, `background-check`, `deals`, `history`): roughly the order the work happens, judging the company, then its papers, then trading with it.
- **Query invalidation across the journey** (`journey-invalidation.test.tsx`).
- **Honesty rules**: "200+" and "100+" caps; follow-ups and check-backs kept as two kinds (a check-back cannot be completed); no drag on the pipeline; ENDED hidden by default *by the server*; the prototype labels.
- **Session handling** in `lib/api/client.ts` (single refresh, Web Locks).
- **The access layer** (§4), route-level code splitting, the module table, and the page-to-shell registry (`platform/shell`).
- **The stack**: Vite, React 18, TypeScript, TanStack Query, Tailwind, Radix, React Hook Form, Zod, sonner, cmdk.

### 3.2 What reads as generated

| # | What | Where in the code | Replaced by |
|---|---|---|---|
| 1 | Cream "paper" page with hairline sections and no containers | `design/tokens.css` (`--paper` `#F5F3EE`) | Neutral grey page with white cards (§5.2, §5.4) |
| 2 | Display serif for titles, company names and numbers (Instrument Serif) | `font-display` in 21 files | One sans family; weight sets the hierarchy (§5.3) |
| 3 | Monospace for every identifier and reference (JetBrains Mono) | `font-mono` in 17 files | The UI font with tabular figures (§5.3) |
| 4 | Ink-black primary button and no brand colour | `components/ui/Button.tsx`, tokens | One brand blue for primary actions, links and selection (§5.2) |
| 5 | Status as glyphs (◌ ◔ ◑ ◕ ‖ ● ▲ ■) and the "Standing" strip | `components/standing/` (`lamps.ts`, `Lamp`, `Standing`) | Worded status badges (§6.4, §18.2) |
| 6 | Invented names: Desk, Agenda, Review, Dossier, Chapters, Ledger, Shelf, Runway, Pre-flight, Composer, "Find…" | nav labels in `routes/modules.ts`; page titles | Standard CRM names (§18.1) |
| 7 | "Good afternoon, Ritu" and big serif numerals on the home page | `pages/HomePage.tsx` (`greeting()`) | Home as a grid of work cards (§8.2) |
| 8 | Icon-only rail that widens on hover | `layout/Rail.tsx` (64 → 232 px) | Labelled side navigation, collapsed only by a button (§7.3) |
| 9 | Vim-style keys: `g h`, `g c`, `j`/`k`, `c`, `l`, `a`/`x`, and a `?` sheet | `layout/useGlobalShortcuts.ts`, `platform/shell/keys.ts` | `/` and Ctrl+K for search, Ctrl+/ for the shortcut list (§7.5) |
| 10 | Command palette with actions ("Log a call", "Go to") | `layout/CommandBar.tsx`, `CommandBody.tsx` | Header search over companies and pages only (§7.5) |
| 11 | The company name morphing between pages, lamps "travelling", rows that "settle" | `lib/viewTransition.ts`, `lib/motion.ts` | Plain fades on menus and panels only (§5.6) |
| 12 | Bottom/right "composer" sheets | `components/ui/Composer.tsx` | A right-hand side panel with a standard header and footer (§6.9) |
| 13 | Brand mark: an italic serif *a* in a black square | `design/BrandMark.tsx`, `public/favicon.svg` | A plain wordmark until a logo exists (§5.8) |
| 14 | Theme follows the system, so a laptop in dark mode demos in dark | `platform/theme/theme.ts` (`'system'` default) | Light by default; dark offered in the user menu (§5.2) |
| 15 | Literary copy: "Nothing here.", "Every company, one record.", "Nothing waiting on you here." | `components/ui/NotFound.tsx`, sign-in, home | Plain product copy (§5.7) |

### 3.3 What stays from the redesign

These stay because enterprise CRMs do them too. Each is restyled to §5:

| Keep | Enterprise counterpart |
|---|---|
| Fail-closed access (§4): absent, never disabled | Not visual; untouched |
| Global search in the header, opened by Ctrl+K or `/` (companies and pages only) | Global search in the Salesforce, Dynamics and HubSpot headers; `/` is Salesforce's search key |
| The **Approvals** queue (was *Review*), as a split view | Salesforce "Items to Approve"; Salesforce split view; Fiori list-detail |
| The **Pipeline** board, with no drag | Salesforce Kanban list view; HubSpot board |
| Inline edit of company facts | Salesforce inline edit on record details |
| The activity composer on the company | Salesforce activity composer; Dynamics timeline with quick create |
| Quick create of a company with a live identifier match | Dynamics quick create with duplicate detection |
| The handover guard as a checklist | Salesforce Path key fields and guidance per stage; Dynamics business process flow steps |
| The dev-only style guide (`/__design`) | Becomes the page the TL reviews (§12.4) |

**Removed**: the glyph grammar and the Standing strip, the serif and monospace faces, the invented names, the `g` chords and single-letter action keys, the actions in the command palette, the view-transition morph and lamp travel, the time-of-day greeting, the hover-widening rail, and the bottom bar on narrow screens (a navigation drawer replaces it).

---

## 4. Access: only what a role may use, failing closed

**Status: built** (4 October, `remaining-work.md` R-33 Phase 0) and **unchanged by this plan**, except for the module names and the `/approvals` address. The subsection numbers are the 4 October ones, which code comments cite.

### 4.1 The role matrix, by module

"—" means absent: no nav row, no route, no button, no search result, no shortcut.

| Module / surface | RM | Compliance | Admin | Developer | API user |
|---|---|---|---|---|---|
| **Home** (`/`) | RM cards | Compliance cards | Admin cards | Read-only cards | **No workspace** page |
| **Companies** list and **Pipeline** (`/companies`, `/pipeline`) | ✓ | ✓ | ✓ | read, masked | — |
| New company, import companies | ✓ | ✓ | ✓ | — | — |
| RXIL intake | — | — | ✓ | — | — |
| **Company record**: details, qualification, activity, deals, documents, history | ✓ act | ✓ act | ✓ act | read | — |
| Company record: **Background check** tab | ✓ read; start; answer more-info | ✓ decide, propose, approve | ✓ decide, propose, approve | — (the tab does not exist) | — |
| Screening decisions, verification results and reviews, Re-KYC cycles | — | ✓ | ✓ | — | — |
| GST branch: add, deactivate | ✓ | ✓ | ✓ | — | — |
| GST branch: flag, unflag | — | ✓ | ✓ | — | — |
| Bring a buyer-only company into the pipeline | ✓ | ✓ | ✓ | — | — |
| **Deal record** (`/deals/:id`) | ✓ act | ✓ act | ✓ act | read; no stage moves, no handover reason | — |
| Parties' compliance on the deal | ✓ | ✓ | ✓ | — | — |
| Trade history: read / record outcome | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | read / — | — |
| **Follow-ups** (`/follow-ups`) | ✓ complete | ✓ complete | ✓ complete | read | — |
| **Approvals** (`/approvals`; `/review` redirects) | — | ✓ | ✓ | — | — |
| Re-KYC due list | ✓ read | ✓ | ✓ | — | — |
| **Settings → My profile, sessions** | ✓ | ✓ | ✓ | ✓ | ✓ |
| Settings → Users / Roles | by permission | by permission | by permission (default ✓) | by permission | by permission |
| Settings → Qualification criteria, Required documents | — | — | ✓ | — | — |
| Reveal identifiers | — | ✓ | ✓ | — | — |
| Search a company by full PAN/GSTIN/IEC | — (name only) | ✓ | ✓ | — (name only) | — |

Two deliberate choices:

- **Criteria and required documents are readable by every CRM role at the API**, but the settings screens are **Admin only**. Other roles see the criteria inside a company's qualification, and the required categories in the deal's handover checklist.
- **The RM sees the Background check tab.** The RM may start a check and answer "more info", and the handover checklist depends on it. The RM sees no decision, screening or verification controls, because the server's `allowed_moves` and `capabilities` leave them out.

### 4.2 One manifest, read by everything

- `src/platform/access/capabilities.ts` has an allowlist of capabilities per role. There is no default branch, so a role nobody listed has nothing.
- `src/routes/modules.ts` declares each module once: its path, its lazy screen, the capabilities it requires and its nav row.
- The router, the side navigation, the search's *Pages* group and the shortcut list are all generated from that table, so they cannot disagree.
- **This plan changes only the table's labels and icons.** It also adds `/approvals` and the *Pipeline* nav row, and drops the per-module `g` shortcut keys.

### 4.3 The failure modes, all closed

| Situation | What renders |
|---|---|
| Role not in the manifest (a new backend role, a typo, `undefined`) | No capabilities: the **No workspace** page |
| `/auth/me` still loading | The shell's skeleton only |
| `/auth/me/permissions` loading or failed | No Users/Roles sections; role capabilities unaffected |
| URL for a module the role lacks | **The same Not found page as a URL that does not exist**: same component, same copy, same document title |
| Module code for a role that lacks it | Never downloaded (`React.lazy` sits inside the gate) |
| Data for a section the role lacks | Never requested (`enabled: can(cap)`) |
| The server says 403 anyway (manifest drift) | An inline "This isn't available" in that card. In development, `console.warn('[access drift]', …)` |
| A disabled control for something the role may never do | Not allowed: it is **absent**. Disabled means "allowed, but not right now" |

### 4.4 Guards in code, and what keeps them honest

- `<Gate requires={…}>` wraps every module route. `useCan(cap)` covers individual controls. Both are exported only from `@/platform/access`.
- A lint rule bans `role ===`, `role !==` and the old `is*Role` helpers outside `src/platform/access/**`.
- The matrix test (`src/routes/access.matrix.test.tsx`) checks every pair of 5 roles × every module: the nav row is present or absent, the route renders or shows Not found, no gated request fires, and no forbidden text appears. **Phase 1 changes what it compares.** The search *Pages* group and the shortcut list must equal the nav. The `g` keys go away.
- The drift check against the server's route table waits on ask A7 (§13).

### 4.5 The two layers, kept apart

1. **Module visibility** comes from the client manifest. It is coarse and by role: "does this role have this module at all?"
2. **Action availability** comes from the server, per record: "what may this user do to *this* company or deal *now*?"

The client never uses layer 1 to decide an action the server serves through layer 2.

---

## 5. Design language: standard enterprise

### 5.1 Principles

1. **Familiar before novel.** Every pattern on screen has a counterpart in Salesforce, Dynamics, HubSpot or Fiori (§18.3). A pattern without one needs a stated reason.
2. **Colour has two jobs.** The brand blue marks what you can act on: primary buttons, links, the selected nav item and the current path step. The status colours mark state. Nothing else is coloured.
3. **Status in words.** A badge always shows its label. Colour and icon support the label; they never replace it.
4. **One level of container.** White cards sit on a grey page. A card never holds another card; inside one, headings and dividers give the structure.
5. **Dense enough for daily work.** 14 px body text, 32 px controls, two-line list items. At 1366 × 768, a common office laptop, a record's header and its first card are visible without scrolling.
6. **Actions where enterprise users look for them.** A record's actions sit top-right of its header and a card's actions top-right of the card. There is one primary button per view.
7. **Calm motion.** Menus, popovers, dialogs and the side panel fade or slide in 150 ms. Nothing moves when data changes, except a toast.
8. **Honest states** (kept): shaped skeletons, errors in the server's words, "Prototype" labels, "200+".

**Never**: a display serif · monospace for ordinary values · cream or beige backgrounds · gradients, glass or backdrop blur · emoji · status shown only as a glyph or a colour · time-of-day greetings · single-letter or chorded navigation keys · cards inside cards · a data grid as the main view of anything · a long scrolling form · an invented name for a standard CRM thing.

### 5.2 Colour tokens

The mechanism stays: CSS variables holding RGB triplets, the Tailwind mapping, and `tokens.contrast.test.ts`. **Token names stay**, so screens do not churn. The values change, and one group (`accent`) is added.

**Neutrals**

| Token | Light | Dark | Use |
|---|---|---|---|
| `paper` | `#F3F3F3` | `#1B1B1B` | Page background |
| `surface` | `#FFFFFF` | `#242424` | Cards, record header, side panel body |
| `raised` | `#FFFFFF` | `#2C2C2C` | Menus, popovers, search results |
| `sunken` | `#F5F5F5` | `#2E2E2E` | Hover fill, wells, upcoming path steps |
| `line` | `#E0E0E0` | `#3A3A3A` | Card borders, dividers |
| `line-strong` | `#8A8A8A` | `#8F8F8F` | Input borders (3:1 on `surface`, WCAG 1.4.11) |
| `ink` | `#242424` | `#F0F0F0` | Primary text |
| `ink-2` | `#424242` | `#D6D6D6` | Secondary text |
| `ink-3` | `#616161` | `#ADADAD` | Labels, metadata (AA on `surface` and `paper`) |
| `ink-4` | `#8A8A8A` | `#7A7A7A` | Placeholders and decorative marks only |

**Accent (new): the brand colour, for actions only**

| Token | Light | Dark | Use |
|---|---|---|---|
| `accent` | `#0B5CAD` | `#75B2F0` | Links and accent text on `surface` |
| `accent-solid` | `#0B5CAD` | `#2266B8` | Primary button, current path step, selected nav bar (white text, ≥ 4.5:1) |
| `accent-solid-hover` | `#094C8F` | `#1D5AA3` | Hover and press on the above |
| `accent-tint` | `#E8F1FB` | `#172A40` | Selected nav row, completed path steps |

The blue is a placeholder until Aner's brand colour is confirmed (§17 Q1). When it is, only these four values change. The focus ring becomes 2 px `accent-solid` with a 2 px `surface` offset; it was ink.

**Status**: the five meanings and their contrast-tested values stay (`positive`, `negative`, `attention`, `progress`, each with `-tint` and `-solid`). The exception is `idle`, which moves from warm grey to neutral: text `ink-3`, tint `#F0F0F0` / `#2E2E2E`, solid `#8A8A8A` / `#7A7A7A`. The tests must pass for every changed value before it merges.

**Theme.** Light by default; the system preference no longer switches it. Dark stays available in the user menu and is kept at parity by the same tests. The reason is that a demo laptop set to dark mode should not demo in dark.

**Risk** (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) never relies on colour alone:

| Risk | Badge |
|---|---|
| Low | positive tint, "Low risk" |
| Medium | attention tint, "Medium risk" |
| High | negative tint with a negative outline, "High risk" |
| Critical | **solid negative, white text, warning icon**, "Critical risk". The only solid risk badge (PDF §3.3) |

### 5.3 Typography

One family, the operating system's UI font:

```
"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif
```

- **Why**: it is what Dynamics 365 and Microsoft 365 render in on Windows, the demo laptop runs Windows 11, and there is nothing to download. It has tabular figures and the `₹` sign. Today none of the three bundled faces has `₹`, so amounts already mix two fonts. On macOS it renders San Francisco.
- **If the TL wants one identical face on every machine**: IBM Plex Sans, self-hosted (open licence). Check `₹` before choosing it.
- Remove `@fontsource/instrument-serif`, `@fontsource-variable/instrument-sans` and `@fontsource-variable/jetbrains-mono`, along with the `preload-fonts` plugin in `vite.config.ts`.

| Role | Size / line height, weight |
|---|---|
| Page and record title | 20/28, 600 |
| Card title | 16/22, 600 |
| Body (default) | 14/20, 400 |
| Secondary | 13/18, 400 |
| Label, caption | 12/16, 400, `ink-3`, sentence case, above its value |
| Home counts | 24/32, 600 |

- **Identifiers** (PAN, GSTIN, IEC, CIN, deal and invoice references) use the UI font with tabular figures. No monospace.
- Numbers are tabular everywhere (`font-variant-numeric: tabular-nums` on `body`).
- No italics for display. No uppercase tracked labels.

### 5.4 Layout, space and density

- 4 px grid. Spacing scale: 4 · 8 · 12 · 16 · 24 · 32.
- App header 48 px. Side navigation 224 px; it collapses to 56 px by a button, and the choice is remembered per viewer.
- Page padding 24 px (16 px under 768 px). Record pages use the full width: a main column, plus a 360 px right column from 1280 px. Below that they are one column.
- **Card**: `surface`, 1 px `line` border, 4 px radius, no shadow, 16 px padding. The header row is 48 px, with the title and an optional count on the left and the actions on the right.
- Controls are 32 px tall (28 px compact inside cards). List items are 56 px (two lines). Badges are 20 px.
- Breakpoints to check: 1440, 1366, 1280, 1024, 768, 390.

### 5.5 Shape and depth

- Radius: 4 px for controls, badges and cards; 8 px for dialogs, the side panel and menus. Only avatars and status dots are round, so there are no pill buttons.
- Resting surfaces have a border and no shadow. Floating layers (menus, popovers, search results, dialogs, side panel) share one shadow: `0 4px 16px rgb(0 0 0 / 0.14)` (dark: `/ 0.5`).

### 5.6 Motion

- 100 ms for hover and press. 150 ms fade or slide for menus, popovers, dialogs and the side panel.
- Removed: page view transitions, the lamp travel and the list settle (`lib/viewTransition.ts`, `lib/motion.ts`).
- Under `prefers-reduced-motion`, all of it is instant.

### 5.7 Voice and copy

- **Standard CRM nouns** (§18.1): Home, Companies, Pipeline, Follow-ups, Approvals, Details, Activity, Deals, Documents, History.
- **Buttons are a verb and an object**: "New company", "Log a call", "Open deal", "Hand over", "Approve". Never "Submit" or "Proceed".
- Sentence case everywhere. The number comes before the noun: "3 overdue".
- **A refusal is shown in the server's words**, introduced by what was tried: "Couldn't hand over: the seller's background check is not clear."
- "RM", never "Operations". "Aner Labs" as the company and "Exporter CRM" as the product.
- **Empty states are one plain line**, plus one action if the role may act: "No follow-ups due." Use no illustrations, taglines, greetings or exclamation marks.
- **Not found**: "Page not found. The page you asked for doesn't exist." plus *Go to Home*. It is identical for a forbidden module (§4.3).

### 5.8 Brand and icons

- **Brand**: the "Aner Labs" wordmark (16/600, `ink`) with "Exporter CRM" in `ink-3` beside it, the way Salesforce and Dynamics name the app in the header. The favicon is a white "A" on an `accent-solid` square. Both are placeholders until a logo exists (§17 Q1).
- **Icons**: **Fluent UI System Icons**, regular, 20 px (MIT licence, Microsoft), the set Dynamics and Microsoft 365 use. Screens name icons by meaning through the existing `Icon` map, and `scripts/build-icons.mjs` copies only the glyphs used. The swap is the map plus the script, and Phosphor is removed.

---

## 6. Components

These are the parts the screens are built from. Generic ones live in `src/components/ui`, CRM ones in `modules/onboarding/components`. Each one gets a style-guide entry and tests for every state, including what Developer does not see.

### 6.1 App header

48 px, `surface`, a bottom border. From left to right:

- the wordmark (links Home);
- search (§7.5);
- **+ New ▾** (only when the role has a create capability): *New company*, *Import companies*, and *RXIL intake* for Admin;
- the user menu: name, role label, theme (Light / Dark), *My profile*, *Sign out*.

### 6.2 Side navigation

- Labelled rows with an icon. *Settings* sits at the foot, then a *Collapse* button.
- The selected row has an `accent-tint` fill, a 3 px `accent-solid` bar on the left and `accent` text.
- Collapsed, it shows 56 px of icons with tooltips. Under 1024 px it is hidden behind a menu button in the header and opens as a drawer.

### 6.3 Page header and record header

**Page header** (list pages): breadcrumbs, the title, and the page's actions on the right.

**Record header** works like the Salesforce highlights panel or the Dynamics form header: what the record is, its key fields, and its actions.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Company                                                                              │
│ Bharat Precision Metals                            [Log a call] [Open deal] [More ▾] │
│ Precision engineering · Mumbai, India · RM R. Mehta                                  │
│ ──────────────────────────────────────────────────────────────────────────────────── │
│ Journey      Qualification   Conversation   Background check                         │
│ Customer     Qualified       Ready now      Clear · Low risk                         │
│                                             until 3 Oct 2027                         │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ( ✓ Lead )>( ✓ Prospect )>(  Customer  )      Customer since 3 Oct 2026              │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- The object type ("Company", "Deal") sits in 12 px `ink-3` above a 20/28 title, with one metadata line under it.
- **Key fields**: up to six, label above value. Statuses are badges (§6.4). For Developer the Background check field is absent, not greyed. Key fields are **state**, not identifiers: PAN and GSTIN are not in the header (PAN is on the Company panel, the GSTINs in *GST registrations*, each with its branch state), and the Background check field is the badge alone (the cycle is on its tab).
- **Actions**: built **only** from served fields. At most three buttons show, the first primary; the rest go under *More ▾*. When nothing applies, there are no buttons. Developer gets none.
- Under the header, the **Path** (§6.5).
- **On scroll** the header compresses to a sticky bar with the title, the badges and the actions (the Fiori dynamic page header behaves the same way).

### 6.4 Status badge

- 20 px tall, 4 px radius, a tint background, text in the meaning's colour, and a leading 6 px dot in its solid colour.
- **Tones**: positive, negative, attention, progress, neutral.
- **Two special forms**: *outline* for "Awaiting approval" (nothing has happened yet, so it has no fill), and *solid* for Critical risk only.
- The wording for every gauge is in §18.2.
- It replaces `Tag` as a status display, `Lamp`, `Standing`, and the chip components (`JourneyChip`, `QualificationChip`, `MarkerBadge`, `DealStageChip`, `VerificationStatusChip`, `ScanStatusBadge`, `RiskChip`, `TradeOutcomeChip`, `ComplianceCheckChip`). Their label maps stay, so the wording and the tests that assert it carry over.

### 6.5 Path

These are chevron steps, as in Salesforce Path and the Dynamics business process flow:

- **completed** steps: `accent-tint` with a check;
- **current**: `accent-solid` with white text;
- **upcoming**: `sunken`;
- one guidance line beside the path for the current stage (for example "Qualify the company to move it to Prospect."), except on the **Journey** path, which has none: nothing on it is a manual move, and the qualification and background-check key fields beside it already say what it waits on.

It has three uses:

| Path | Steps | Clickable? |
|---|---|---|
| **Journey** (record header) | Lead → Prospect → Customer | **Never**: the journey is never moved by hand. A buyer-only company shows an "Outside pipeline" badge instead of a path |
| **Conversation** (Activity tab) | Not contacted → Reaching out → Spoke to them → Interested → Ready now | A step is clickable **only if** the server lists that move (`GET …/conversation/moves`). Clicking selects it and shows *Mark as current*, as Salesforce Path does. *Not now* is a button beside the path that opens a date popover (not in the past). *Ready now* offers *Open deal* |
| **Deal stage** (deal header) | Open → Gathering paperwork → Handed over | Never. Moves are header buttons from `allowed_stage_moves`. A withdrawn deal shows a "Withdrawn" badge instead of the path |

The guidance line is fixed text per stage. It names what moves a stage on and never offers a move the server did not list.

### 6.6 Card and related-list card

- **Card**: a header row (title, count, actions), a body, and an optional footer link.
- **Related-list card** (the record's right column): up to three items, as Salesforce shows in a narrow column. The footer *View all* opens the matching tab. *+ Add* sits in the header when the role may add.

### 6.7 Record list item: the list without a table

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Bharat Precision Metals                          Customer  Qualified  Clear · Low risk│
│ Precision engineering · IN · RM R. Mehta                                             │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Coastal Seafood Exports                          Prospect  Qualified  Flagged        │
│ Seafood · IN · RM S. Rao                                                             │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- Two lines. The title is a link (14/600); under it is one line of key facts (13 px, `ink-2`). The badges sit on the right.
- The whole row is the link. It gets a `sunken` hover fill and sits in normal tab order.
- There are no column headers and no sortable grid. Filtering and order come from the list's own controls, on the server (as Fiori's object list item and Salesforce's split-view list work).
- One component serves companies, deals, users, follow-ups and approvals. The facts line and badges differ per use.
- A **company** row's facts line is industry · country · RM. It carries no identifiers: PAN and GSTIN are looked up on a company already found (*Search by identifier*), and masked values on every row read as a string of dots. The company record shows them all.

### 6.8 Activity timeline and composer

As in the Salesforce activity timeline and the Dynamics timeline:

- **Composer** at the top, with tabs *Call · Meeting · Email · Note · Task · Follow-up*. Each tab has a subject, an optional body, and a due date for a follow-up. Staff only.
- **Upcoming**: open follow-ups by due date. **Past activity**: entries grouped by month, each with an icon, title, who and when, and expandable.
- Today's paging stays: 8 per page, then *Show earlier*.

### 6.9 Side panel

The quick-create and quick-action surface, as in Dynamics quick create and HubSpot's create panel:

- A right-hand panel, 480 px wide (full width under 768 px), over a dimmed page.
- A header with the verb ("New company", "Record a decision") and a close button. The fewest fields possible. A footer with one primary button and *Cancel*.
- A 422 that names a field (`detail[].loc`) is shown on that field; anything else goes in the footer. Focus returns to the trigger on close.
- It replaces `Composer` and `FormPanel`. Their logic and variants stay (§9).

### 6.10 Inline edit field

- Label above value. A pencil appears on hover and focus, as in Salesforce inline edit.
- *Enter* saves and *Esc* cancels. The server's error appears under the field.
- Staff only; every other role sees plain text. This is the existing `Editable`, restyled.

### 6.11 Handover checklist

```
 Handover readiness                                                   4 of 6 met
 ✓ Seller is a customer
 ✓ Seller's background check is clear (until 3 Oct 2027)
 ✓ A buyer is recorded
 ✕ Buyer's AML is not passed                                          Go to buyer ›
 ✓ Invoicing branch recorded: Maharashtra
 ✕ Pre-shipment document missing                                      Upload ›
```

- **With ask A3** (structured conditions): one row per condition, with a link where the role may act.
- **Fallback (today)**: one attention message with `handover_blocked_reason` verbatim. The client never splits the server's sentence into rows.
- Developer gets neither, because the server gives Developer no reason (D8).

### 6.12 Pipeline board

- Three columns: **Lead**, **Prospect**, **Customer**, each with a capped count.
- **Cards** show the name; one facts line, industry · country · RM; the qualification and marker badges (and the background-check badge for staff, once A1 lands); and a **next-step line** worked out from the row alone, with no request per card: a lead not yet reviewed reads "Waiting on a qualification decision" (attention colour), a lead judged not qualified "Not qualified — stays a lead", a prospect "Needs a clear background check", a paused or ended company its marker and reason. A customer has none (the column note says it once).
- The **Lead** column header counts "N waiting on you" (the unreviewed leads on the page in hand) for OPERATIONS only, through the `queue.qualification` capability: COMPLIANCE and ADMIN may record a decision too, but it is not their queue. It is never used to gate a request.
- Each column scrolls past 34rem, so one long stage does not run the page down past the other two.
- **No drag.** The column header says what moves a company on.

### 6.13 Split view

A list of record list items on the left (360 px) and the selected record on the right, as in Salesforce split view and Fiori list-detail. The selection is kept in the URL, so a link opens the same item. Used by Approvals (§8.8).

### 6.14 Identifier

It renders in the UI font with tabular figures, one step down the type scale (`text-caption`) and never wrapped — an identifier split over two lines reads as two fragments. The eye shows only for `identifiers.reveal`, and **starts closed**: a role that may reveal is sent the value in full but reads it covered (last four showing) until it opens the eye, and *Copy* appears only once revealed. A masked role gets no eye and no copy (§3.1). Every PAN, CIN, IEC, registration number and GSTIN on screen goes through `Identifier` — a GSTIN carries the PAN, so leaving it bare would undo the PAN's cover. A picker option, which cannot hold an eye, always shows the covered form.

### 6.15 Other primitives

- **Button**: primary (`accent-solid`), secondary (white with a `line-strong` border), subtle (text only) and destructive (`negative-solid`), at 32 or 28 px.
- **Inputs**: `Segmented`, `Select`, `DatePopover`.
- **Overlays and feedback**: `Dialog` (confirmations), `Toast` (sonner).
- **Navigation and structure**: `Tabs` (underlined, with an `accent-solid` bar under the selected tab), `Breadcrumbs`, `Avatar` (initials).
- **States**: `Skeleton`, `EmptyState` (one line, one action), `InlineError`.

---

## 7. Shell, navigation and search

### 7.1 The shell

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Aner Labs  Exporter CRM     [ Search companies and pages…   Ctrl K ]   [+ New ▾]  RM ◯ │
├───────────────┬──────────────────────────────────────────────────────────────────────┤
│ ⌂ Home        │ Companies › Bharat Precision Metals                                  │
│ ▦ Companies   │ ┌ record header ───────────────────────────────────────────────────┐ │
│ ▥ Pipeline    │ └──────────────────────────────────────────────────────────────────┘ │
│ ☑ Follow-ups  │ Details  Qualification  Activity  Deals  Documents  Background  History│
│ ⚖ Approvals   │ ┌ tab content ─────────────────────────────┐ ┌ related cards ──────┐ │
│               │ │                                          │ │                     │ │
│               │ └──────────────────────────────────────────┘ └─────────────────────┘ │
│ ⚙ Settings    │                                                                      │
│ « Collapse    │                                                                      │
└───────────────┴──────────────────────────────────────────────────────────────────────┘
```

### 7.2 App header

As §6.1. It replaces `ContextBar`. The breadcrumbs move into each page's header, because that is where enterprise apps put them.

### 7.3 Navigation per role

| Nav row | RM | Compliance | Admin | Developer | API user |
|---|---|---|---|---|---|
| Home | ✓ | ✓ | ✓ | ✓ | (no shell) |
| Companies | ✓ | ✓ | ✓ | ✓ | |
| Pipeline | ✓ | ✓ | ✓ | ✓ | |
| Follow-ups | ✓ | ✓ | ✓ | ✓ | |
| Approvals | | ✓ | ✓ | | |
| Settings (foot) | ✓ | ✓ | ✓ | ✓ | |

- **Pipeline gets its row back.** The UI before the redesign had it, and it is the word people use in the demo. It links to `/pipeline`, which keeps redirecting to `/companies?view=board`. On that view the nav marks *Pipeline* as current, not *Companies*. The Companies page keeps a *List | Pipeline* switch.
- Settings shows only the sections the role has (§8.9).

### 7.4 URLs

Every current URL keeps working. There is one new address, `/approvals`, and `/review` redirects to it, the way `/pipeline` redirects today. The `/settings/*` sections, the `?tab=` keys and the list filters in the URL (`?journey=PROSPECT&q=…`) are unchanged.

### 7.5 Search and keyboard

**Search** is a field in the app header. Ctrl+K or `/` focuses it, and its results drop down in three groups:

- **Companies**: name, city and the journey badge. Name search works for every reader. Search by **full** PAN, GSTIN or IEC is only for `identifiers.reveal`. For a masked role, an identifier-shaped query sends nothing and shows the hint "To match a company by PAN, use New company" (unchanged rule).
- **Pages**: the role's modules, generated from the module table.
- **Recent**: the last eight companies opened, kept per viewer and cleared on sign-out.

Search shows **no actions**. Actions live on the record.

**Keyboard**: `/` and Ctrl+K go to search, Ctrl+/ lists the shortcuts (as in Salesforce), *Esc* closes a panel, menu or dialog, and Tab order is standard everywhere. **Removed**: the `g` chords, `j`/`k`, `c`, `l`, `a`/`x` and the `?` sheet. Shortcuts never fire inside inputs.

---

## 8. Screens

Each screen below gives its layout, what each role sees, and its fallbacks. Roles not mentioned see the screen as §4.1 says.

### 8.1 Sign in

- Two columns on white. Left: the wordmark at the top, then a 400 px form, "Sign in to Exporter CRM", "Use your work email and password.", email, password, *Sign in* (primary) and "No account yet, or locked out? Ask an administrator."; the copyright at the foot. Errors are inline.
- Right, from 1024 px: a pale accent panel with a looping illustration of a sales team at a meeting table, the headline "Every exporter, from first call to handover", and three lines with icons: *Companies and background checks*, *Deal pipeline*, *Approvals and handover*. Below 1024 px the panel is not shown and the animation is not fetched. From 1024 px the page is exactly the window's height and the picture shrinks to the room left, so the page never scrolls (checked down to a 520 px tall window).
- The illustration is "Business meeting in office" by Abdul Latif (LottieFiles, Lottie Simple License: commercial use, no attribution required), played by lottie-web's SVG-only build. The player and the file load only once the panel shows, outside the main bundle. It is decorative (`aria-hidden`), and under `prefers-reduced-motion` it shows one still frame.
- It is always light. (Changed 6 October at the user's request: the earlier plain centred card read as too bare.)

### 8.2 Home

The title is "Home". A two-column grid of cards from 1280 px, one column below. Every card is hidden, not empty, when the role lacks it or its backend ask has not landed.

```
 Home
 ┌ My follow-ups                    Mine | Team ┐ ┌ Pipeline                               ┐
 │ ⚑ Overdue 2d  Call back about statements    │ │   48          21           9          │
 │               Aarav Textiles   [Mark done]  │ │   Leads       Prospects    Customers   │
 │ ⚑ Overdue 1d  Send revised term sheet       │ │                         View pipeline ›│
 │               Coastal Seafood  [Mark done]  │ └────────────────────────────────────────┘
 │ ◷ Tomorrow    Site visit · Bharat Precision │ ┌ Re-KYC due                             ┐
 │                           View all (7) ›    │ │ Bharat Precision    expires 12 Oct     │
 └─────────────────────────────────────────────┘ │ Compliance starts the check            │
 ┌ Check back on                               ┐ └────────────────────────────────────────┘
 │ Deccan Spices     due today  Open activity ›│ ┌ Recent companies                       ┐
 └─────────────────────────────────────────────┘ └────────────────────────────────────────┘
```

| Card | RM | Compliance | Admin | Developer | Source |
|---|---|---|---|---|---|
| **Items to approve**: proposal, company, proposer and time, *Approve* / *Reject* (both confirm), *View all* → Approvals | | 1st | 1st | | `GET /background-check/proposals?status=open` |
| **My follow-ups**: overdue and due within 7 days; *Mark done* opens a popover for the outcome; *Mine* / *Team* | ✓ | ✓ | ✓ | Team, read-only | `/follow-ups` |
| **Check back on**: companies parked at "Not now" whose date has come. It opens the company's Activity tab and has no *done* (the two-kinds rule) | ✓ | ✓ | ✓ | read | existing |
| **Pipeline**: three counts, each linking to the filtered list ("200+" when capped) | ✓ | ✓ | ✓ | ✓ | company search |
| **Re-KYC due**: read-only for RM; *Start Re-KYC* for Compliance | read | ✓ | ✓ | | `GET /background-check/due` |
| **Setup**: active criteria version, required document categories, users | | | ✓ | | settings APIs |
| **Recent companies** | ✓ | ✓ | ✓ | ✓ | per viewer |

- Developer sees a neutral bar first: "Read-only access. Identifiers are masked."
- API user gets the **No workspace** page (§8.10) and never reaches the shell.
- *In review* (ask A4) and *Deals in paperwork* (ask A5) cards appear only once their asks land.

### 8.3 Companies list and Pipeline

```
 Companies                                                                  [New company ▾]
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │ All · Leads 48 · Prospects 21 · Customers 9      Qualification ▾  Relationship ▾       │
 │ [ Search this list… ]                                                ☐ Outside pipeline│
 ├──────────────────────────────────────────────────────────────────────────────────────┤
 │ (record list items, §6.7)                                                              │
 ├──────────────────────────────────────────────────────────────────────────────────────┤
 │                                50 shown · Show more                                    │
 └──────────────────────────────────────────────────────────────────────────────────────┘
```

- **Filters**: the journey as tabs with capped counts; qualification and relationship as dropdown buttons; *Outside pipeline* as a checkbox. All filtering is on the server, and every filter lives in the URL.
- **Badges on each item**: journey, qualification, and marker when paused or ended. Conversation and background check join them once ask A1 lands (background check for staff only).
- **Prefetch** on hover and focus is kept; it is invisible.
- **New company ▾**: *New company*, *Import companies*, and *RXIL intake* for Admin, each gated by its capability.
- **Pipeline** view: §6.12. It is reached from the side navigation's *Pipeline* row (`/pipeline` → `/companies?view=board`), which is marked current while it is open. There is no in-page List/Pipeline switch: it offered the same two screens the navigation already does.
- **Identity completion** (`/companies/identity-completion`) is the same record list, with a "Missing: …" line on each company.

### 8.4 New company, import, RXIL intake

- **New company**: a side panel over the Companies list. `/companies/new` opens the list with the panel open.
  - Step 1 is one *Identifier* field. The kind (PAN, GSTIN, IEC, CIN) is detected and shown as a tag. Once a name and country are known, `POST /companies/match` answers: already in the CRM (with an *Open* link, identifiers masked per role), a possible duplicate, a conflict, or new.
  - Step 2 asks for the name, country and source, plus the registration number for a foreign company. The button is *Create lead*.
  - A duplicate PAN is refused in the server's words, with a link to the other company. After creating, the company record opens on *Details*.
- **Import companies**: a page with one card holding a drop zone. The preview shows the header and the first five lines as row items ("Row 2 · Lakshmi Polymers · IN"). The server's report comes back grouped as *Created*, *Warnings* and *Refused*, in its own words. The client re-implements none of the server's checks.
- **RXIL intake** (Admin): a paste box, a parsed preview card, then *Take in*.

### 8.5 Company record

```
 Companies › Bharat Precision Metals
 ┌ record header and journey path (§6.3) ──────────────────────────────────────────────┐
 └──────────────────────────────────────────────────────────────────────────────────────┘
 Details   Qualification   Activity   Deals   Documents   Background check   History
 ┌ tab content ─────────────────────────────────────┐ ┌ Open follow-ups (2)   View all ┐
 │                                                  │ │ Call back about statements ⚑2d │
 │                                                  │ └────────────────────────────────┘
 │                                                  │ ┌ Deals (2)             View all ┐
 │                                                  │ │ DL-0041 Rotterdam · Paperwork  │
 │                                                  │ └────────────────────────────────┘
 │                                                  │ ┌ Contacts (3)             + Add ┐
 │                                                  │ ┌ Documents (5)         View all ┐
 └──────────────────────────────────────────────────┘
```

**Header actions** come only from served fields. They replace the redesign's *Now* panel.

| Action | Shown when |
|---|---|
| Log a call | `crm.write` |
| Record qualification | `can_record_results` |
| Open deal | `can_open_deal` |
| Start background check | `allowed_moves` includes `IN_REVIEW` |
| Approve / Reject | `open_proposal.allowed_actions` |
| Pause / End / Resume (under *More*) | `allowed_marker_moves` |
| Bring into pipeline | buyer-only company, staff |

**Tabs.** The `?tab=` keys are unchanged; only the labels change.

| Tab | `?tab=` | Content |
|---|---|---|
| **Details** (default) | `overview` | *Company information* card: facts in two columns as inline-edit fields (staff), read-only text otherwise. *GST registrations* card: branch items with state, GSTIN, and Active / Flagged badges; *Add branch* (side panel); deactivate (staff); flag and unflag with a reason popover (`gst.flag`). A GSTIN another company holds shows the server's warning with a link. The identity gaps notice |
| **Qualification** | `qualification` | The server's suggestion as a banner. One item per criterion: *Pass / Fail / Unknown* (segmented), the observed value, and an evidence note (PASS and FAIL need evidence; the server says so). Changes collect into a sticky "Record 2 results" bar, and nothing is sent per keystroke. Outcome buttons are exactly `allowed_outcomes`; *Not qualified* opens the served reason codes. Earlier outcomes sit in a collapsed section |
| **Activity** | `conversation` | The conversation path (§6.5) and *Not now*, then the composer and timeline (§6.8). Contacts are in the right column |
| **Deals** | `deals` | *Selling* and *Buying* cards of deal items (reference, title, stage badge, counterparty). The *Trade* card: one item per relationship, with invoice counts by outcome as badges ("3 paid · 1 unpaid · 1 no outcome recorded"). Expanding one shows its invoices. Amounts stay in their currency and are **never totalled** (IQ-4). *Record a past invoice* (staff) |
| **Documents** | `documents` | Items grouped by category: name, type, size, who uploaded it and when, and a scan badge. *Quarantined* and *Scan failed* are never downloadable. Upload is a drop zone on the card plus a type select. "Prototype: pass-through scanner" is on the card, not on each file. *View document* (beside *Download*, same `is_downloadable` gate) shows a PDF, an image or plain text in a wide side panel, from a blob of the served bytes; *Download* in the panel saves those bytes. SVG, HTML and other types are download only: a blob URL runs with the CRM's origin, so an uploaded SVG or HTML file is never rendered |
| **Background check** | `background-check` | §8.5.1. Absent for Developer |
| **History** | `history` | Entries grouped by day. Rows that share a timestamp are one entry, labelled "same moment". A filter by area uses the existing `?dimension=`, and its options come from the dimensions actually sent. Read-only |

**Right column** (from 1280 px; below that it follows the tab content): *Open follow-ups*, *Deals*, *Contacts* (with *+ Add* as a side panel) and *Documents*, as related-list cards (§6.6). Developer sees no *Add*.

#### 8.5.1 Background check tab

```
 Background check · cycle 2 (Re-KYC, started 1 Oct)                         Cycle [2 ▾]
 ┌ Status ──────────────────────────────────────────────────────────────────────────────┐
 │ In review                              [Ask for more information]  [Propose decision ▾]│
 │ Required for Clear   KYB Passed · AML In review · Sanctions Not recorded               │
 │ Still needed         AML has no accepted review · Sanctions not recorded               │
 │ Awaiting approval    Clear · Low risk, proposed by R. Mehta at 11:02  [Approve][Reject]│
 └────────────────────────────────────────────────────────────────────────────────────────┘
 ┌ Screening  5 of 7 ┐   ┌ Verifications ┐   ┌ Bank activity ┐   ┌ Decisions ┐
```

- **Status card.** The moves are buttons from `allowed_moves`; there is no state-map diagram. Each opens the decision side panel. For *Clear* the panel ends on a summary step: "This Clear rests on: KYB passed, AML passed, Sanctions passed, 7 of 7 screened, 2 documents."
- **Required for Clear** comes from `required_checks`. **Still needed** is the server's `clear_blocked_reasons`.
- **Awaiting approval**: *Approve* and *Reject* for a different officer (`allowed_actions`), *Withdraw* for the proposer.
- **Screening**: one item per check, with *Pass / Fail / Exempt / Needs review* for Compliance. It is read-only for RM (`capabilities.can_record_decision`).
- **Verifications**: grouped by check type, with provenance badges (*Manual*, *Stub*, *Provider*; *Placeholder* stays prominent). *Record a result* and *Review* are side panels.
- **Bank activity**: one line, "No bank feed is connected.", with the Prototype label.
- **Decisions**: by cycle. Each one opens its evidence.
- `VerificationSection`, `ScreeningChecklist`, `DecisionHistory`, `ProposalHistory`, `AwaitingApproval` and `CheckCycleActions` keep their logic and tests. They are restyled, not rewritten.

### 8.6 Deal record

```
 Companies › Bharat Precision Metals › DL-2026-0041
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │ Deal · DL-2026-0041                                                                   │
 │ Rotterdam shipment                                      [Hand over] [Withdraw] [More ▾]│
 │ Bharat Precision Metals → Rotterdam Trading BV (NL)                                   │
 │ Stage                Invoicing branch     Opened                                      │
 │ Gathering paperwork  Maharashtra          2 Oct 2026 by R. Mehta                      │
 ├──────────────────────────────────────────────────────────────────────────────────────┤
 │ ( ✓ Open )>(  Gathering paperwork  )>( Handed over )                                  │
 └──────────────────────────────────────────────────────────────────────────────────────┘
 ┌ Handover readiness (§6.11) ─────────────────────┐  ┌ History ────────────────────────┐
 ┌ Seller ─────────────────┐ ┌ Buyer ─────────────┐ │  │ 16:41 Buyer recorded            │
 ┌ Documents (required categories marked) ────────┐ │  │ 16:40 Open → Gathering paperwork│
 ┌ Trade between these two ───────────────────────┐ │  └─────────────────────────────────┘
 ┌ Handover record (after handover, read-only) ───┐
```

- **Stage moves** are header buttons from `allowed_stage_moves`. *Hand over* is the primary button and keeps its confirmation ("This cannot be undone…"). *Withdraw* opens a reason side panel. *Record outcome* (after handover, staff) is a side panel.
- **Developer** gets no buttons and no readiness reason. The page reads as a record.
- **Seller card**: status badges, and the *Invoicing branch* select (staff, `PUT /deals/{id}/invoicing-branch`).
- **Buyer card**: *Choose buyer* opens a side panel with the identifier lookup (match or create, set once). A legacy buyer shows a collapsed "Legacy buyer record" section with `BuyerChecks`.
- **Documents**: grouped by category. The required categories (from `/settings/deal-required-documents`) are marked *Present* or *Missing*.
- **Handover record**: a read-only card with a "Read-only" badge and the server's words ("taken at the handover" or "reconstructed").

### 8.7 Follow-ups

- The title is "Follow-ups", with a *Mine | Team* switch.
- Cards for **Overdue**, **Today**, **This week**, **Later** and **Done (last 14 days)**, each a list of task items: due date, subject, company and owner, with a *Mark done* button. The button opens a popover for the outcome; it is staff only, and Developer reads.
- **Check back on** is its own card, in the right column from 1280 px. It has no *done* action.
- `state` and `is_overdue` come from the server and are never computed. The `OVERDUE / OUTSTANDING / DONE` filters map onto the cards.

### 8.8 Approvals (Compliance, Admin)

A split view (§6.13).

- **Left list**: *Awaiting your approval* (open proposals), *Re-KYC due*, and *In review* once ask A4 lands.
- **Right side**: the selected company's Background check tab (the same component as the company record, so the two never differ), with *Approve* and *Reject* in its status card. Both confirm in a dialog.
- **Sources**: `GET /background-check/proposals?status=open` (`compliance.queue`) and `GET /background-check/due`.
- For RM and Developer the module does not exist (§4.1).

### 8.9 Settings

A settings page with its own left list. It shows only the sections the role has.

- **My profile** (everyone): a details card with inline edit; *Change password* (side panel, with the existing strength meter); *Sessions* as device items, each with *Sign out*.
- **Users** (`settings.users`): people as record list items (initials avatar, name, email, role badge, Active / Inactive), with search and a role filter. *New user* and *Reset password* are side panels.
- **Roles** (`settings.roles`): roles as list items. Opening one shows its **permission matrix**, an editor of toggles grouped by module. It is the one grid in the app, because it is an editor, not a data view. Built-in roles carry a badge. CRM permissions the catalogue marks "not enforced" say so in place.
- **Qualification criteria** (Admin): one card per criterion (label, rule, required, active), with its version history collapsed. *New version* is a side panel pre-filled from the current version.
- **Required documents** (Admin): the categories as a checklist of toggles, with the change history below. A 409 `DEAL_REQUIRED_DOCUMENT_CHANGED` reads "Someone changed this. Here is the current rule."

### 8.10 Not found, no workspace, errors, loading

- **Not found**: "Page not found." plus *Go to Home*. It is identical for forbidden modules (§4.3).
- **No workspace** (API user, unknown role): the wordmark, then "Your account doesn't have access to a workspace yet. Ask an administrator.", *My profile* and *Sign out*. No navigation, no CRM words, no counts.
- **Errors**: inline in the card that failed, with the server's message and *Try again*. Each tab and card has its own error boundary, so one failure never blanks the page.
- **Loading**: skeletons shaped like the card, never a page-centre spinner. Buttons show their own pending state.

---

## 9. No generic forms: the replacement for each one

Validation keeps Zod at the edge and treats the server's errors as the authority.

| Form today | Becomes | Enterprise counterpart |
|---|---|---|
| Sign in | Form beside an illustrated product panel, two fields | Standard (Salesforce, HubSpot sign-in pages) |
| New company (`AddExporterPage`) | Side panel: identifier lookup, then name, country, source | Dynamics quick create with duplicate detection |
| Import companies | Drop zone, preview, grouped report | Data import wizards |
| RXIL intake | Paste box, parsed preview card, *Take in* | — |
| Company facts (`CompanyPanel`) | Inline edit fields | Salesforce inline edit |
| GST branch add / flag | *Add branch* side panel; flag reason popover | Quick action |
| Pause / End (`MarkerControl`) | *More ▾*, then a reason dialog | Record action menu |
| Qualification results and outcome | Criterion items with segmented results and a sticky record bar | Path key fields |
| Conversation status | Conversation path with *Mark as current*; *Not now* date popover | Salesforce Path |
| Contact | *+ Add* on the Contacts card, opening a side panel | HubSpot / Dynamics quick create |
| Activity | Timeline composer | Salesforce activity composer |
| Open deal | Popover: reference, then *Open* | Quick action |
| Choose buyer | Side panel with the identifier lookup | Lookup with create |
| Withdraw deal / Record outcome | Side panels | Quick action |
| Background-check move | Side panel from the status card | Quick action |
| Approve / reject a proposal | Confirm dialog | Approve / Reject on the approval request |
| Verification result / review | Side panels | Quick action |
| Screening item | Segmented choice in the item | — |
| Start Re-KYC / Re-KYB | Popover with a reason | Quick action |
| Complete a follow-up | *Mark done* popover | Task completion |
| Criteria version | Side panel, pre-filled | — |
| Required documents | Toggles | Settings toggles |
| User / role / reset password | Side panels | Admin quick create |
| My profile | Inline edit and a password side panel | — |

---

## 10. No table views: the replacement for each one

| List | Becomes |
|---|---|
| Companies | Record list items (§6.7), plus the Pipeline board (§6.12) |
| Identity completion | Record list items with a "Missing: …" line |
| Qualification results | Criterion items (§8.5) |
| Qualification criteria | Criterion cards with their version history |
| Required documents | Category checklist and history |
| Import preview and report | Row items grouped by created, warning and refused |
| Users | People list items |
| Roles | Role list items; the permission matrix is the one editor grid |
| Follow-ups | Task items grouped by due date |
| Approvals | Split view |
| History | Timeline grouped by day |
| A company's deals | Deal list items |
| Documents | Items grouped by category |
| Screening and verifications | Items grouped by check |
| Trade invoices | Invoice items with outcome badges; amounts in their own currency, never totalled |

---

## 11. Accessibility

- **WCAG 2.2 AA** in both themes, proved by `tokens.contrast.test.ts`. It gains input borders (3:1) and the accent pairs.
- **Never colour alone**: every badge has its words, and the Critical risk badge has an icon.
- **Focus**: a 2 px `accent-solid` ring with a 2 px offset on everything focusable. Focus returns to the trigger when a side panel, dialog or popover closes.
- **Keyboard**: every action can be reached by Tab and Enter. The shortcut list (Ctrl+/) shows only the role's keys.
- **Live regions** announce async results ("Decision recorded", "Couldn't hand over: …").
- **Reduced motion** turns every transition off.
- **Tests**: axe on Home (per role), the companies list, each company tab, the deal record, Follow-ups, Approvals and Settings, in both themes.

---

## 12. Engineering

### 12.1 What changes in code

| Area | Files | Change |
|---|---|---|
| Tokens | `src/design/tokens.css`, `tailwind.config.ts`, `lib/cn.ts` | New values (§5.2) and the `accent` group; the font family and type scale (§5.3); remove the `display-*` sizes and the `font-display` and `font-mono` families; update the type scale `tailwind-merge` knows |
| Fonts | `main.tsx`, `vite.config.ts`, `package.json` | Remove the three `@fontsource` imports and dependencies and the `preload-fonts` plugin |
| Icons | `scripts/build-icons.mjs`, `src/design/icon-paths.ts`, `icons.ts`, `icon-names.ts` | Fluent regular 20 in place of Phosphor |
| Primitives | `components/ui/*` | `Button` (accent); `Tag` → `Badge`; `Composer` → `SidePanel`; `Tabs` (underlined); `Card` (header row); `Editable` (pencil); `NotFound` copy; new `Path`, `RecordHeader`, `RecordListItem`, `Breadcrumbs` |
| Shell | `layout/*` | `Rail` → `SideNav`; `ContextBar` and `AvatarMenu` → `AppHeader` (search, *+ New*, user menu); `CommandBar` / `CommandBody` → the header search; `Shortcuts` / `useGlobalShortcuts` → `/`, Ctrl+K, Ctrl+/; `BottomBar` → nav drawer |
| Module table | `routes/modules.ts`, `platform/shell/keys.ts` | Labels (Home, Companies, Pipeline, Follow-ups, Approvals), icons, `/approvals` with `/review` redirecting, the Pipeline nav row; remove the `shortcut` keys |
| CRM parts | `modules/onboarding/components/standing/*` | `Standing` → `RecordHeader` fields and `StatusBadge`; `Lamp` and `lamps.ts` deleted (wording stays in the label maps); `GaugeTrack` → `Path` (conversation); `StageRoute` → `Path` (deal); `CheckRunway` → the status card's buttons; `Preflight` → `HandoverChecklist`; `Shelf` → grouped document list; `SmartEntry` → `IdentifierLookup`; `PartyCard` kept as the seller and buyer cards |
| Motion | `lib/viewTransition.ts`, `lib/motion.ts`, `design/motion.test.ts` | Removed; the reduced-motion test stays for the remaining fades |
| Theme | `platform/theme/theme.ts` | Default `light` |
| Pages | every page | Re-laid out per §8, with their tests updated in the same change |

**Not touched**: `platform/access`, `lib/api`, the hooks, `paths.ts`, session handling, and the server-driven logic inside components.

**Renames**: a component is renamed when its screen is reworked, in the same change, never in a separate sweep. Names describe behaviour, and no plan or task IDs go into code, comments or tests.

### 12.2 Dependencies

| Add | Why |
|---|---|
| `@fluentui/svg-icons` (dev only) | The build script copies the glyphs used into `icon-paths.ts` |

| Remove | When |
|---|---|
| `@fontsource/instrument-serif`, `@fontsource-variable/instrument-sans`, `@fontsource-variable/jetbrains-mono` | Phase 1 |
| `@phosphor-icons/react` (dev) | Phase 1, once the icon map is switched |

Radix, cmdk (it backs the search results list), sonner, React Hook Form and Zod stay.

### 12.3 Performance

- Route-level splitting and *prefetch on intent* stay.
- Dropping the fonts takes the font files off the first load.
- Budget: initial JS ≤ 250 kB gzip on Home (146 kB at the last measure, 5 October).
- No optimistic state for anything the server decides. A new activity in the timeline is the one optimistic case, rolled back on error.

### 12.4 The style guide is the TL's review page

`/__design` is mounted only in development, so it is not in the production bundle. Phase 1 rebuilds it to show:

- the tokens in light and dark;
- every badge for every gauge (§18.2);
- the path in its three uses;
- a record header seen as each role (the existing "Seen as" switch);
- a record list item, a related-list card, the side panel, the timeline and the checklist.

The TL signs off on this page and on one real screen before Phase 2 starts.

### 12.5 Section references in code

94 files under `frontend/src` cite `frontend-plan §…`. References to §4 stay valid. References to §5–§8 point at the 4 October version (`a77725d`). Each one is rewritten when its file is touched in Phases 1–3. Phase 3 greps for any left over.

---

## 13. Backend asks

None of these blocks a phase. Each unlocks a fuller screen, and until it lands the fallback ships. Status is from `remaining-work.md` (R-46, D-19).

| # | Ask | Unlocks | Fallback until then | Status |
|---|---|---|---|---|
| A1 | Company list items carry `conversation`, `conversation_check_back_on`, and for staff only `background_check`, `awaiting_approval`, `rekyc_due` (omitted for Developer, D8) | All four badges on list items, pipeline cards and search results | Journey, qualification and marker badges only | To build (R-46) |
| A2 | `total` on company search | Exact counts on Home, the list and the board | "200+" / "50 shown" | Not scheduled |
| A3 | Structured `handover_conditions: [{key, met, message}]` beside `handover_blocked_reason` | The handover checklist with links (§6.11) | The server's sentence in one message | To build (R-46) |
| A4 | `background_check` filter on company search (staff only) | *In review* on Home and in Approvals | Card hidden | To build (R-46) |
| A5 | Cross-company `GET /deals?stage=…` | *Deals in paperwork* on Home | Card hidden | Deferred (D-19) |
| A6 | `relationship_manager_user_id` written, plus a filter on it | A *My companies* list view; RM avatars | RM shown as text | Deferred (D-19) |
| A7 | The gated-route table exported as JSON, guarded like `openapi.json` | The automated drift check of the access manifest (§4.4) | Manual check in review | To build (R-46) |
| A8 | `dry_run=true` on `POST /imports/companies` | A server-checked import preview | Header and first lines previewed client-side | Deferred (D-19) |
| A9 | Criteria versions carry `created_by_name` | Names instead of ids in the criteria history | The id, labelled "user id" | R-36 |

---

## 14. Delivery phases

**Gates for every phase**: `npx tsc -b --noEmit` · `npx eslint .` (0 errors) · `npx vitest run` (no test removed without its replacement) · `npx vite build`. Do not run prettier over existing files: there is no prettier config, and the repo is hand-formatted (single quotes, about 100 columns).

**Already done**: Phase 0, access (4 October). The "Ink & Paper" Phases 1–5 (5 October, PR #19) are superseded visually. Their structure is reused: lazy modules, the token mechanism, the shell registry, the primitives, and the component logic.

**Start point**: a branch from `main` after the current unstaged work on `main` is committed. Phase 1 touches most of `frontend/src`, so starting on top of open changes would conflict.

### Phase 1: Look and shell

- Tokens (§5.2), the system font (§5.3), Fluent icons (§5.8), the wordmark, and light as the default theme.
- Primitives: `Button`, `Badge`, `Card`, `Tabs`, `SidePanel`, `Editable`, `Path`, `RecordHeader`, `RecordListItem`, `Breadcrumbs`.
- Shell: `AppHeader` with search and *+ New*, `SideNav`, the nav drawer, and the shortcut set (§7.5).
- On-screen names (§18.1), and the Not found, No workspace and sign-in copy.
- Removal of the motion extras (§5.6).
- The style guide rebuilt (§12.4).
- **Done when**:
  - every screen renders in the new look with no behaviour change;
  - no `font-display`, `font-mono` or glyph lamp remains on screen;
  - the matrix test is green against the new nav and search;
  - axe is clean on the style guide in both themes;
  - **the TL has signed off the style guide and the company record header.**
- **Status (6 October): built**, unstaged on `feature/frontend-redesign`. Placeholder blue, Segoe UI, light by default (the open questions' recommended answers). Awaiting TL sign-off of `/__design` and the company record.

### Phase 2: The screens the demo walks

In this order, because each one reuses the one before it:

1. **Company record**: header, path, tabs, right column, and the Background check tab (§8.5).
2. **Deal record** (§8.6).
3. **Companies list and Pipeline** (§8.3), and *New company* as a side panel (§8.4).
4. **Home** for each role (§8.2).
5. **Follow-ups** (§8.7).
6. **Approvals** (§8.8).

- **Done when**: `demo.md` §3–§5 have been walked as RM, Compliance, Admin and Developer, in light, at 1366 × 768 and 1440 × 900, with no console error and no failed request. Each screen passes §15, and screenshots have gone to the TL.
- **Status (6 October): built**, all six screens. Every screen was walked headless as each role with no console error and no failed request; the formal `demo.md` §3–§5 walk and the screenshots for the TL are still to do.

### Phase 3: Remaining screens and clean-up

- Import, RXIL intake and identity completion (§8.4, §8.3), and the Settings sections (§8.9).
- Delete what is now unused: `Lamp`, `lamps.ts`, `Standing`, `CheckRunway`, `StageRoute`, `CommandBody`'s actions, `BottomBar`, `lib/motion.ts` and `lib/viewTransition.ts`.
- Renames left over from Phase 2. Section references to the old plan (§12.5).
- A full dark-theme pass.
- `demo.md` §2 screen names and the "Find…" wording updated.
- **Done when**: nothing imports a removed component, no code comment cites a removed section, and every role passes §15 in both themes.
- **Status (6 October): built.** Import, RXIL intake, identity completion and Settings restyled; *Qualification criteria* and *Required documents* sit inside the Settings frame (the side navigation shows only *Settings*); `lamps.ts`, `Lamp`, `DocumentList` and the motion helpers deleted; components renamed per §18.1 (`CheckStatus`, `HandoverChecklist`, `DocumentsByCategory`, `IdentifierLookup`, `ConversationPath`, `DealStagePath`, `CompanyBadges`, `ApprovalsPage`; folder `components/record`); section references and old names in comments updated; dark theme checked on the main screens; `demo.md` §2–§5 names updated.

---

## 15. Definition of done and QA

For every screen, before it merges:

- [ ] **Roles**: walked as RM, Compliance, Admin, Developer and API user. What shows matches §4.1, no forbidden request fires, and the matrix test covers it.
- [ ] **Server authority**: every action is rendered from a served list or capability; nothing is computed on the client; refusals use the server's words; `from_value` and 409 are handled where they apply.
- [ ] **Masking**: identifiers go only through `Identifier`, with no reveal or copy for masked roles.
- [ ] **States**: loading (shaped), empty (one line, plus one action if permitted), error (inline, with retry), and the Prototype labels present.
- [ ] **Look**: tokens only; no serif, no monospace, no glyph-only status; one primary button per view; no card inside a card; no shadow on a resting surface.
- [ ] **Names and copy**: §18.1 names; verbs on buttons; sentence case; "RM", not "Operations".
- [ ] **Both themes**: light and dark checked, axe clean.
- [ ] **Keyboard**: every action reachable, focus visible and returned.
- [ ] **Widths**: 1440, 1366, 1280, 1024, 768 and 390, with no horizontal page scroll.
- [ ] **Gates**: tsc, eslint, vitest and build all green.

---

## 16. Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| The TL dislikes the new look too | A third pass costs another week | The TL signs off the style guide and one real screen at the end of Phase 1, before any screen is re-laid out |
| The brand colour is not known | A placeholder blue might be "wrong" | It is four token values (§5.2); changing them later touches no screen |
| The system font differs between Windows and macOS | Screenshots differ by machine | Demo and screenshots on Windows. IBM Plex Sans is ready if one face is wanted (§5.3) |
| Tests assert the old names and copy ("Desk", "Agenda", "Review", "Nothing here.", "Find…") | Many test edits | Update them in the same change as the screen. The matrix test guards access throughout |
| Merge conflicts with work in progress on `main` | Phase 1 touches most files | Start from a clean `main` (§14). Phase 1 is mechanical and lands first, in one change |
| Without tables, lists are harder to scan | RMs compare many companies | Two-line items with right-aligned badges, journey tabs with counts, server-side filters in the URL |
| "Enterprise" drifts back into "generic" | The TL's original complaint | The *Never* list (§5.1), one brand colour, record pages built from named enterprise patterns (§18.3) |

---

## 17. Open questions

None blocks the start of Phase 1.

1. **Brand.** Does Aner have a brand colour and a logo? Until then, the placeholder blue (§5.2) and the wordmark (§5.8) are used.
2. **Demo date.** If the demo comes before Phase 2 finishes, Phase 2 is cut to the screens `demo.md` §4 walks: company record, deal record, companies list, and Home.
3. **The identifier eye for Compliance and Admin** (carried from 5 October). They read identifiers in full by decision, so the eye changes nothing for them. Should it be dropped, or should identifiers be masked until revealed?
4. **Theme.** Light by default, with dark in the user menu (§5.2). Agreed?

Answered earlier (D-20, still applies): a placeholder brand mark until a logo exists; a read-only home for Developer; Approvals in the Admin navigation.

---

## 18. Appendices

### 18.1 Names: on screen and in code

| 4 October (on screen) | New (on screen) | Code, when its screen is reworked |
|---|---|---|
| Desk | **Home** | `HomePage` (unchanged) |
| Companies (register) | **Companies** | `ExportersListPage` |
| Board | **Pipeline** | `PipelineView` |
| Agenda | **Follow-ups** | `FollowUpsPage` (unchanged) |
| Review | **Approvals** | `ApprovalsPage` |
| Dossier, chapters | **Company record**, **tabs** | `ExporterDetailPage` |
| Now | Header actions | `RecordHeader` |
| Profile | **Details** | `CompanyPanel` |
| Conversation | **Activity** | `ConversationPanel` |
| Deals & trade | **Deals** | `DealsPanel` |
| Ledger | **History** | `HistoryTimeline` (unchanged) |
| Standing, lamps | **Status badges** | `StatusBadge` |
| Gauge track | **Conversation path** | `Path` |
| Check runway | **Background check status** | status card in `BackgroundCheckPanel` |
| Pre-flight | **Handover readiness** | `HandoverChecklist` |
| Shelf | **Documents** | `DocumentList` |
| Party card | **Seller** / **Buyer** | `PartyCard` (unchanged) |
| Composer | **Side panel** | `SidePanel` |
| Smart entry | **Identifier lookup** | `IdentifierLookup` |
| Deal room | **Deal record** | `DealDetailPage` (unchanged) |
| Find… (⌘K) | **Search** | `HeaderSearch` |
| Rail, context bar | **Side navigation**, **app header** | `SideNav`, `AppHeader` |
| "Nothing here." | **Page not found** | `NotFound` (unchanged) |

### 18.2 Status wording per gauge

| Gauge | Neutral | Progress | Attention | Positive | Negative |
|---|---|---|---|---|---|
| Journey (path, not a badge) | Lead · Prospect · Customer; "Outside pipeline" badge (neutral) for a buyer-only company | | | | |
| Qualification | Not reviewed | — | — | Qualified | Not qualified |
| Conversation | Not contacted | Reaching out · Spoke to them · Interested | Not now · check back <date> | Ready now | — |
| Background check | Not started | In review | More info needed | Clear · <risk> · until <date> | Flagged · On hold |
| Background check, extra badges | "Awaiting approval" (outline) | | "Re-KYC due" | | |
| Marker | Ended (and the name greyed in lists) | | Paused | | |
| Deal stage | Withdrawn | Open · Gathering paperwork | | Handed over | |
| Document scan | | Scanning | | Clean | Quarantined · Scan failed |
| Trade outcome | Not known · No outcome recorded · Claimed (beside the status, never folded into it) | | Part paid · Unpaid | Paid | Disputed |
| Risk | | | Medium | Low | High; **Critical** (solid, icon) |

Exact strings come from the existing label maps (`background-check-labels.ts`, `verification-labels.ts` and the chip label maps), so tests that assert them keep passing.

### 18.3 Enterprise patterns this plan uses

| Pattern | Where it comes from | Used in |
|---|---|---|
| App header with app name, global search, quick create (+) and user menu | Dynamics 365 app header; Salesforce global header | §6.1, §7.2 |
| Labelled left navigation | Dynamics site map; HubSpot navigation | §6.2, §7.3 |
| Record header with key fields and actions | Salesforce highlights panel (up to seven compact-layout fields); Dynamics form header (four read-only fields); Fiori dynamic page header (key information and global actions) | §6.3 |
| Stage path with guidance | Salesforce Path (key fields and guidance per stage, *Mark as current stage*); Dynamics business process flow | §6.5 |
| Tabs, with the main task on the first one | Dynamics main form guidance ("Information that's necessary and is primary … should be on the first tab"); Fiori anchor bar or tabs | §8.5 |
| Related records as cards in a narrow right column, three items each | Salesforce related lists in a narrow region; HubSpot right sidebar; Dynamics reference panel | §6.6, §8.5 |
| Activity timeline with a composer | Salesforce activity timeline; Dynamics timeline control; HubSpot middle column | §6.8 |
| Lists as Kanban or split view, not only tables | Salesforce list views, displayed as Table, Kanban or Split View | §6.12, §6.13 |
| List and detail side by side | Fiori flexible column layout | §8.8 |
| Quick create in a side panel | Dynamics quick create forms; HubSpot create panel | §6.9 |
| Inline edit on record details | Salesforce inline edit | §6.10 |
| Items to approve on the home page | Salesforce "Items to Approve" home component | §8.2 |
| `/` to search, Ctrl+/ for the shortcut list | Salesforce Lightning keyboard shortcuts | §7.5 |
| Icon set | Fluent UI System Icons (Microsoft, MIT) | §5.8 |

### 18.4 Where each product rule comes from

| Rule | Source |
|---|---|
| Absent, never disabled, for what a role may not do | architecture §9 ("a disabled eye icon would still leak…") |
| The server decides moves; the screen asks | architecture §1, §4; PDF §2.6 |
| CRITICAL looks different | PDF §3.3 |
| The gauges shown side by side, never merged | PDF poster, "The same dashboard, three companies" |
| No drag on the journey | architecture §4 (the journey is never moved by hand) |
| Follow-ups and check-backs stay two kinds | `FollowUpsPage.tsx`; `engagement.md` |
| RM, not Operations; Aner Labs | plan.md P1-4, P1-5; IQ-13 |
| Developer never sees background check, verification or screening | D8 (`contracts/background-check.md` §14) |
| API user reaches nothing | `test_api_user_reaches_nothing_in_the_crm` |
| Masked roles cannot search by identifier; an exact match may name a company | decision 12; BQ-2 |
| Amounts never totalled, kept in their currency | IQ-4; `trade-history.md` |

### 18.5 Sources (checked 5 October 2026)

- Salesforce: [How page layout elements display in Lightning Experience](https://help.salesforce.com/s/articleView?language=en_US&id=platform.layouts_in_lex.htm&type=5) · [Custom record pages (Trailhead)](https://trailhead.salesforce.com/content/learn/modules/lightning_app_builder/lightning_app_builder_recordpage) · [List views (Trailhead)](https://trailhead.salesforce.com/content/learn/modules/lightning-experience-for-salesforce-classic-users/work-with-list-views) · [Split view guide](https://www.salesforceben.com/your-complete-guide-to-salesforce-split-view/) · [Path (Lightning Design System)](https://archive-2_5_2.lightningdesignsystem.com/components/path/) · [Keyboard shortcuts](https://help.salesforce.com/s/articleView?id=xcloud.accessibility_keyboard_shortcuts.htm&language=en_US&type=5) · [Approval requests on the home page](https://help.salesforce.com/s/articleView?id=sf.approvals_homepage.htm&language=en_US&type=5)
- Microsoft: [Productive main form design in model-driven apps](https://learn.microsoft.com/en-us/power-apps/maker/model-driven-apps/design-productive-forms) · [Timeline control](https://learn.microsoft.com/en-us/power-apps/maker/model-driven-apps/set-up-timeline-control) · [Business process flows](https://learn.microsoft.com/en-us/power-apps/user/work-with-business-processes) · [Fluent 2 iconography](https://fluent2.microsoft.design/iconography) · [`@fluentui/svg-icons`](https://www.npmjs.com/package/@fluentui/svg-icons)
- HubSpot: [Record page layout](https://knowledge.hubspot.com/records/work-with-records)
- SAP: [Fiori object page floorplan](https://www.sap.com/design-system/fiori-design-web/v1-145/page-types/floorplans/object-page)
