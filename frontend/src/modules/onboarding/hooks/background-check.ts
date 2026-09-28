/**
 * React Query hooks for the background check — **owner: Developer 4A** (L4-03, L4-13).
 *
 * Recording a decision invalidates **both** the standing and the decision list: the
 * standing carries `allowed_moves`, so a stale copy would keep offering the move that
 * was just made. A **refused** decision reloads the standing too — a 409 usually means
 * the check moved under the screen, and the moves on offer should be the current ones.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getBackgroundCheck,
  listBackgroundCheckDecisions,
  recordBackgroundCheckDecision,
} from '../api';
import type { RecordBackgroundCheckDecisionRequest } from '../types';

/** Key prefix, so the mutation can invalidate everything about one company at once. */
const backgroundCheckKey = (customerId: string) => ['backgroundCheck', customerId] as const;
const decisionsKey = (customerId: string) =>
  ['backgroundCheckDecisions', customerId] as const;

export function useBackgroundCheck(customerId: string | undefined) {
  return useQuery({
    queryKey: backgroundCheckKey(customerId ?? ''),
    queryFn: () => getBackgroundCheck(customerId as string),
    enabled: Boolean(customerId),
  });
}

export function useBackgroundCheckDecisions(
  customerId: string | undefined,
  params: { limit?: number; offset?: number } = {},
) {
  return useQuery({
    queryKey: [...decisionsKey(customerId ?? ''), params],
    queryFn: () => listBackgroundCheckDecisions(customerId as string, params),
    enabled: Boolean(customerId),
  });
}

export function useRecordBackgroundCheckDecision(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordBackgroundCheckDecisionRequest) =>
      recordBackgroundCheckDecision(customerId, body),
    onSuccess: () => {
      // The standing carries `allowed_moves`; without this the dialog would go on
      // offering the move that was just made.
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: decisionsKey(customerId) });
      // The gauge is part of the company's story, so the history timeline changes too.
      void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
    },
  });
}
