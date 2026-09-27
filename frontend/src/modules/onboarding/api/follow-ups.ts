/**
 * Follow-ups and completions — **owner: Developer 3A, Phase 2** (L3-04b).
 *
 * Created as a stub in the seam commit, together with its
 * `export * from './follow-ups'` line in `api/index.ts`, and filled here — so the
 * barrel, which every owner shares, was never opened twice.
 *
 * The paths are `/onboarding/follow-ups`, not under `/onboarding/exporters/...`: a
 * follow-ups list spans every company, so it is not a company sub-resource. See
 * `follow_up_router.py`'s docstring for the other reason — `/exporters/follow-ups`
 * would be matched by `/exporters/{customer_id}` first.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  CompleteFollowUpRequest,
  FollowUpCompletion,
  FollowUpList,
  FollowUpListParams,
} from '../types';

/**
 * What we owe exporters next: follow-ups, and companies parked at NOT_NOW.
 *
 * No owner filter by default — follow-ups are the whole team's (decision D2).
 * `actorId` narrows the list; it is never a permission.
 */
export function listFollowUps(params: FollowUpListParams = {}): Promise<FollowUpList> {
  const query = new URLSearchParams();
  if (params.state) query.set('state', params.state);
  if (params.customerId) query.set('customer_id', params.customerId);
  if (params.actorId) query.set('actor_id', params.actorId);
  if (params.includeCheckBacks === false) query.set('include_check_backs', 'false');
  if (params.checkBacksDueOnly) query.set('check_backs_due_only', 'true');
  query.set('limit', String(params.limit ?? 50));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<FollowUpList>(`/onboarding/follow-ups?${query.toString()}`);
}

/**
 * Record that a follow-up was dealt with.
 *
 * No actor: who completed it comes from the login session on the server. Every
 * refusal — already completed, not a follow-up, a reschedule with no date or a date
 * in the past — comes back as the server worded it, and the caller shows that rather
 * than second-guessing it.
 */
export function completeFollowUp(
  activityId: string,
  payload: CompleteFollowUpRequest,
): Promise<FollowUpCompletion> {
  return apiRequest<FollowUpCompletion>(
    `/onboarding/follow-ups/${activityId}/completion`,
    { method: 'POST', body: payload },
  );
}
