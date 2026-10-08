/**
 * What the Companies list can be narrowed by, and how those choices read.
 *
 * Separate from the panel that renders them: the page needs the type and the summary
 * too, and a file that exports both a component and its constants loses fast refresh.
 */

import { COUNTRY_OPTIONS } from './countries';

import type {
  BackgroundCheckState,
  CompanyPipelineStatus,
  CompanyTradeRole,
  ExporterSource,
} from './types';

/** The filters the list can be narrowed by. A key is absent when it is not filtering. */
export interface CompanyFilters {
  source?: ExporterSource;
  pipeline_status?: CompanyPipelineStatus;
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
export function describeFilters(filters: CompanyFilters): string[] {
  const described: string[] = [];
  if (filters.source) described.push(`Source: ${SOURCE_LABEL[filters.source] ?? filters.source}`);
  if (filters.trade_role) described.push(`Buyer or seller: ${ROLE_LABEL[filters.trade_role]}`);
  if (filters.background_check) {
    described.push(`Background check: ${CHECK_LABEL[filters.background_check]}`);
  }
  if (filters.has_open_deals !== undefined) {
    described.push(filters.has_open_deals ? 'Has an open deal' : 'No open deal');
  }
  if (filters.country) {
    const country = COUNTRY_OPTIONS.find((option) => option.code === filters.country);
    described.push(`Country: ${country?.name ?? filters.country}`);
  }
  if (filters.industry) described.push(`Industry: ${filters.industry}`);
  if (filters.pipeline_status) described.push(`Pipeline: ${filters.pipeline_status}`);
  return described;
}
