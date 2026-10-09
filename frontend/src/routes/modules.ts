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
 * Nav names are the standard CRM ones (frontend-plan §18.1): Home, Companies, My
 * companies (an RM's own, `/my-companies` redirecting to the list filtered by owner),
 * Pipeline, Deals, Follow-ups, Compliance work (once "Approvals"), Settings. Pipeline is the Companies board
 * (`/pipeline` redirects to it), and `/review` redirects to `/approvals`, so old
 * links keep working.
 */

import { createElement, lazy, type ComponentType } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import {
  CompanyRoutes,
  DealDetailPage,
  DealsPage,
  DealRequiredDocumentsPage,
  PaymentTermsPage,
  SanctionsListsPage,
  FollowUpsPage,
  LegacyExporterRoutes,
  MyCompaniesRedirect,
  PipelineRedirect,
  QualificationCriteriaPage,
  ApprovalsPage,
  type WorklistBadgeKind,
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
  /** A computed count beside the row (`WorklistBadge`). */
  badge?: WorklistBadgeKind;
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

function PaymentTermsSection() {
  return createElement(SettingsSectionFrame, {
    section: 'paymentTerms',
    children: createElement(PaymentTermsPage),
  });
}

function SanctionsListsSection() {
  return createElement(SettingsSectionFrame, {
    section: 'sanctionsLists',
    children: createElement(SanctionsListsPage),
  });
}

/** `/review` was the Approvals address; it keeps working, with its `?case=`. */
function ReviewRedirect() {
  const { search } = useLocation();
  return createElement(Navigate, { to: `/approvals${search}`, replace: true });
}

/**
 * In side-navigation order. Documents have no row: they are reached from a company or a
 * deal, because the server has no cross-company document list. Deals have one
 * (`GET /deals` lists every company's), and a deal's own page keeps that row current.
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
  // The companies this user is RM of: the list, filtered by owner. Only an RM has
  // any — ADMIN assigns RMs and COMPLIANCE never is one. Its badge counts the checks
  // waiting on information for those companies.
  {
    id: 'my-companies',
    path: '/my-companies',
    requires: ['rm.self'],
    Screen: MyCompaniesRedirect,
    nav: {
      label: 'My companies',
      to: '/my-companies',
      icon: 'person',
      group: 'main',
      badge: 'infoRequested',
    },
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
    id: 'deals',
    path: '/deals',
    requires: ['crm.read'],
    Screen: DealsPage,
    nav: { label: 'Deals', to: '/deals', icon: 'deal', group: 'main' },
  },
  {
    id: 'follow-ups',
    path: '/follow-ups',
    requires: ['crm.read'],
    Screen: FollowUpsPage,
    nav: { label: 'Follow-ups', to: '/follow-ups', icon: 'followUps', group: 'main' },
  },
  // Compliance work: reviews, items to approve and Re-KYC due (frontend-plan §8.8).
  // Absent for every other role. The address stays `/approvals`.
  {
    id: 'approvals',
    path: '/approvals',
    requires: ['compliance.queue'],
    Screen: ApprovalsPage,
    nav: { label: 'Compliance work', to: '/approvals', icon: 'approvals', group: 'main', badge: 'compliance' },
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
  {
    // The payment terms deals and company defaults choose from.
    id: 'payment-terms',
    path: '/settings/payment-terms',
    requires: ['settings.paymentTerms'],
    Screen: PaymentTermsSection,
    nav: {
      label: 'Payment terms',
      to: '/settings/payment-terms',
      icon: 'receipt',
      group: 'settings',
      sideNav: false,
    },
  },
  {
    // The sanctions lists a screening covers.
    id: 'sanctions-lists',
    path: '/settings/sanctions-lists',
    requires: ['settings.sanctionsLists'],
    Screen: SanctionsListsSection,
    nav: {
      label: 'Sanctions lists',
      to: '/settings/sanctions-lists',
      icon: 'shield',
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
 * `/settings`). The Companies board (`?view=board`) belongs to Pipeline, and the list
 * filtered to the user's own companies (`?owner=me`) to My companies.
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
  if (pathname === '/companies' && new URLSearchParams(search).get('owner') === 'me') {
    const mine = rows.find((row) => row.to === '/my-companies');
    if (mine) return mine;
  }
  return rows
    .filter((row) => (row.to === '/' ? pathname === '/' : pathname === row.to || pathname.startsWith(`${row.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0];
}
