/**
 * Verification results, the screening checklist and bank activity —
 * **owner: Developer 4**.
 *
 * Split out of the single `hooks/index.ts`; the barrel re-exports everything,
 * so no component changed. Mechanical move — every hook below is
 * byte-identical to the one it replaced, query keys and invalidations
 * included — except `useScreeningItemHistory`, added by Developer 4B (4B-7).
 * Recording a decision invalidates the item histories too, so an open history
 * shows the new decision. Every write also refreshes what it feeds
 * (`invalidateWhatAWriteFeeds`).
 */

import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getBankActivity,
  getScreeningItemHistory,
  getScreeningReview,
  listVerificationResults,
  reviewVerification,
  triggerVerification,
  updateScreeningReviewItem,
} from '../api';
import type {
  RecordVerificationReviewRequest,
  ScreeningChecklistStatus,
  TriggerVerificationRequest,
  VerificationEntityType,
  VerificationEvidenceRef,
} from '../types';

/**
 * What a verification or screening write changes beyond its own list (Developer 4B).
 *
 * A company's results and screening decisions are the inputs to its background
 * check (background-check.md §12), and Developer 4A's panel shows what still blocks `CLEAR` —
 * and disables `CLEAR` — from the `['backgroundCheck', id]` query. Without this, a
 * finished checklist or an accepted review left `CLEAR` disabled until the page was
 * reloaded. Each write also adds a history row: on the company for an `EXPORTER`
 * subject, on the deal's company and deal for a `BUYER` (whose ids this hook does not
 * know, so every history list refreshes). DIRECTOR, INVOICE, VESSEL and SHIPMENT
 * subjects feed neither (D15).
 *
 * The keys are Developer 4A's (`hooks/background-check.ts`) and Developer 1's
 * (`hooks/history.ts`), used as prefixes.
 */
function invalidateWhatAWriteFeeds(
  queryClient: QueryClient,
  entityType: VerificationEntityType,
  entityReference: string,
) {
  if (entityType === 'EXPORTER') {
    void queryClient.invalidateQueries({ queryKey: ['backgroundCheck', entityReference] });
    void queryClient.invalidateQueries({ queryKey: ['companyHistory', entityReference] });
  } else if (entityType === 'BUYER') {
    void queryClient.invalidateQueries({ queryKey: ['companyHistory'] });
    void queryClient.invalidateQueries({ queryKey: ['dealHistory'] });
  }
}

export function useVerificationResults(
  entityType: VerificationEntityType,
  entityReference: string | undefined,
) {
  return useQuery({
    queryKey: ['verificationResults', entityType, entityReference],
    queryFn: () => listVerificationResults(entityType, entityReference!),
    enabled: Boolean(entityReference),
  });
}

export function useTriggerVerification(
  entityType: VerificationEntityType,
  entityReference: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<TriggerVerificationRequest, 'entity_type' | 'entity_reference'>) =>
      triggerVerification({
        ...payload,
        entity_type: entityType,
        entity_reference: entityReference,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['verificationResults', entityType, entityReference],
      });
      invalidateWhatAWriteFeeds(queryClient, entityType, entityReference);
    },
  });
}

export function useReviewVerification(
  entityType: VerificationEntityType,
  entityReference: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      verificationResultId,
      payload,
    }: {
      verificationResultId: string;
      payload: RecordVerificationReviewRequest;
    }) => reviewVerification(verificationResultId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['verificationResults', entityType, entityReference],
      });
      invalidateWhatAWriteFeeds(queryClient, entityType, entityReference);
    },
  });
}

/** The checklist in the current check cycle, or in `cycleId` (read-only; P2-3d). */
export function useScreeningReview(customerId: string | undefined, cycleId?: string) {
  return useQuery({
    queryKey: ['screeningReview', customerId, cycleId ?? 'current'],
    queryFn: () => getScreeningReview(customerId!, cycleId),
    enabled: Boolean(customerId),
  });
}

export function useUpdateScreeningReviewItem(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      itemKey,
      status,
      comment,
      evidenceRefs = [],
    }: {
      itemKey: string;
      status: ScreeningChecklistStatus;
      comment: string | null;
      /** Optional evidence (P2-1b, IQ-14). */
      evidenceRefs?: VerificationEvidenceRef[];
    }) =>
      updateScreeningReviewItem(customerId, itemKey, {
        status,
        comment,
        ...(evidenceRefs.length > 0 ? { evidence_refs: evidenceRefs } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['screeningReview', customerId] });
      void queryClient.invalidateQueries({ queryKey: ['screeningItemHistory', customerId] });
      // A screening decision is a background-check input on the company (D9 history row).
      invalidateWhatAWriteFeeds(queryClient, 'EXPORTER', customerId);
    },
  });
}

/** One page of an item's decision history, fetched only while `enabled`. */
export function useScreeningItemHistory(
  customerId: string,
  itemKey: string,
  { limit, offset, enabled }: { limit: number; offset: number; enabled: boolean },
) {
  return useQuery({
    queryKey: ['screeningItemHistory', customerId, itemKey, limit, offset],
    queryFn: () => getScreeningItemHistory(customerId, itemKey, { limit, offset }),
    enabled,
  });
}

export function useBankActivity(customerId: string | undefined) {
  return useQuery({
    queryKey: ['bankActivity', customerId],
    queryFn: () => getBankActivity(customerId!),
    enabled: Boolean(customerId),
  });
}
