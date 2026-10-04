/**
 * Trade history — what two companies have invoiced and how it was settled —
 * **owner: Developer 3** (allocation tasks 3.20–3.22, plan P5-3, P5-4, P5-7).
 *
 * A relationship's own paths are absolute (`/onboarding/trade-relationships/...`)
 * because a relationship belongs to a *pair* and not to either company; only the
 * list hangs off a company, which reads as what it is — the relationships *of* a
 * company, on one side.
 *
 * **There is no "get the relationship for this pair" route**, and the panel does not
 * need one: `listTradeRelationships(sellerId)` carries each counterparty's
 * `company_id`, so finding the pair is a filter on a list the deal page would be
 * fetching anyway. A route per pair would be a second way to ask the same question,
 * and the list is the one that also answers "who else does this company sell to".
 *
 * Amounts arrive as **strings** (`amount`, `amount_paid`): money is `Numeric`
 * server-side, and a JSON number would silently round it. Nothing here parses them —
 * they are formatted for display and never summed (decision IQ-4: there is no
 * reporting currency, so a total across currencies would be a lie).
 */

import { apiRequest } from '@/lib/api/client';

import type {
  DealPaymentOutcome,
  DealSide,
  RecordDealPaymentOutcomeRequest,
  RecordTradeInvoiceRequest,
  RecordTradeOutcomeRequest,
  TradeInvoice,
  TradeInvoiceDetail,
  TradeOutcome,
  TradeRelationshipDetail,
  TradeRelationshipList,
} from '../types';

/**
 * One company's trade relationships, on one side.
 *
 * `as: 'buyer'` lists who it buys from instead. Two sides, two lists, for the same
 * reason the deal lists are separate (task 2.7): a company can sell to one
 * counterparty and buy from another, and one list mixing them would read differently
 * row by row.
 */
export function listTradeRelationships(
  companyId: string,
  params: { as?: DealSide } = {},
): Promise<TradeRelationshipList> {
  const query = new URLSearchParams();
  if (params.as) query.set('as', params.as);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiRequest<TradeRelationshipList>(
    `/onboarding/exporters/${companyId}/trade-relationships${suffix}`,
  );
}

/** One relationship with its invoices, newest first, each carrying the outcome we
 * currently believe. `current_outcome` is `null` when nobody has recorded one —
 * which is not `UNKNOWN`, where somebody looked and could not say. */
export function getTradeRelationship(
  relationshipId: string,
): Promise<TradeRelationshipDetail> {
  return apiRequest<TradeRelationshipDetail>(
    `/onboarding/trade-relationships/${relationshipId}`,
  );
}

/** One invoice and its **whole** outcome chain, oldest first — every belief and when
 * it was replaced, which is what makes a corrected invoice tell its own story. */
export function getTradeInvoice(invoiceId: string): Promise<TradeInvoiceDetail> {
  return apiRequest<TradeInvoiceDetail>(`/onboarding/trade-invoices/${invoiceId}`);
}

/** Record an invoice against a relationship. Its identity is frozen the moment it is
 * written, so there is no edit — a mistake is corrected by recording the right one. */
export function recordTradeInvoice(
  relationshipId: string,
  body: RecordTradeInvoiceRequest,
): Promise<TradeInvoice> {
  return apiRequest<TradeInvoice>(
    `/onboarding/trade-relationships/${relationshipId}/invoices`,
    { method: 'POST', body },
  );
}

/** Append what we now know about an invoice. A correction passes
 * `supersedes_outcome_id`, and the server refuses anything but the chain's current
 * head — so two people cannot each correct the same outcome without seeing the
 * other's. */
export function recordTradeOutcome(
  invoiceId: string,
  body: RecordTradeOutcomeRequest,
): Promise<TradeOutcome> {
  return apiRequest<TradeOutcome>(`/onboarding/trade-invoices/${invoiceId}/outcomes`, {
    method: 'POST',
    body,
  });
}

/**
 * Record how a handed-over deal was settled (task 3.21, plan P5-6).
 *
 * Creates the deal's invoice if it has none — the four invoice fields are then
 * required together — and appends the outcome. **Not a deal stage**: handover is the
 * end of the deal's own story, and what happened to the money afterwards is a fact
 * about the trade (architecture §3.3).
 */
export function recordDealPaymentOutcome(
  dealId: string,
  body: RecordDealPaymentOutcomeRequest,
): Promise<DealPaymentOutcome> {
  return apiRequest<DealPaymentOutcome>(
    `/onboarding/deals/${dealId}/payment-outcome`,
    { method: 'POST', body },
  );
}
