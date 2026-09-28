/**
 * Background check — **owner: Developer 4A** (L4-03, L4-13).
 *
 * Contract: `docs/contracts/background-check.md`. Three calls, matching the three
 * routes, and nothing else.
 *
 * **The move table is not here, and neither are the roles.** `getBackgroundCheck`
 * returns `allowed_moves` for the signed-in user, and the screen offers exactly
 * those. Keeping a copy of the nine moves — or of who may make them — in the browser
 * is how a rule change leaves a button behind that 403s or 409s.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  BackgroundCheck,
  BackgroundCheckDecision,
  BackgroundCheckDecisionList,
  RecordBackgroundCheckDecisionRequest,
} from '../types';

/**
 * Where a company's check stands, and what this user may do next.
 *
 * `clear_blocked_reasons` names CLEAR's outstanding prerequisites, so the screen can
 * say what is missing instead of offering a button that answers 409.
 */
export async function getBackgroundCheck(customerId: string): Promise<BackgroundCheck> {
  return apiRequest<BackgroundCheck>(`/onboarding/exporters/${customerId}/background-check`);
}

/**
 * Record a move.
 *
 * The body carries where the check is going, why, and the risk — and nothing about
 * who is deciding. The actor comes from the session, the source and decided-by kind
 * are the server's, and the evidence snapshot is assembled server-side. Sending any
 * of them is a 422, so there is no point trying from here.
 */
export async function recordBackgroundCheckDecision(
  customerId: string,
  body: RecordBackgroundCheckDecisionRequest,
): Promise<BackgroundCheckDecision> {
  return apiRequest<BackgroundCheckDecision>(
    `/onboarding/exporters/${customerId}/background-check/decisions`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

/** Every decision on the company, newest first, each with its evidence snapshot. */
export async function listBackgroundCheckDecisions(
  customerId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<BackgroundCheckDecisionList> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  const suffix = query.toString() ? `?${query}` : '';
  return apiRequest<BackgroundCheckDecisionList>(
    `/onboarding/exporters/${customerId}/background-check/decisions${suffix}`,
  );
}
