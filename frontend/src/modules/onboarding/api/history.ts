/**
 * The shared CRM history log — read side.
 *
 * Every recorded change to a company — its journey, each gauge, its marker,
 * profile edits and its deals — interleaved, newest first; or one deal's own
 * changes. Nothing is ever edited: a correction is a new row.
 */

import { apiRequest } from '@/lib/api/client';

import type { HistoryList, HistoryListParams } from '../types';

function historyQuery(params: HistoryListParams): string {
  const query = new URLSearchParams();
  if (params.dimension) query.set('dimension', params.dimension);
  query.set('limit', String(params.limit ?? 25));
  query.set('offset', String(params.offset ?? 0));
  return query.toString();
}

export function listCompanyHistory(
  customerId: string,
  params: HistoryListParams = {},
): Promise<HistoryList> {
  return apiRequest<HistoryList>(
    `/onboarding/exporters/${customerId}/history?${historyQuery(params)}`,
  );
}

export function listDealHistory(
  dealId: string,
  params: Omit<HistoryListParams, 'dimension'> = {},
): Promise<HistoryList> {
  return apiRequest<HistoryList>(`/onboarding/deals/${dealId}/history?${historyQuery(params)}`);
}
