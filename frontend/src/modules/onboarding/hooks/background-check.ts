/**
 * React Query hooks for the background check — **owner: Developer 4A** (L4-03, L4-13).
 *
 * Recording a decision invalidates **both** the standing and the decision list: the
 * standing carries `allowed_moves`, so a stale copy would keep offering the move that
 * was just made. It also invalidates the company and its deals: a `CLEAR` makes a
 * prospect a `CUSTOMER` in the same request, and any move changes whether its deals
 * may be handed over. A **refused** decision reloads the standing too — a 409 usually
 * means the check moved under the screen, and the moves on offer should be the
 * current ones.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  approveBackgroundCheckProposal,
  getBackgroundCheck,
  getDecisionEvidence,
  listBackgroundCheckDecisions,
  listBackgroundCheckProposals,
  listCheckCycles,
  listOpenProposals,
  listReKycDue,
  recordBackgroundCheckDecision,
  rejectBackgroundCheckProposal,
  startCheckCycle,
  withdrawBackgroundCheckProposal,
} from '../api';
import type { RecordBackgroundCheckDecisionRequest, StartCheckCycleRequest } from '../types';

import { invalidateJourney } from './profile';

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
      // offering the move that was just made. A proposal (CLEAR, FLAGGED, ON_HOLD)
      // changes it too: the check is now awaiting approval.
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: decisionsKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: proposalsKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: PROPOSAL_QUEUE_KEY });
      // The header, journey chip, lists, deals' handover state and the history
      // timeline (the gauge is part of the company's story) change too.
      invalidateJourney(queryClient, customerId);
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
    },
  });
}

// ── Developer 1 (compliance engine) ────────────────────────────────────────

const proposalsKey = (customerId: string) => ['backgroundCheckProposals', customerId] as const;
/** Every cross-company proposal read (the Home queue), whatever its parameters. */
const PROPOSAL_QUEUE_KEY = ['backgroundCheckProposalQueue'] as const;
/** Every Re-KYC due read, whatever its parameters. */
const REKYC_DUE_KEY = ['reKycDue'] as const;

const cyclesKey = (customerId: string) => ['checkCycles', customerId] as const;

/** One decision's evidence, resolved — fetched only while `enabled` (a row is open). */
export function useDecisionEvidence(customerId: string, decisionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['decisionEvidence', customerId, decisionId],
    queryFn: () => getDecisionEvidence(customerId, decisionId),
    enabled: enabled && Boolean(customerId) && Boolean(decisionId),
    // What a decision rested on never changes; only `review_superseded` can.
    staleTime: 60_000,
  });
}

/** The company's check cycles, cycle 1 first. */
export function useCheckCycles(customerId: string | undefined) {
  return useQuery({
    queryKey: cyclesKey(customerId ?? ''),
    queryFn: () => listCheckCycles(customerId as string),
    enabled: Boolean(customerId),
  });
}

/**
 * Start a Re-KYC / Re-KYB. A new cycle changes what every compliance read shows —
 * the standing (and on a CLEAR company the gauge), the decisions, the checklist and
 * the results grouped by cycle — and on a CLEAR company the deals' handover state and
 * the Home "Re-KYC due" list, which the reopened company leaves.
 */
export function useStartCheckCycle(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StartCheckCycleRequest) => startCheckCycle(customerId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: decisionsKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: cyclesKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: ['screeningReview', customerId] });
      void queryClient.invalidateQueries({
        queryKey: ['verificationResults', 'EXPORTER', customerId],
      });
      void queryClient.invalidateQueries({ queryKey: REKYC_DUE_KEY });
      invalidateJourney(queryClient, customerId);
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
    },
  });
}

// ── Maker-checker (P3-1b/c) and Re-KYC due (P3-3c) ─────────────────────────

/** One company's proposals, newest first. */
export function useBackgroundCheckProposals(customerId: string | undefined) {
  return useQuery({
    queryKey: proposalsKey(customerId ?? ''),
    queryFn: () => listBackgroundCheckProposals(customerId as string),
    enabled: Boolean(customerId),
  });
}

/** Open proposals this user may act on — the Home card "Proposals awaiting me". */
export function useProposalsAwaitingMe(params: { limit?: number; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: [...PROPOSAL_QUEUE_KEY, 'awaiting-me', params.limit ?? null],
    queryFn: () => listOpenProposals({ awaitingMe: true, limit: params.limit }),
    enabled: params.enabled ?? true,
  });
}

/** Companies whose Clear has expired or soon will — the Home card "Re-KYC due". */
export function useReKycDue(params: { limit?: number; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: [...REKYC_DUE_KEY, params.limit ?? null],
    queryFn: () => listReKycDue({ limit: params.limit }),
    enabled: params.enabled ?? true,
  });
}

export type ProposalResolution =
  | { kind: 'APPROVE' }
  | { kind: 'REJECT'; reason: string }
  | { kind: 'WITHDRAW'; reason: string | null };

/**
 * Approve, reject or withdraw a proposal. Approval writes the decision — a CLEAR can
 * make a prospect a CUSTOMER — so everything about the company is reloaded, and so are
 * the Home queue and the Re-KYC list. A refusal (stale, already resolved) reloads the
 * standing and the queue too, so the screen shows what is actually there.
 */
export function useResolveBackgroundCheckProposal(customerId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
    void queryClient.invalidateQueries({ queryKey: proposalsKey(customerId) });
    void queryClient.invalidateQueries({ queryKey: PROPOSAL_QUEUE_KEY });
  };
  return useMutation({
    mutationFn: async ({
      proposalId,
      resolution,
    }: {
      proposalId: string;
      resolution: ProposalResolution;
    }): Promise<unknown> => {
      switch (resolution.kind) {
        case 'APPROVE':
          return approveBackgroundCheckProposal(customerId, proposalId);
        case 'REJECT':
          return rejectBackgroundCheckProposal(customerId, proposalId, resolution.reason);
        case 'WITHDRAW':
          return withdrawBackgroundCheckProposal(customerId, proposalId, resolution.reason);
      }
    },
    onSuccess: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: decisionsKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: REKYC_DUE_KEY });
      invalidateJourney(queryClient, customerId);
    },
    onError: refresh,
  });
}
