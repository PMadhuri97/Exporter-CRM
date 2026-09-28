/**
 * Qualification — **owner: Developer 2** (L2-09, L2-10).
 *
 * The server decides everything: which outcomes the user may record, whether
 * results may be recorded, what the suggestion is. These functions only carry
 * requests and responses.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  CreateCriterionRequest,
  Criterion,
  CriterionDefinitionRequest,
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

// ── Criteria (ADMIN writes; every staff role and DEVELOPER may read) ──

/** The current version of every criterion, active or not. */
export function listCriteria(): Promise<{ criteria: Criterion[] }> {
  return apiRequest<{ criteria: Criterion[] }>('/onboarding/qualification/criteria');
}

/** Add a criterion as version 1. 409 `QUALIFICATION_CRITERION_EXISTS` if the key is taken. */
export function createCriterion(request: CreateCriterionRequest): Promise<Criterion> {
  return apiRequest<Criterion>('/onboarding/qualification/criteria', {
    method: 'POST',
    body: request,
  });
}

/** Every version of one criterion, oldest first. */
export function listCriterionVersions(key: string): Promise<{ criteria: Criterion[] }> {
  return apiRequest<{ criteria: Criterion[] }>(
    `/onboarding/qualification/criteria/${encodeURIComponent(key)}/versions`,
  );
}

/**
 * Add the next version of a criterion — the only way one changes, label
 * included. 409 `QUALIFICATION_CRITERION_CHANGED` if someone else added a
 * version first.
 */
export function addCriterionVersion(
  key: string,
  request: CriterionDefinitionRequest,
): Promise<Criterion> {
  return apiRequest<Criterion>(
    `/onboarding/qualification/criteria/${encodeURIComponent(key)}/versions`,
    { method: 'POST', body: request },
  );
}
