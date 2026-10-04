/**
 * The module table: every top-level screen, declared once (`docs/frontend-plan.md`
 * §4.2, `remaining-work.md` R-33 Phase 0).
 *
 * The router (`AppRouter`) and the rail (`layout/Sidebar`) are both generated from
 * this, so neither can offer what the other refuses. A module carries the capabilities
 * it needs; a role without them gets no rail row and, at its URL, the same `NotFound`
 * as an address that does not exist. The screen itself is a `React.lazy` component
 * rendered inside the gate, so its code and its requests never reach that role.
 *
 * The modules' own sub-routes gate their write screens the same way
 * (`modules/onboarding/routes.tsx`: add company, import, RXIL intake).
 *
 * Phase 2 (frontend-plan §7): the command bar's "Go to" list, the `g` shortcuts and
 * the `?` sheet are generated from this table too, so a module appears in all of them
 * or in none. Rail labels follow §7.2 — Desk, Companies, Agenda — and Pipeline is the
 * Companies board now (`/pipeline` redirects there, so old links keep working).
 */

import { lazy, type ComponentType } from 'react';

import {
  CompanyRoutes,
  DealDetailPage,
  DealRequiredDocumentsPage,
  FollowUpsPage,
  LegacyExporterRoutes,
  PipelineRedirect,
  QualificationCriteriaPage,
  ReviewPage,
} from '@/modules/onboarding';
import type { IconName } from '@/design/icons';
import { SettingsRoutes } from '@/modules/settings';
import { can, type Capability } from '@/platform/access';

const HomePage = lazy(() => import('@/pages/HomePage').then((m) => ({ default: m.HomePage })));

export interface NavRow {
  label: string;
  /** Where the row links; the module's `path` may be a splat. */
  to: string;
  icon: IconName;
  /** `main` rows sit at the top of the rail; `settings` rows at its foot. */
  group: 'main' | 'settings';
  /** The key after `g` that goes here (`g c` → Companies). */
  shortcut?: string;
}

export interface AppModule {
  id: string;
  /** The route path, as `<Route path>` takes it. */
  path: string;
  /** Every one is needed. An empty list is "any signed-in user". */
  requires: readonly Capability[];
  Screen: ComponentType;
  /**
   * What a role without `requires` sees here. Absent: the generic `NotFound`.
   * `noWorkspace` is for the root only — a user with no CRM capability lands there.
   */
  denied?: 'noWorkspace';
  nav?: NavRow;
}

/**
 * In rail order. Deals and documents have no row: they are reached from a company,
 * because the server has no cross-company deal or document list.
 */
export const APP_MODULES: readonly AppModule[] = [
  {
    id: 'home',
    path: '/',
    requires: ['crm.read'],
    Screen: HomePage,
    denied: 'noWorkspace',
    nav: { label: 'Desk', to: '/', icon: 'desk', group: 'main', shortcut: 'h' },
  },
  {
    id: 'companies',
    path: '/companies/*',
    requires: ['crm.read'],
    Screen: CompanyRoutes,
    nav: { label: 'Companies', to: '/companies', icon: 'company', group: 'main', shortcut: 'c' },
  },
  {
    id: 'follow-ups',
    path: '/follow-ups',
    requires: ['crm.read'],
    Screen: FollowUpsPage,
    nav: { label: 'Agenda', to: '/follow-ups', icon: 'agenda', group: 'main', shortcut: 'f' },
  },
  // The compliance working day (frontend-plan §8.8). Absent for every other role.
  {
    id: 'review',
    path: '/review',
    requires: ['compliance.queue'],
    Screen: ReviewPage,
    nav: { label: 'Review', to: '/review', icon: 'review', group: 'main', shortcut: 'r' },
  },
  // The Companies board's older address (no rail row: Companies is the row).
  { id: 'pipeline', path: '/pipeline', requires: ['crm.read'], Screen: PipelineRedirect },
  { id: 'deal', path: '/deals/:dealId', requires: ['crm.read'], Screen: DealDetailPage },
  // The old `/exporters/*` addresses redirect into the CRM, so they need it too.
  {
    id: 'legacy-exporters',
    path: '/exporters/*',
    requires: ['crm.read'],
    Screen: LegacyExporterRoutes,
  },
  // Settings → My profile is for every role, the API user included.
  {
    id: 'settings',
    path: '/settings/*',
    requires: [],
    Screen: SettingsRoutes,
    nav: { label: 'Settings', to: '/settings', icon: 'settings', group: 'settings', shortcut: 's' },
  },
  // Static paths outrank the `/settings/*` splat in React Router, whatever the order.
  {
    id: 'qualification-criteria',
    path: '/settings/qualification-criteria',
    requires: ['settings.criteria'],
    Screen: QualificationCriteriaPage,
    nav: {
      label: 'Qualification criteria',
      to: '/settings/qualification-criteria',
      icon: 'criteria',
      group: 'settings',
    },
  },
  {
    // Which paperwork a deal must have before handover (plan P2-5a).
    id: 'required-documents',
    path: '/settings/deal-required-documents',
    requires: ['settings.requiredDocuments'],
    Screen: DealRequiredDocumentsPage,
    nav: {
      label: 'Required documents',
      to: '/settings/deal-required-documents',
      icon: 'requiredDocuments',
      group: 'settings',
    },
  },
];

/** The rail rows `role` may follow, in rail order. */
export function navRowsFor(role: string | null | undefined): NavRow[] {
  return APP_MODULES.filter((module) => module.nav && can(role, module.requires)).map(
    (module) => module.nav as NavRow,
  );
}

/** The rail row a path belongs to — the most specific one (`/settings/x` over `/settings`). */
export function navRowForPath(rows: readonly NavRow[], pathname: string): NavRow | undefined {
  return rows
    .filter((row) => (row.to === '/' ? pathname === '/' : pathname === row.to || pathname.startsWith(`${row.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0];
}
