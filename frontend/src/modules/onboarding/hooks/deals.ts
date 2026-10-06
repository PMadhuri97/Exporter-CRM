/**
 * React Query hooks for deals.
 *
 * Created as a stub with its barrel line in `hooks/index.ts`,
 * and filled here, so the barrel was never opened twice.
 *
 * **Seam S2**: the Conversation panel calls `useOpenDeal` through the
 * barrel when the gauge is `READY_NOW`. That is why opening a deal invalidates the
 * conversation keys as well as the deal ones — see `useOpenDeal`.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import {
  getDeal,
  listAllDeals,
  listCompanyDeals,
  listDealRequiredDocuments,
  openDeal,
  setDealBuyer,
  setDealInvoicingBranch,
  setDealRequiredDocument,
  transitionDealStage,
} from '../api';
import type {
  AllDealsParams,
  DealListParams,
  OpenDealRequest,
  SetDealBuyerRequest,
  SetDealInvoicingBranchRequest,
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

/** Every deal, across companies. A changed filter keeps the rows on screen until the
 * answer arrives, as the Companies list does. */
export function useAllDeals(params: AllDealsParams) {
  return useQuery({
    queryKey: ['allDeals', params],
    queryFn: () => listAllDeals(params),
    placeholderData: keepPreviousData,
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
 * Four groups of invalidations, and the third is the one worth explaining:
 *
 * - `deals` for the company — the new deal belongs in the list, and the
 *   company page's Deals tab shows the count. `allDeals` too: the Deals page lists
 *   every company's.
 * - `exporterProfile` for the company — its `updated_at` moves.
 * - `exporterConversation` **and** `conversationHistory` for the company — the
 *   server moved the gauge to `READY_NOW` as part of this request (architecture
 *   §3.3, seam S1) and wrote a history row for it. Without these, the Conversation
 *   panel would keep showing the old value until something else refetched it, and
 *   the screen would disagree with the database.
 *
 * Those two key names are engagement's, copied from `hooks/engagement.ts` rather than
 * guessed: a query key is a string, so a wrong one type-checks perfectly and
 * simply never invalidates anything. Invalidating them is exactly what the seam is
 * for — the write is theirs, the cause is ours.
 */
export function useOpenDeal(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OpenDealRequest) => openDeal(customerId, body),
    onSuccess: () => invalidateAfterOpening(queryClient, customerId),
  });
}

/**
 * Open a deal on a company chosen at the time — the Deals page's *New deal*, where
 * the seller is picked in the form rather than known when the hook is created.
 * The same request and the same invalidations as `useOpenDeal`.
 */
export function useOpenDealOnCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, body }: { companyId: string; body: OpenDealRequest }) =>
      openDeal(companyId, body),
    onSuccess: (_deal, { companyId }) => invalidateAfterOpening(queryClient, companyId),
  });
}

function invalidateAfterOpening(queryClient: QueryClient, customerId: string) {
  void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
  void queryClient.invalidateQueries({ queryKey: ['allDeals'] });
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
      // The Deals page shows each deal's stage.
      void queryClient.invalidateQueries({ queryKey: ['allDeals'] });
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
    onSuccess: (_deal, body) => {
      void queryClient.invalidateQueries({ queryKey: ['deal', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['dealHistory', dealId] });
      // The Deals page shows the buyer and the corridor it decides.
      void queryClient.invalidateQueries({ queryKey: ['allDeals'] });
      if (body.create) {
        // A company was created: it now exists for every company search.
        void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] });
      }
      if (customerId !== undefined) {
        // The list shows the buyer's name per row.
        void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
      }
    },
  });
}

/**
 * Record, change or clear the deal's invoicing branch.
 *
 * The response is the deal as this user reads it, so it replaces the cached one at
 * once: the select shows the new branch without snapping back while a refetch runs,
 * and `handover_blocked_reason` — which the branch is one of the guard's questions
 * about — is current as soon as the request returns. History gains a row on the deal
 * and on the seller's timeline.
 */
export function useSetDealInvoicingBranch(dealId: string, customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetDealInvoicingBranchRequest) => setDealInvoicingBranch(dealId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(['deal', dealId], updated);
      void queryClient.invalidateQueries({ queryKey: ['dealHistory', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
    },
  });
}

// ── Which paperwork a handover needs ────────────────────────────

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
