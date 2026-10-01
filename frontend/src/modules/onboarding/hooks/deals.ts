/**
 * React Query hooks for deals — **owner: Developer 3B** (L3-05, L3-06).
 *
 * Created as a stub in the seam commit with its barrel line in `hooks/index.ts`,
 * and filled here, so the barrel was never opened twice.
 *
 * **Seam S2**: Developer 3A's Conversation panel calls `useOpenDeal` through the
 * barrel when the gauge is `READY_NOW`. That is why opening a deal invalidates the
 * conversation keys as well as the deal ones — see `useOpenDeal`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getDeal,
  listCompanyDeals,
  listDealRequiredDocuments,
  openDeal,
  setDealBuyer,
  setDealRequiredDocument,
  transitionDealStage,
} from '../api';
import type {
  DealListParams,
  OpenDealRequest,
  SetDealBuyerRequest,
  SetDealRequiredDocumentRequest,
  TransitionDealStageRequest,
} from '../types';

export function useCompanyDeals(
  customerId: string | undefined,
  params: DealListParams = {},
) {
  return useQuery({
    queryKey: ['deals', customerId, params],
    queryFn: () => listCompanyDeals(customerId!, params),
    enabled: Boolean(customerId),
  });
}

export function useDeal(dealId: string | undefined) {
  return useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => getDeal(dealId!),
    enabled: Boolean(dealId),
  });
}

/**
 * Open a deal, then refresh everything opening one changed.
 *
 * Four invalidations, and the third is the one worth explaining:
 *
 * - `deals` for the company — the new deal belongs in the list, and the
 *   company page's Deals tab shows the count.
 * - `exporterProfile` for the company — its `updated_at` moves.
 * - `exporterConversation` **and** `conversationHistory` for the company — the
 *   server moved the gauge to `READY_NOW` as part of this request (architecture
 *   §3.3, seam S1) and wrote a history row for it. Without these, Developer 3A's
 *   panel would keep showing the old value until something else refetched it, and
 *   the screen would disagree with the database.
 *
 * Those two key names are 3A's, copied from `hooks/engagement.ts` rather than
 * guessed: a query key is a string, so a wrong one type-checks perfectly and
 * simply never invalidates anything. Invalidating them is exactly what the seam is
 * for — the write is theirs, the cause is ours.
 */
export function useOpenDeal(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OpenDealRequest) => openDeal(customerId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['exporterConversation', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['conversationHistory', customerId],
      });
    },
  });
}

/**
 * Move a deal's stage.
 *
 * Invalidates the deal and its company's list. Not the conversation: a stage move
 * does not touch the gauge — only *opening* a deal does.
 */
export function useTransitionDealStage(dealId: string, customerId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TransitionDealStageRequest) =>
      transitionDealStage(dealId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['deal', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['dealHistory', dealId] });
      if (customerId !== undefined) {
        void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
        void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
      }
    },
  });
}

export function useSetDealBuyer(dealId: string, customerId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetDealBuyerRequest) => setDealBuyer(dealId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['deal', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['dealHistory', dealId] });
      if (customerId !== undefined) {
        // The list shows the buyer's name per row.
        void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
      }
    },
  });
}

// ── Which paperwork a handover needs (plan P2-5a) ────────────────────────────

/** The handover rule. Any CRM reader may read it; `can_edit` says who may
 * change it. */
export function useDealRequiredDocuments() {
  return useQuery({
    queryKey: ['dealRequiredDocuments'],
    queryFn: listDealRequiredDocuments,
  });
}

/**
 * Require a category before handover, or stop requiring it.
 *
 * Invalidates every `['deal', …]` entry as well as the rule itself: changing the
 * rule changes `handover_blocked_reason` on every open deal, and a page still
 * showing the old reason would be telling the user something untrue.
 */
export function useSetDealRequiredDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetDealRequiredDocumentRequest) => setDealRequiredDocument(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['dealRequiredDocuments'] });
      void queryClient.invalidateQueries({ queryKey: ['deal'] });
      void queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
}
