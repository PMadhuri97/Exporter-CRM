// modules/onboarding: route subtree — mounted by the app router as
// `<Route path="/exporters/*" element={<OnboardingRoutes />} />`. Owning its
// own nested `<Routes>` here (rather than the app router listing every
// onboarding path itself) keeps route additions inside this module as later
// tickets (Exporter Detail, etc.) land, matching the module-facade
// discipline elsewhere in this project.
import { Route, Routes } from 'react-router-dom';

import {
  AddExporterPage,
  CompanyImportPage,
  ExporterDetailPage,
  ExportersListPage,
  RxilIntakePage,
} from './pages';
// Section 9.3 additions get their own import statement rather than joining the list
// above: an ES module's imports must sit at the top of the file, so they cannot live
// inside the owner anchors further down, and a separate line at least means no two
// owners ever edit the same one. 3A·2 (Phase 2):
import { FollowUpsPage } from './pages';
// 3B (L3-11b): a deal's own page, and one company's paperwork.
import { DealDetailPage, DocumentsPage } from './pages';

export function OnboardingRoutes() {
  return (
    <Routes>
      <Route index element={<ExportersListPage />} />
      <Route path="new" element={<AddExporterPage />} />
      <Route path="import" element={<CompanyImportPage />} />
      <Route path="rxil-intake" element={<RxilIntakePage />} />
      <Route path=":customerId" element={<ExporterDetailPage />} />
      {/*
        Section 9.3 — anchor blocks for Developers 3A and 3B. This file is
        Developer 1's (architecture §8.1); three people add routes to it, so the
        seam commit cuts the tail into owned blocks rather than leaving one
        shared append point that conflicts every time.

        Nothing is mounted here yet, and nothing should be until the screen it
        points at renders something: `layout/Sidebar.tsx`'s docstring states the
        rule — never navigation to a route that renders nothing.
      */}
      {/* ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ── */}
      {/* (3A appends here; 3B does not.) Cut into the two phase sub-anchors
          below — phase agreement §6.3. The conversation gauge is a panel on the
          detail page above, not a route of its own, so Phase 1 adds no route. */}

      {/* ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ── */}

      {/* ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ── */}
      {/*
        The Follow-ups screen (L3-11a-ii). Mounted **here**, inside this module's
        subtree, which the app router mounts at `/exporters/*` — so its URL is
        `/exporters/follow-ups`, and the sidebar's Follow-ups row points at that.

        The Phase 2 prompt's §5 assigns the route to this file and describes the
        sidebar change as a one-word `status` flip, which together would imply a
        top-level `/follow-ups`. Those two cannot both hold: `OnboardingRoutes` is
        only mounted under `/exporters/*`, so a top-level path would have to be added
        to `routes/AppRouter.tsx` and exported from `modules/onboarding/index.ts` —
        two files outside Phase 2's §2, against the explicit DoD "no file outside §2
        changed". Keeping the route here and giving the sidebar row its path costs one
        extra word on a line Phase 2 already owns. Flagged for Developer 1, who owns
        both files. See docs/dev3a-phase2-progress.md.
      */}
      <Route path="follow-ups" element={<FollowUpsPage />} />

      {/* ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ── */}
      {/* (3B appends here; 3A does not.)

        Both routes are inside this module's subtree, which the app router mounts at
        `/exporters/*`, so their URLs are `/exporters/deals/:dealId` and
        `/exporters/:customerId/documents`. Deals are reached from the company page's
        Deals panel rather than from the sidebar: there is no cross-company deal or
        document list on the server, and a sidebar row pointing at a page that can
        only say "pick a company first" would be the fake navigation
        `layout/Sidebar.tsx` forbids. That is why no row is added there — see
        docs/dev3b-progress.md.

        `deals/:dealId` is declared **before** `:customerId` would match it: the
        company route above is `:customerId` alone, so `/exporters/deals/x` has two
        segments and cannot collide with it. Kept adjacent so the next person adding
        a route here sees the constraint.
      */}
      <Route path="deals/:dealId" element={<DealDetailPage />} />
      <Route path=":customerId/documents" element={<DocumentsPage />} />
    </Routes>
  );
}
