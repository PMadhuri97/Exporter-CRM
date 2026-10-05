// modules/onboarding — public facade.
// Other modules import ONLY from here.
export { CompanyRoutes, LegacyExporterRoutes, PipelineRedirect } from './routes';
// Loaded on first use: the app router gates each one before it renders.
export {
  DealDetailPage,
  FollowUpsPage,
  DealRequiredDocumentsPage,
  ReviewPage,
  QualificationCriteriaPage,
} from './lazyPages';
export { COMPANY_TABS, paths, type CompanyTab } from './paths';
// The shell's company search (⌘K) and the journey glyph it draws beside each result.
export { JourneyDots } from './components/CompanyChips';
export { identifierKind, useCompanyFinder, type IdentifierKind } from './hooks/finder';
export { JOURNEY_LABEL } from './constants';
// The style guide's domain sections — reached only from the dev-only `/__design`.
export { OnboardingStyleGuide } from './styleguide/OnboardingStyleGuide';
// The desk's sections: domain views composed by `src/pages/HomePage.tsx`.
export {
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
  SetupCard,
  UpNextCard,
} from './components/home';
