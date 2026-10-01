// modules/onboarding — public facade.
// Other modules import ONLY from here.
export { CompanyRoutes, LegacyExporterRoutes } from './routes';
export {
  DealDetailPage,
  FollowUpsPage,
  PipelinePage,
  DealRequiredDocumentsPage,
  QualificationCriteriaPage,
} from './pages';
export { COMPANY_TABS, paths, type CompanyTab } from './paths';
// The Home page's cards: domain views composed by `src/pages/HomePage.tsx`.
export { CheckBacksDueCard, FollowUpsDueCard, PipelineSummaryCard } from './components/home';
