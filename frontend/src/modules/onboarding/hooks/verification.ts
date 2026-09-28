/**
 * Verification results, the screening checklist and bank activity —
 * **owner: Developer 4**.
 *
 * Split out of the single `hooks/index.ts`; the barrel re-exports everything,
 * so no component changed. Mechanical move — every hook below is
 * byte-identical to the one it replaced, query keys and invalidations
 * included — except `useScreeningItemHistory`, added by Developer 4B (4B-7).
 * Recording a decision invalidates the item histories too, so an open history
 * shows the new decision.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

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
} from '../types';

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
    },
  });
}

export function useScreeningReview(customerId: string | undefined) {
  return useQuery({
    queryKey: ['screeningReview', customerId],
    queryFn: () => getScreeningReview(customerId!),
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
    }: {
      itemKey: string;
      status: ScreeningChecklistStatus;
      comment: string | null;
    }) => updateScreeningReviewItem(customerId, itemKey, { status, comment }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['screeningReview', customerId] });
      void queryClient.invalidateQueries({ queryKey: ['screeningItemHistory', customerId] });
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
