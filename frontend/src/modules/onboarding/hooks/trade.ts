/**
 * React Query hooks for trade history — **owner: Developer 3** (tasks 3.20–3.22).
 *
 * Two reads the panels use, one lookup derived from the first, and the writes.
 *
 * `useTradeRelationshipForPair` is the deal page's question — "have these two traded
 * before?" — answered from the seller's list rather than from a route of its own. It
 * returns the relationship **or `null`**, and those are different answers from
 * `undefined` (still loading): a panel that cannot tell them apart flashes "nothing
 * recorded" before the data arrives, which is the one thing this panel must not say
 * wrongly.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getTradeInvoice,
  getTradeRelationship,
  listTradeRelationships,
  recordDealPaymentOutcome,
  recordTradeInvoice,
  recordTradeOutcome,
} from '../api';
import type {
  DealSide,
  RecordDealPaymentOutcomeRequest,
  RecordTradeInvoiceRequest,
  RecordTradeOutcomeRequest,
} from '../types';

export function useTradeRelationships(
  companyId: string | undefined,
  as: DealSide = 'seller',
) {
  return useQuery({
    queryKey: ['tradeRelationships', companyId, as],
    queryFn: () => listTradeRelationships(companyId!, { as }),
    enabled: Boolean(companyId),
  });
}

export function useTradeRelationship(relationshipId: string | undefined) {
  return useQuery({
    queryKey: ['tradeRelationship', relationshipId],
    queryFn: () => getTradeRelationship(relationshipId!),
    enabled: Boolean(relationshipId),
  });
}

export function useTradeInvoice(invoiceId: string | undefined) {
  return useQuery({
    queryKey: ['tradeInvoice', invoiceId],
    queryFn: () => getTradeInvoice(invoiceId!),
    enabled: Boolean(invoiceId),
  });
}

/**
 * The relationship for one ordered pair, from the seller's list.
 *
 * It reuses the `['tradeRelationships', sellerId, 'seller']` cache entry, so a deal
 * page and the seller's company page share one request. `select` narrows it, which
 * keeps the filtering out of the component and means a changed response shape is a
 * compile error here rather than a wrong row there.
 *
 * `data` is the relationship, or `null` when this pair has none — a real answer, and
 * the one every deal had before task 3.18 shipped.
 */
export function useTradeRelationshipForPair(
  sellerId: string | undefined,
  buyerId: string | undefined,
) {
  return useQuery({
    queryKey: ['tradeRelationships', sellerId, 'seller'],
    queryFn: () => listTradeRelationships(sellerId!, { as: 'seller' }),
    enabled: Boolean(sellerId && buyerId),
    select: (list) =>
      list.relationships.find((r) => r.buyer.company_id === buyerId) ?? null,
  });
}

/** Record an invoice, then refresh the relationship it belongs to and both
 * companies' lists — `invoice_count` on every row that names this pair moved. */
export function useRecordTradeInvoice(relationshipId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordTradeInvoiceRequest) =>
      recordTradeInvoice(relationshipId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tradeRelationship', relationshipId] });
      void queryClient.invalidateQueries({ queryKey: ['tradeRelationships'] });
    },
  });
}

/**
 * Record an outcome, then refresh the invoice, its relationship and the history.
 *
 * `relationshipId` is a parameter rather than something read back from the response
 * because the response is one outcome: refreshing the relationship it hangs off means
 * knowing which one, and the caller already does.
 *
 * The history invalidation is the easy one to forget — the server writes a `trade`
 * history row on the seller's timeline for every outcome, so a company page left
 * open would keep showing the timeline it loaded before.
 */
export function useRecordTradeOutcome(invoiceId: string, relationshipId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordTradeOutcomeRequest) => recordTradeOutcome(invoiceId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tradeInvoice', invoiceId] });
      void queryClient.invalidateQueries({ queryKey: ['tradeRelationship', relationshipId] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory'] });
    },
  });
}

/**
 * Record how a handed-over deal was settled (P5-6).
 *
 * Invalidates by prefix rather than by id: this one request may create a relationship
 * *and* an invoice *and* an outcome, so which keys hold stale data depends on what the
 * deal already had. The deal itself is invalidated too — not because its stage moved
 * (it does not; this is not a stage) but because its panel reads the relationship
 * through the pair.
 */
export function useRecordDealPaymentOutcome(dealId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordDealPaymentOutcomeRequest) =>
      recordDealPaymentOutcome(dealId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['deal', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['tradeRelationships'] });
      void queryClient.invalidateQueries({ queryKey: ['tradeRelationship'] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory'] });
    },
  });
}
