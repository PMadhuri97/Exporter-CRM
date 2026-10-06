// modules/onboarding — public facade.
// Other modules import ONLY from here.
export { CompanyRoutes, LegacyExporterRoutes, PipelineRedirect } from './routes';
// Loaded on first use: the app router gates each one before it renders.
export {
  DealDetailPage,
  DealsPage,
  FollowUpsPage,
  DealRequiredDocumentsPage,
  ApprovalsPage,
  QualificationCriteriaPage,
} from './lazyPages';
export { COMPANY_TABS, paths, type CompanyTab } from './paths';
// The header search's company results, and the journey badge beside each one.
export { JourneyBadge } from './components/StatusBadge';
export { identifierKind, useCompanyFinder, type IdentifierKind } from './hooks/finder';
export { JOURNEY_LABEL } from './constants';
// The style guide's domain sections — reached only from the dev-only `/__design`.
export { OnboardingStyleGuide } from './styleguide/OnboardingStyleGuide';
// Home's cards: domain views composed by `src/pages/HomePage.tsx`.
export {
  CheckBackCard,
  MyFollowUpsCard,
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
  SetupCard,
} from './components/home';
