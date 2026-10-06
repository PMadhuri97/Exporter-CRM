/**
 * Every in-app URL this module owns, in one place.
 *
 * Screens link through these rather than writing `/companies/${id}` inline, so
 * a URL changes in one file. (They did change once: the screens lived under
 * `/exporters/*` until the refresh renamed them to match the architecture's
 * "company" — `LegacyExporterRoutes` in `routes.tsx` still redirects the old
 * addresses.)
 */

/** The company page's tabs, in display order. */
export const COMPANY_TABS = [
  'overview',
  'qualification',
  'conversation',
  'deals',
  'documents',
  'background-check',
  'history',
] as const;

export type CompanyTab = (typeof COMPANY_TABS)[number];

export const paths = {
  companies: '/companies',
  newCompany: '/companies/new',
  importCompanies: '/companies/import',
  rxilIntake: '/companies/rxil-intake',
  /** The identity completion list. */
  identityCompletion: '/companies/identity-completion',
  company: (customerId: string, tab?: CompanyTab) =>
    tab && tab !== 'overview'
      ? `/companies/${customerId}?tab=${tab}`
      : `/companies/${customerId}`,
  /** Every deal, across companies. */
  deals: '/deals',
  /** The Deals page with *New deal* open, so a link anywhere can start one. */
  newDeal: '/deals?new=1',
  deal: (dealId: string) => `/deals/${dealId}`,
  /** Companies as a board of three journey columns (frontend-plan §8.3). */
  board: '/companies?view=board',
  followUps: '/follow-ups',
  /** The board's older address: it redirects to `board`, so links keep working. */
  pipeline: '/pipeline',
  qualificationCriteria: '/settings/qualification-criteria',
  /** Which paperwork a handover needs. ADMIN only. */
  dealRequiredDocuments: '/settings/deal-required-documents',
} as const;
