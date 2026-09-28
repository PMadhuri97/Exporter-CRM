/**
 * The shared history log — Developer 1's routes, read by the company page's
 * History tab and the deal page.
 *
 * Keys: `['companyHistory', id, params]` and `['dealHistory', id, params]`.
 * A mutation that writes history invalidates the prefix it touched; the
 * conversation panel keeps its own `['conversationHistory', id]` key.
 */

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { listCompanyHistory, listDealHistory } from '../api';
import type { HistoryListParams } from '../types';

export function useCompanyHistory(customerId: string | undefined, params: HistoryListParams = {}) {
  return useQuery({
    queryKey: ['companyHistory', customerId, params],
    queryFn: () => listCompanyHistory(customerId!, params),
    enabled: Boolean(customerId),
    placeholderData: keepPreviousData,
  });
}

export function useDealHistory(
  dealId: string | undefined,
  params: Omit<HistoryListParams, 'dimension'> = {},
) {
  return useQuery({
    queryKey: ['dealHistory', dealId, params],
    queryFn: () => listDealHistory(dealId!, params),
    enabled: Boolean(dealId),
    placeholderData: keepPreviousData,
  });
}
