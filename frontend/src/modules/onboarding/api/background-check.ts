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
  ApproveBackgroundCheckProposalResponse,
  BackgroundCheck,
  BackgroundCheckDecision,
  BackgroundCheckDecisionList,
  BackgroundCheckProposal,
  BackgroundCheckProposalList,
  CheckCycleList,
  DecisionEvidence,
  ReKycDueList,
  RecordBackgroundCheckDecisionRequest,
  StartCheckCycleRequest,
  StartCheckCycleResponse,
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
 *
 * **Maker-checker (P3-1b).** A move the server marks `approval_required` (CLEAR,
 * FLAGGED, ON_HOLD) is not recorded: the answer (202) is a **proposal**, and the check
 * moves only when a different compliance officer approves it; the screen reloads the
 * standing either way, which then shows it awaiting approval.
 */
export async function recordBackgroundCheckDecision(
  customerId: string,
  body: RecordBackgroundCheckDecisionRequest,
): Promise<BackgroundCheckDecision | BackgroundCheckProposal> {
  return apiRequest<BackgroundCheckDecision | BackgroundCheckProposal>(
    `/onboarding/exporters/${customerId}/background-check/decisions`,
    // The object itself: `apiRequest` encodes the body. Stringifying it here too
    // sent a JSON string, which the server refuses (422).
    { method: 'POST', body },
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

// ── Developer 1 (compliance engine) ────────────────────────────────────────

/** What one decision rested on, each pinned id resolved into a readable item (P2-1a). */
export async function getDecisionEvidence(
  customerId: string,
  decisionId: string,
): Promise<DecisionEvidence> {
  return apiRequest<DecisionEvidence>(
    `/onboarding/exporters/${customerId}/background-check/decisions/${decisionId}/evidence`,
  );
}

/** Every check cycle of the company, cycle 1 first (P2-3d). */
export async function listCheckCycles(customerId: string): Promise<CheckCycleList> {
  return apiRequest<CheckCycleList>(
    `/onboarding/exporters/${customerId}/background-check/cycles`,
  );
}

/**
 * Start a Re-KYC or Re-KYB (P2-3c). On a CLEAR company the server also reopens it in
 * the same request. Offer it only when `allowed_cycle_actions` lists the kind.
 */
export async function startCheckCycle(
  customerId: string,
  body: StartCheckCycleRequest,
): Promise<StartCheckCycleResponse> {
  return apiRequest<StartCheckCycleResponse>(
    `/onboarding/exporters/${customerId}/background-check/cycles`,
    { method: 'POST', body },
  );
}

// ── Developer 1: maker-checker (P3-1b/c) and Re-KYC due (P3-3c) ────────────

/** One company's proposals, newest first, each with what this user may do with it. */
export async function listBackgroundCheckProposals(
  customerId: string,
): Promise<BackgroundCheckProposalList> {
  return apiRequest<BackgroundCheckProposalList>(
    `/onboarding/exporters/${customerId}/background-check/proposals`,
  );
}

/**
 * Approve a proposal as the second officer. The server refuses the proposer (403) and
 * a proposal that is resolved or out of date (409) — the check, its latest decision or
 * its inputs moved since it was proposed.
 */
export async function approveBackgroundCheckProposal(
  customerId: string,
  proposalId: string,
): Promise<ApproveBackgroundCheckProposalResponse> {
  return apiRequest<ApproveBackgroundCheckProposalResponse>(
    `/onboarding/exporters/${customerId}/background-check/proposals/${proposalId}/approve`,
    { method: 'POST' },
  );
}

/** Reject a proposal, with a reason. Not the proposer, who withdraws instead. */
export async function rejectBackgroundCheckProposal(
  customerId: string,
  proposalId: string,
  reason: string,
): Promise<BackgroundCheckProposal> {
  return apiRequest<BackgroundCheckProposal>(
    `/onboarding/exporters/${customerId}/background-check/proposals/${proposalId}/reject`,
    { method: 'POST', body: { reason } },
  );
}

/** Withdraw one's own proposal; the reason is optional. */
export async function withdrawBackgroundCheckProposal(
  customerId: string,
  proposalId: string,
  reason: string | null,
): Promise<BackgroundCheckProposal> {
  return apiRequest<BackgroundCheckProposal>(
    `/onboarding/exporters/${customerId}/background-check/proposals/${proposalId}/withdraw`,
    { method: 'POST', body: reason ? { reason } : {} },
  );
}

/**
 * Proposals across companies (COMPLIANCE, ADMIN). `awaitingMe` leaves out the caller's
 * own — the Home card "Proposals awaiting me".
 */
export async function listOpenProposals(
  params: { awaitingMe?: boolean; limit?: number } = {},
): Promise<BackgroundCheckProposalList> {
  const query = new URLSearchParams({ status: 'open' });
  if (params.awaitingMe) query.set('awaiting', 'me');
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  return apiRequest<BackgroundCheckProposalList>(`/onboarding/background-check/proposals?${query}`);
}

/**
 * CLEAR companies whose Clear has expired or expires before `before` (default: the
 * server's Re-KYC window from now), expired first.
 */
export async function listReKycDue(
  params: { before?: string; limit?: number } = {},
): Promise<ReKycDueList> {
  const query = new URLSearchParams();
  if (params.before) query.set('before', params.before);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const suffix = query.toString() ? `?${query}` : '';
  return apiRequest<ReKycDueList>(`/onboarding/background-check/due${suffix}`);
}
