/**
 * modules/onboarding: route trees — **owner: Developer 1**.
 *
 * The app router mounts these through the module facade:
 *
 *   /companies/*   CompanyRoutes          the company screens
 *   /exporters/*   LegacyExporterRoutes   redirects from the old addresses
 *
 * The screens that sit at the top level (`/follow-ups`, `/pipeline`,
 * `/deals/:dealId`, `/settings/qualification-criteria`) are single pages, so
 * the app router mounts them directly. Every URL is spelled once, in
 * `paths.ts`.
 */

import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom';

import { NotFound } from '@/components';

import {
  AddExporterPage,
  CompanyImportPage,
  ExporterDetailPage,
  ExportersListPage,
  RxilIntakePage,
} from './pages';
import { paths } from './paths';

export function CompanyRoutes() {
  return (
    <Routes>
      <Route index element={<ExportersListPage />} />
      <Route path="new" element={<AddExporterPage />} />
      <Route path="import" element={<CompanyImportPage />} />
      <Route path="rxil-intake" element={<RxilIntakePage />} />
      <Route path=":customerId" element={<ExporterDetailPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

/** Sends `to` on with the current query string, so a bookmarked filter or tab
 * survives the move. */
function Redirect({ to }: { to: string }) {
  const { search } = useLocation();
  const target = search ? `${to}${to.includes('?') ? '&' : '?'}${search.slice(1)}` : to;
  return <Navigate to={target} replace />;
}

function CompanyRedirect({ documents = false }: { documents?: boolean }) {
  const { customerId = '' } = useParams();
  return <Redirect to={paths.company(customerId, documents ? 'documents' : undefined)} />;
}

function DealRedirect() {
  const { dealId = '' } = useParams();
  return <Redirect to={paths.deal(dealId)} />;
}

/**
 * The screens lived under `/exporters/*` until the refresh renamed them to the
 * architecture's "company". Old bookmarks and pasted links keep working.
 * (The API is still `/api/v1/onboarding/exporters`; only the screens moved.)
 */
export function LegacyExporterRoutes() {
  return (
    <Routes>
      <Route index element={<Redirect to={paths.companies} />} />
      <Route path="new" element={<Redirect to={paths.newCompany} />} />
      <Route path="import" element={<Redirect to={paths.importCompanies} />} />
      <Route path="rxil-intake" element={<Redirect to={paths.rxilIntake} />} />
      <Route path="follow-ups" element={<Redirect to={paths.followUps} />} />
      <Route path="deals/:dealId" element={<DealRedirect />} />
      <Route path=":customerId" element={<CompanyRedirect />} />
      <Route path=":customerId/documents" element={<CompanyRedirect documents />} />
      <Route path="*" element={<Redirect to={paths.companies} />} />
    </Routes>
  );
}
