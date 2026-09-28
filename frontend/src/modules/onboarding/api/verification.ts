/**
 * Verification results, the screening checklist and bank activity —
 * **owner: Developer 4**.
 *
 * Everything the background-check gauge reads or writes (architecture §9.4).
 * The screening checklist here is the eight-item *compliance* list, not the
 * sales qualification gauge — a distinction §5.5 calls out precisely because
 * the two are easy to confuse and must never share a table.
 *
 * Split out of the single `api/index.ts`; the barrel re-exports everything, so
 * no caller changed. Mechanical move — every function below is byte-identical
 * to the one it replaced, except `getScreeningItemHistory`, which Developer 4B
 * added for the checklist's per-item history (4b-task.md §5.6, 4B-7).
 */

import { apiRequest } from '@/lib/api/client';

export function listVerificationResults(
  entityType: import('../types').VerificationEntityType,
  entityReference: string,
): Promise<import('../types').VerificationResultList> {
  const query = new URLSearchParams({
    entity_type: entityType,
    entity_reference: entityReference,
  });
  return apiRequest<import('../types').VerificationResultList>(
    `/onboarding/verifications?${query.toString()}`,
  );
}

export function triggerVerification(
  payload: import('../types').TriggerVerificationRequest,
): Promise<import('../types').VerificationResult> {
  return apiRequest<import('../types').VerificationResult>('/onboarding/verifications', {
    method: 'POST',
    body: payload,
  });
}

export function reviewVerification(
  verificationResultId: string,
  payload: import('../types').RecordVerificationReviewRequest,
): Promise<import('../types').VerificationResult> {
  return apiRequest<import('../types').VerificationResult>(
    `/onboarding/verifications/${verificationResultId}/review`,
    { method: 'POST', body: payload },
  );
}

export function getScreeningReview(
  customerId: string,
): Promise<import('../types').ScreeningReviewList> {
  return apiRequest<import('../types').ScreeningReviewList>(
    `/onboarding/exporters/${customerId}/screening-review`,
  );
}

/** Every decision recorded on one checklist item, newest first, one page. */
export function getScreeningItemHistory(
  customerId: string,
  itemKey: string,
  params: { limit?: number; offset?: number } = {},
): Promise<import('../types').ScreeningItemHistory> {
  const query = new URLSearchParams({
    limit: String(params.limit ?? 50),
    offset: String(params.offset ?? 0),
  });
  return apiRequest<import('../types').ScreeningItemHistory>(
    `/onboarding/exporters/${customerId}/screening-review/${encodeURIComponent(itemKey)}/history?${query.toString()}`,
  );
}

export function updateScreeningReviewItem(
  customerId: string,
  itemKey: string,
  payload: {
    status: import('../types').ScreeningChecklistStatus;
    comment: string | null;
  },
): Promise<import('../types').ScreeningReviewItem> {
  return apiRequest<import('../types').ScreeningReviewItem>(
    `/onboarding/exporters/${customerId}/screening-review/${encodeURIComponent(itemKey)}`,
    { method: 'PUT', body: payload },
  );
}

export function getBankActivity(
  customerId: string,
): Promise<import('../types').BankActivityResponse> {
  return apiRequest<import('../types').BankActivityResponse>(
    `/onboarding/exporters/${customerId}/bank-activity`,
  );
}
