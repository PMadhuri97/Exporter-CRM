// modules/onboarding — public facade.
// Other modules import ONLY from here.
export { CompanyRoutes, LegacyExporterRoutes } from './routes';
// Loaded on first use (G7): the app router gates each one before it renders.
export {
  DealDetailPage,
  FollowUpsPage,
  PipelinePage,
  DealRequiredDocumentsPage,
  QualificationCriteriaPage,
} from './lazyPages';
export { COMPANY_TABS, paths, type CompanyTab } from './paths';
// The Home page's cards: domain views composed by `src/pages/HomePage.tsx`.
export {
  CheckBacksDueCard,
  FollowUpsDueCard,
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
} from './components/home';
