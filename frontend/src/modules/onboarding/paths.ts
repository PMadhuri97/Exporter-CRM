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
  company: (customerId: string, tab?: CompanyTab) =>
    tab && tab !== 'overview'
      ? `/companies/${customerId}?tab=${tab}`
      : `/companies/${customerId}`,
  deal: (dealId: string) => `/deals/${dealId}`,
  followUps: '/follow-ups',
  pipeline: '/pipeline',
  qualificationCriteria: '/settings/qualification-criteria',
} as const;
