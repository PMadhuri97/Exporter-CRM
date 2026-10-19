/**
 * What the Companies list can be narrowed by, and how those choices read.
 *
 * Separate from the panel that renders them: the page needs the type and the summary
 * too, and a file that exports both a component and its constants loses fast refresh.
 */

import { countryLabel } from './countries';

import type { BackgroundCheckState, CompanyTradeRole, ExporterSource } from './types';

/** The filters the list can be narrowed by. A key is absent when it is not filtering. */
export interface CompanyFilters {
  source?: ExporterSource;
  background_check?: BackgroundCheckState;
  trade_role?: CompanyTradeRole;
  has_open_deals?: boolean;
  country?: string;
  industry?: string;
}

/**
 * The sources a company can be filed under, in the order the New company panel offers
 * them — this is the same list, imported there, so the two cannot drift apart. A source
 * you can file a company under is a source you can find it by.
 *
 * `ExporterSource` also has `DEAL_BUYER`, which is deliberately absent: a company whose
 * record began as the other side of someone's deal is better asked for as *Buyer or
 * seller*, which answers by what the company has done rather than how its record began.
 *
 * A `Partial` record on purpose: a source added to the enum should not silently appear
 * in this list, and leaving one out should not be a type error.
 */
export const SOURCE_LABEL: Partial<Record<ExporterSource, string>> = {
  MANUAL: 'Manual entry',
  SALES: 'Sales',
  REFERRAL: 'Referral',
  RXIL: 'RXIL',
  PARTNER: 'Partner',
  API: 'API',
  BROKER: 'Broker',
  EVENT: 'Event',
  EXISTING_CUSTOMER: 'Existing customer',
};

export const CHECK_LABEL: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  CLEAR: 'Clear',
  MORE_INFO: 'More information needed',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

export const ROLE_LABEL: Record<CompanyTradeRole, string> = {
  SELLER: 'Seller',
  BUYER: 'Buyer',
  BOTH: 'Both',
};

/**
 * The filters in force, in words — for the export panel, which has its own *Source*
 * checkbox and must not be mistaken for choosing which companies are exported.
 *
 * Each entry reads "Source: RXIL". An empty list means every company the page's other
 * lenses allow; it does not mean every company in the database.
 */
/**
 * What else narrows the list, beside the panel's own filters: the lenses the panel
 * holds and the controls on the bar above it.
 *
 * Passed in rather than read here, because each keeps its own state — `owner` is a URL
 * lens, `name` is the search box — and this file holds no state of its own.
 */
export interface CompanyLensSummary {
  /** `ANY`, `me`, `none` or `inactive`. */
  owner?: string;
  /** `ANY` or `missing`. */
  contacts?: string;
  /** `ANY`, `me` or `none`. */
  collections?: string;
  /** The journey tab: `ALL` or a stage. */
  journey?: string;
  qualification?: string;
  relationship?: string;
  /** What is typed in the search box. */
  name?: string;
}

const OWNER_WORDS: Record<string, string> = {
  me: 'Mine',
  none: 'Unassigned',
  inactive: 'RM deactivated',
};

const COLLECTIONS_WORDS: Record<string, string> = {
  me: 'My collections',
  none: 'No collections owner',
};

export function describeFilters(
  filters: CompanyFilters,
  lenses: CompanyLensSummary = {},
): string[] {
  const described: string[] = [];
  if (filters.source) described.push(`Source: ${SOURCE_LABEL[filters.source] ?? filters.source}`);
  if (filters.trade_role) described.push(`Buyer or seller: ${ROLE_LABEL[filters.trade_role]}`);
  if (filters.background_check) {
    described.push(`Background check: ${CHECK_LABEL[filters.background_check]}`);
  }
  if (filters.has_open_deals !== undefined) {
    described.push(filters.has_open_deals ? 'Has an open deal' : 'No open deal');
  }
  if (filters.country) described.push(`Country: ${countryLabel(filters.country)}`);
  if (filters.industry) described.push(`Industry: ${filters.industry}`);

  // The bar and the lenses narrow the file just as much as the panel does. Left out,
  // the export said "Every company on the list" while Owner was set to Unassigned.
  if (lenses.name) described.push(`Name contains: ${lenses.name}`);
  if (lenses.journey && lenses.journey !== 'ALL') described.push(`Journey: ${lenses.journey}`);
  if (lenses.qualification && lenses.qualification !== 'ANY') {
    described.push(`Qualification: ${lenses.qualification}`);
  }
  if (lenses.relationship && lenses.relationship !== 'ANY') {
    described.push(`Relationship: ${lenses.relationship}`);
  }
  if (lenses.owner && lenses.owner !== 'ANY') {
    described.push(`Owner: ${OWNER_WORDS[lenses.owner] ?? lenses.owner}`);
  }
  if (lenses.contacts === 'missing') described.push('Contacts: no primary contact');
  if (lenses.collections && lenses.collections !== 'ANY') {
    described.push(`Collections: ${COLLECTIONS_WORDS[lenses.collections] ?? lenses.collections}`);
  }
  return described;
}
