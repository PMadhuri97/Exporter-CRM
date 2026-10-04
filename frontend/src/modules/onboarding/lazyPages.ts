/**
 * Every onboarding screen, loaded on first use (`docs/frontend-plan.md` §4.3, G7).
 *
 * Each page is its own chunk, imported from its own file — never through
 * `./pages/index.ts`, which would pull every page into whichever chunk reached it
 * first. A route wraps these in `Gate`, so a role that may not open a screen never
 * downloads it: the administrator's settings screens and RXIL intake reach no other
 * role's browser.
 */

import { lazy } from 'react';

export const AddExporterPage = lazy(() =>
  import('./pages/AddExporterPage').then((m) => ({ default: m.AddExporterPage })),
);
export const CompanyImportPage = lazy(() =>
  import('./pages/CompanyImportPage').then((m) => ({ default: m.CompanyImportPage })),
);
export const DealDetailPage = lazy(() =>
  import('./pages/DealDetailPage').then((m) => ({ default: m.DealDetailPage })),
);
export const DealRequiredDocumentsPage = lazy(() =>
  import('./pages/DealRequiredDocumentsPage').then((m) => ({
    default: m.DealRequiredDocumentsPage,
  })),
);
export const ExporterDetailPage = lazy(() =>
  import('./pages/ExporterDetailPage').then((m) => ({ default: m.ExporterDetailPage })),
);
export const ExportersListPage = lazy(() =>
  import('./pages/ExportersListPage').then((m) => ({ default: m.ExportersListPage })),
);
export const FollowUpsPage = lazy(() =>
  import('./pages/FollowUpsPage').then((m) => ({ default: m.FollowUpsPage })),
);
export const IdentityCompletionPage = lazy(() =>
  import('./pages/IdentityCompletionPage').then((m) => ({ default: m.IdentityCompletionPage })),
);
export const PipelinePage = lazy(() =>
  import('./pages/PipelinePage').then((m) => ({ default: m.PipelinePage })),
);
export const QualificationCriteriaPage = lazy(() =>
  import('./pages/QualificationCriteriaPage').then((m) => ({
    default: m.QualificationCriteriaPage,
  })),
);
export const RxilIntakePage = lazy(() =>
  import('./pages/RxilIntakePage').then((m) => ({ default: m.RxilIntakePage })),
);
