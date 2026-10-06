/**
 * The module table: every top-level screen, declared once (`docs/frontend-plan.md`
 * §4.2).
 *
 * The router (`AppRouter`), the side navigation, search's *Pages* group and the
 * shortcut list are all generated from this, so none of them can offer what another
 * refuses. A module carries the capabilities it needs; a role without them gets no
 * nav row and, at its URL, the same `NotFound` as an address that does not exist.
 * The screen itself is a `React.lazy` component rendered inside the gate, so its code
 * and its requests never reach that role.
 *
 * The modules' own sub-routes gate their write screens the same way
 * (`modules/onboarding/routes.tsx`: add company, import, RXIL intake).
 *
 * Nav names are the standard CRM ones (frontend-plan §18.1): Home, Companies,
 * Pipeline, Follow-ups, Approvals, Settings. Pipeline is the Companies board
 * (`/pipeline` redirects to it), and `/review` redirects to `/approvals`, so old
 * links keep working.
 */

import { createElement, lazy, type ComponentType } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import {
  CompanyRoutes,
  DealDetailPage,
  DealRequiredDocumentsPage,
  FollowUpsPage,
  LegacyExporterRoutes,
  PipelineRedirect,
  QualificationCriteriaPage,
  ApprovalsPage,
} from '@/modules/onboarding';
import type { IconName } from '@/design/icons';
import { SettingsRoutes, SettingsSectionFrame } from '@/modules/settings';
import { can, type Capability } from '@/platform/access';

const HomePage = lazy(() => import('@/pages/HomePage').then((m) => ({ default: m.HomePage })));

export interface NavRow {
  label: string;
  /** Where the row links; the module's `path` may be a splat. */
  to: string;
  icon: IconName;
  /** `main` rows sit at the top of the side navigation; `settings` rows at its foot. */
  group: 'main' | 'settings';
  /** Off for a Settings section reached from the Settings frame: it is still a page
   * search offers, but the side navigation shows only *Settings* (§7.3). */
  sideNav?: boolean;
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

/** The two rule sections are their own modules, drawn inside the Settings frame. */
function CriteriaSection() {
  return createElement(SettingsSectionFrame, {
    section: 'criteria',
    children: createElement(QualificationCriteriaPage),
  });
}

function RequiredDocumentsSection() {
  return createElement(SettingsSectionFrame, {
    section: 'requiredDocuments',
    children: createElement(DealRequiredDocumentsPage),
  });
}

/** `/review` was the Approvals address; it keeps working, with its `?case=`. */
function ReviewRedirect() {
  const { search } = useLocation();
  return createElement(Navigate, { to: `/approvals${search}`, replace: true });
}

/**
 * In side-navigation order. Deals and documents have no row: they are reached from a company,
 * because the server has no cross-company deal or document list.
 */
export const APP_MODULES: readonly AppModule[] = [
  {
    id: 'home',
    path: '/',
    requires: ['crm.read'],
    Screen: HomePage,
    denied: 'noWorkspace',
    nav: { label: 'Home', to: '/', icon: 'home', group: 'main' },
  },
  {
    id: 'companies',
    path: '/companies/*',
    requires: ['crm.read'],
    Screen: CompanyRoutes,
    nav: { label: 'Companies', to: '/companies', icon: 'company', group: 'main' },
  },
  // The Companies board. `/pipeline` redirects to `/companies?view=board`, where the
  // nav marks Pipeline, not Companies, as current (`navRowForPath`).
  {
    id: 'pipeline',
    path: '/pipeline',
    requires: ['crm.read'],
    Screen: PipelineRedirect,
    nav: { label: 'Pipeline', to: '/pipeline', icon: 'pipeline', group: 'main' },
  },
  {
    id: 'follow-ups',
    path: '/follow-ups',
    requires: ['crm.read'],
    Screen: FollowUpsPage,
    nav: { label: 'Follow-ups', to: '/follow-ups', icon: 'followUps', group: 'main' },
  },
  // Items to approve and Re-KYC due (frontend-plan §8.8). Absent for every other role.
  {
    id: 'approvals',
    path: '/approvals',
    requires: ['compliance.queue'],
    Screen: ApprovalsPage,
    nav: { label: 'Approvals', to: '/approvals', icon: 'approvals', group: 'main' },
  },
  { id: 'review', path: '/review', requires: ['compliance.queue'], Screen: ReviewRedirect },
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
    nav: { label: 'Settings', to: '/settings', icon: 'settings', group: 'settings' },
  },
  // Static paths outrank the `/settings/*` splat in React Router, whatever the order.
  {
    id: 'qualification-criteria',
    path: '/settings/qualification-criteria',
    requires: ['settings.criteria'],
    Screen: CriteriaSection,
    nav: {
      label: 'Qualification criteria',
      to: '/settings/qualification-criteria',
      icon: 'criteria',
      group: 'settings',
      sideNav: false,
    },
  },
  {
    // Which paperwork a deal must have before handover.
    id: 'required-documents',
    path: '/settings/deal-required-documents',
    requires: ['settings.requiredDocuments'],
    Screen: RequiredDocumentsSection,
    nav: {
      label: 'Required documents',
      to: '/settings/deal-required-documents',
      icon: 'requiredDocuments',
      group: 'settings',
      sideNav: false,
    },
  },
];

/** The nav rows `role` may follow, in side-navigation order. */
export function navRowsFor(role: string | null | undefined): NavRow[] {
  return APP_MODULES.filter((module) => module.nav && can(role, module.requires)).map(
    (module) => module.nav as NavRow,
  );
}

/**
 * The nav row a location belongs to — the most specific one (`/settings/x` over
 * `/settings`). The Companies board (`?view=board`) belongs to Pipeline.
 */
export function navRowForPath(
  rows: readonly NavRow[],
  pathname: string,
  search = '',
): NavRow | undefined {
  if (pathname === '/companies' && new URLSearchParams(search).get('view') === 'board') {
    const pipeline = rows.find((row) => row.to === '/pipeline');
    if (pipeline) return pipeline;
  }
  return rows
    .filter((row) => (row.to === '/' ? pathname === '/' : pathname === row.to || pathname.startsWith(`${row.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0];
}
