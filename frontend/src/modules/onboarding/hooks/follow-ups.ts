/**
 * React Query hooks for follow-ups — **owner: Developer 3A, Phase 2** (L3-04b).
 *
 * Created as a stub in the seam commit with its barrel line in `hooks/index.ts`, and
 * filled here, so Phase 2 never opened the barrel.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { completeFollowUp, listFollowUps } from '../api';
import type { CompleteFollowUpRequest, FollowUpListParams } from '../types';

export function useFollowUps(params: FollowUpListParams = {}) {
  return useQuery({
    queryKey: ['followUps', params],
    queryFn: () => listFollowUps(params),
  });
}

/**
 * Complete a follow-up, then refresh what the completion changed.
 *
 * Two invalidations:
 *
 * - `followUps` — every variant of the list. The completed row moves from
 *   outstanding to done, and a RESCHEDULED completion also **adds** a row (the
 *   replacement follow-up the server logs), so no single cached page can be patched
 *   in place.
 * - `exporterActivities` for the company — a reschedule logs a new activity, which
 *   the company page's activity list shows. Developer 3A owns that key too, so this
 *   is not a cross-owner reach.
 *
 * The conversation gauge is deliberately **not** invalidated: completing a follow-up
 * does not move it. A check-back row leaves this list by someone moving the gauge on
 * the company page, which invalidates its own keys.
 */
export function useCompleteFollowUp(customerId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      activityId,
      payload,
    }: {
      activityId: string;
      payload: CompleteFollowUpRequest;
    }) => completeFollowUp(activityId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['followUps'] });
      if (customerId) {
        void queryClient.invalidateQueries({
          queryKey: ['exporterActivities', customerId],
        });
      }
    },
  });
}
