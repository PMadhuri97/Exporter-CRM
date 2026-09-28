# Frontend refresh — 28 September 2026

An audit of `frontend/` against the Architecture PDF
(`docs/Exporter-CRM-Architecture-and-Plan.pdf`) and the developer handover docs,
and the refresh that followed. No backend file changed; `openapi.json` and
`schema.ts` were not regenerated.

## What the audit found

The data model was already current: the journey (LEAD → PROSPECT → CUSTOMER),
the PAUSED/ENDED marker, qualification, the conversation gauge, follow-ups,
deals and documents were all built, every allowed move was read from the
server, and the generated API types matched the backend. What looked dated was
the surface:

- **Stale text on screen.** "Opening a deal is not built yet" on READY_NOW
  (deals had shipped); a placeholder dashboard saying the list, follow-ups and
  pipeline were "next in the build sequence"; "Exporter" where the PDF says
  "company".
- **Backend features with no screen.** Qualification criteria admin (L2-09),
  the company and deal history (§3.1, L1-11), opening a deal from READY_NOW
  (§3.3, seam S2). No 404 route; handover used `window.confirm`.
- **No design system in use.** Radix, `clsx` and `tailwind-merge` installed but
  never imported; Inter named but never loaded; five separate chip
  implementations; colour tokens still named after the retired lifecycle; one
  long stacked company page; no dark mode or narrow-screen layout.

## What changed

**Foundations**

- Colour tokens are CSS variables (`src/index.css`) with light and dark palettes,
  mapped in `tailwind.config.ts`. `stage.*` became `journey.*` and `marker.*`;
  `brand-200`/`700` and `status-info` were added.
- Inter is self-hosted (`@fontsource-variable/inter`).
- A UI kit in `src/components/ui/` — `Button`, `Chip`, `Card`/`Panel`,
  `PageHeader`, `Tabs` (Radix), `Dialog`/`ConfirmDialog`/`Drawer`/`Sheet`
  (Radix), `Field`/`Input`/`Select`/`Textarea`, `Table`, `Skeleton`,
  `ErrorState`, `NotFound` — exported from `@/components`. Every page and panel
  is built from it, except the two files below.
- Theme toggle (system → light → dark) in the top bar, applied before first
  paint by an inline script in `index.html` (`src/platform/theme`).
- Responsive shell: the sidebar collapses to an icon rail on large screens and
  becomes a drawer on small ones; tables scroll inside their card.
- `isStaffRole` / `isAdminRole` in `@/platform/auth` replace the per-screen role
  checks (one of which, `role !== 'DEVELOPER'`, let `API_USER` through).

**URLs** — every path is spelled once, in `modules/onboarding/paths.ts`.

| Screen | URL | Was |
|---|---|---|
| Home ("My work") | `/` | placeholder dashboard |
| Companies | `/companies` (`?journey=` selects a tab) | `/exporters` |
| Add / import / RXIL intake | `/companies/new`, `/import`, `/rxil-intake` | `/exporters/…` |
| Company page | `/companies/:id` (`?tab=overview…history`) | `/exporters/:id` |
| Company documents | `/companies/:id?tab=documents` | `/exporters/:id/documents` |
| Deal | `/deals/:dealId` | `/exporters/deals/:dealId` |
| Follow-ups | `/follow-ups` | `/exporters/follow-ups` |
| Pipeline | `/pipeline` | unchanged |
| Qualification criteria (ADMIN) | `/settings/qualification-criteria` | — |
| Anything else | 404 page | blank shell |

Every old `/exporters/*` address redirects, query string kept
(`LegacyExporterRoutes`). The API is still `/api/v1/onboarding/exporters`.

**Screens**

- **Home** — overdue follow-ups (mine / team), check-backs due, and a count per
  journey stage. There is no stats endpoint and the company search returns no
  total, so a count is the length of one capped search, shown as "200+" at the
  cap.
- **Company page** — a sticky header (name, journey, qualification, marker,
  masked PAN/GSTIN, owner, conversation and check-back date, marker moves) over
  tabs: Overview, Qualification, Conversation, Deals, Documents, Background
  check, History. DEVELOPER gets no Background check tab (the server refuses it
  the results). Marker moves ask for their reason in a dialog.
- **History** — the shared log, every dimension, filterable, paged; profile edits
  show before and after as the server recorded (and masked) them. Also on the
  deal page.
- **Open a deal from READY_NOW** — the prompt uses the same `OpenDealForm` as the
  Deals tab and goes to the new deal.
- **Qualification criteria (ADMIN)** — list, add, "new version" (prefilled),
  version history. No edit or delete: every change is a version. A 409
  `QUALIFICATION_CRITERION_CHANGED` is explained, not swallowed.
- **Deal page** — handover confirmed in a dialog; stage, buyer, paperwork and
  history laid out side by side.
- The company list gained paging; the add form gained CIN.

**Left untouched on purpose:** `components/VerificationSection.tsx` and
`pages/panels/BackgroundCheckPanel.tsx` (Developer 4's). They sit in the
Background check tab as they were. One scoped rule in `index.css` keeps their
`bg-ink text-white` buttons legible in the dark theme; their hard-coded
`red-*`/`emerald-*`/`amber-*` classes keep light-theme colours there.

## Blocked or out of scope

| Item | Why | Needs |
|---|---|---|
| Background-check gauge, risk rating with CRITICAL, reopen dialog, screening history (L4-07…L4-13) | No backend: migration 0015 and its routes do not exist | Developer 4 |
| Deals and Documents rows in the sidebar (PDF §8.1) | No cross-company deal or document list on the server | Programme lead, then backend |
| Handover | Always blocked until the background check exists; the page shows `handover_blocked_reason` | Developer 4 |
| Exact counts on Home and the list | The company search has no `total` | Backend |
| People's names instead of actor ids | No users endpoint | Backend |
| Changing a NOT_NOW check-back date in one step | Needs a backend change | Developer 3A / lead |
| Reason-code admin screen | No route (criterion-result Q5) | Developer 2 / lead |

**Backend issues found during the audit:**

- **Fixed (28 Sep, on request):** a deal buyer's `registration_number`,
  `tax_id`, `contact_email` and `contact_phone` reached OPERATIONS and DEVELOPER
  unmasked on every deal response. `schemas/deal.py`'s docstring promised the
  contact details were masked through a `_masked_contact` helper that was never
  written, and deliberately left the registration number and tax ID visible;
  the lead's call was to mask all four, like an exporter's PAN/GSTIN. Now
  `DealBuyerResponse.masked_for(viewer)` applies the shared `masking.py` rule on
  all four deal routes; `SetDealBuyerRequest` refuses a masked value
  (`NotMasked`); and a masked field **left out** of the `PUT` keeps its stored
  value (`DealService.set_buyer(keep=…)`), so OPERATIONS can edit a buyer
  without erasing what it cannot see — the buyer form starts those fields empty
  ("Hidden — type to replace") and omits them unless typed. Tests in
  `test_l3b_deal_buyer.py` and `DealDetailPage.test.tsx`; `openapi.json` and
  `schema.ts` regenerated (descriptions only). **Developer 3B should know** —
  it reverses their documented design for the two identifiers.
- `allowed_stage_moves` is not filtered by role, so DEVELOPER is served moves
  it would get 403 for. The UI already hides them.
