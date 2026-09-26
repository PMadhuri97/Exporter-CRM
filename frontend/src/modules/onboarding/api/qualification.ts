/**
 * Qualification — **owner: Developer 2** (L2-09, L2-10).
 *
 * The server decides everything: which outcomes the user may record, whether
 * results may be recorded, what the suggestion is. These functions only carry
 * requests and responses.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  Qualification,
  ReasonCode,
  RecordOutcomeRequest,
  RecordResultsRequest,
} from '../types';

export function getQualification(customerId: string): Promise<Qualification> {
  return apiRequest<Qualification>(`/onboarding/exporters/${customerId}/qualification`);
}

export function recordQualificationResults(
  customerId: string,
  request: RecordResultsRequest,
): Promise<Qualification> {
  return apiRequest<Qualification>(
    `/onboarding/exporters/${customerId}/qualification/results`,
    { method: 'POST', body: request },
  );
}

export function recordQualificationOutcome(
  customerId: string,
  request: RecordOutcomeRequest,
): Promise<Qualification> {
  return apiRequest<Qualification>(
    `/onboarding/exporters/${customerId}/qualification/outcome`,
    { method: 'POST', body: request },
  );
}

export function listReasonCodes(): Promise<{ reason_codes: ReasonCode[] }> {
  return apiRequest<{ reason_codes: ReasonCode[] }>('/onboarding/qualification/reason-codes');
}
