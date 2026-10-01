/**
 * Deals and buyers — **owner: Developer 3B** (L3-05, L3-06).
 *
 * Created as a stub in the seam commit, together with its
 * `export * from './deals'` line in `api/index.ts`, and filled here — so the
 * barrel, which every owner shares, was never opened twice.
 *
 * **Seam S2 lives here.** Developer 3A's Conversation panel offers to open a deal
 * when the gauge is `READY_NOW`; it imports `openDeal` and `useOpenDeal` through
 * the barrel (`../../api`, `../../hooks`), never from this file directly, and
 * defines no deal request function or deal type of its own (prompt §4.2).
 *
 * A deal's own paths are absolute (`/onboarding/deals/...`) because a deal is its
 * own thing, not a company sub-resource; only the list hangs off a company, which
 * reads as what it is — the deals *of* a company.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  Deal,
  DealList,
  DealListParams,
  DealRequiredDocument,
  DealRequiredDocuments,
  OpenDealRequest,
  SetDealBuyerRequest,
  SetDealRequiredDocumentRequest,
  TransitionDealStageRequest,
} from '../types';

/**
 * Open a deal on a company.
 *
 * Also sets the company's conversation to `READY_NOW`, server-side and in the same
 * transaction (architecture §3.3) — so a caller that shows the conversation gauge
 * has to refresh it afterwards. `useOpenDeal` does exactly that.
 *
 * No stage: a deal always starts at `OPEN`, and the request has no field for one.
 */
export function openDeal(
  companyId: string,
  body: OpenDealRequest,
): Promise<Deal> {
  return apiRequest<Deal>(`/onboarding/exporters/${companyId}/deals`, {
    method: 'POST',
    body,
  });
}

/** One company's deals, newest first. Every stage unless `stages` narrows it —
 * withdrawn and handed-over deals are part of the company's record. */
export function listCompanyDeals(
  companyId: string,
  params: DealListParams = {},
): Promise<DealList> {
  const query = new URLSearchParams();
  for (const stage of params.stages ?? []) query.append('stage', stage);
  query.set('limit', String(params.limit ?? 50));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<DealList>(
    `/onboarding/exporters/${companyId}/deals?${query.toString()}`,
  );
}

/**
 * One deal, its buyer, and the moves allowed from here.
 *
 * `allowed_stage_moves` is what this deal may do next, as data; a handover that is
 * blocked by assumption A5's guard is absent from it and
 * `handover_blocked_reason` says why, so a screen explains rather than offering a
 * button that 409s.
 */
export function getDeal(dealId: string): Promise<Deal> {
  return apiRequest<Deal>(`/onboarding/deals/${dealId}`);
}

/** Move a deal's stage. `reason` is required for `WITHDRAWN` and refused for
 * anything else — the server words every refusal, and the caller shows it. */
export function transitionDealStage(
  dealId: string,
  body: TransitionDealStageRequest,
): Promise<Deal> {
  return apiRequest<Deal>(`/onboarding/deals/${dealId}/transitions`, {
    method: 'POST',
    body,
  });
}

/** Record or replace the deal's buyer. One buyer per deal, so this is a `PUT`:
 * it replaces that one row rather than adding another. */
export function setDealBuyer(
  dealId: string,
  body: SetDealBuyerRequest,
): Promise<Deal> {
  return apiRequest<Deal>(`/onboarding/deals/${dealId}/buyer`, {
    method: 'PUT',
    body,
  });
}

// ── Which paperwork a handover needs (plan P2-5a) ────────────────────────────
//
// A settings rule about every deal, not a property of one, so its path is
// `/settings/...` like the qualification criteria. Any CRM reader may read it;
// only ADMIN may change it, which `can_edit` on the response says.

/** The requirements as they stand, and every version ever written. */
export function listDealRequiredDocuments(): Promise<DealRequiredDocuments> {
  return apiRequest<DealRequiredDocuments>(
    '/onboarding/settings/deal-required-documents',
  );
}

/**
 * Require a document category before handover, or stop requiring it.
 *
 * There is no delete: the table is append-only, so `active: false` writes a new
 * version recording that the requirement was removed, by whom and when.
 */
export function setDealRequiredDocument(
  body: SetDealRequiredDocumentRequest,
): Promise<DealRequiredDocument> {
  return apiRequest<DealRequiredDocument>(
    '/onboarding/settings/deal-required-documents',
    { method: 'POST', body },
  );
}
