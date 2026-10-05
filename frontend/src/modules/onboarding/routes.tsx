/**
 * modules/onboarding: route trees.
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
 *
 * The app router gates `/companies/*` on `crm.read`; the write screens below it are
 * gated again on their own capability, **at the route**: a role the server
 * refuses gets the same `NotFound` as an address that does not exist, and the page's
 * code is never downloaded.
 */

import { Navigate, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router-dom';

import { NotFound } from '@/components';
import { Gate } from '@/platform/access';

import {
  AddExporterPage,
  CompanyImportPage,
  ExporterDetailPage,
  ExportersListPage,
  IdentityCompletionPage,
  PipelinePage,
  RxilIntakePage,
} from './lazyPages';
import { paths } from './paths';

/**
 * Companies has two views of one list (frontend-plan §8.3): the register (rows) and
 * the board (three journey columns). `?view=board` picks the board, so a view is a
 * URL that can be shared.
 */
function CompaniesIndex() {
  const [params] = useSearchParams();
  return params.get('view') === 'board' ? <PipelinePage /> : <ExportersListPage />;
}

export function CompanyRoutes() {
  return (
    <Routes>
      <Route index element={<CompaniesIndex />} />
      <Route
        path="new"
        element={
          <Gate requires="company.create">
            <AddExporterPage />
          </Gate>
        }
      />
      <Route
        path="import"
        element={
          <Gate requires="company.import">
            <CompanyImportPage />
          </Gate>
        }
      />
      <Route
        path="rxil-intake"
        element={
          <Gate requires="company.rxilIntake">
            <RxilIntakePage />
          </Gate>
        }
      />
      <Route path="identity-completion" element={<IdentityCompletionPage />} />
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

/** `/pipeline` was its own screen until the redesign folded it into Companies as the board. */
export function PipelineRedirect() {
  return <Redirect to={paths.board} />;
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
