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
  getBackgroundCheck,
  getDecisionEvidence,
  listBackgroundCheckDecisions,
  listCheckCycles,
  recordBackgroundCheckDecision,
  startCheckCycle,
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
      // offering the move that was just made.
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
      void queryClient.invalidateQueries({ queryKey: decisionsKey(customerId) });
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
 * the results grouped by cycle — and on a CLEAR company the deals' handover state.
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
      invalidateJourney(queryClient, customerId);
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: backgroundCheckKey(customerId) });
    },
  });
}
