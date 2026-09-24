import { apiRequest } from '@/lib/api/client';

import type {
  CreateExporterLeadRequest,
  ExporterProfile,
  ExporterProfileDetail,
  ExporterProfileListItem,
  ExporterSearchParams,
} from '../types';

interface SearchExportersResult {
  profiles: ExporterProfileListItem[];
  limit: number;
  offset: number;
}

function buildQuery(params: ExporterSearchParams): string {
  const query = new URLSearchParams();
  if (params.legalName) query.set('legal_name', params.legalName);
  if (params.gstin) query.set('gstin', params.gstin);
  if (params.pan) query.set('pan', params.pan);
  if (params.iec) query.set('iec', params.iec);
  if (params.source) query.set('source', params.source);
  if (params.status) query.set('status', params.status);
  query.set('limit', String(params.limit ?? 100));
  query.set('offset', String(params.offset ?? 0));
  return query.toString();
}

/**
 * The stage-group tabs (`STATUS_TO_STAGE_GROUP`) are a display grouping the
 * backend's `status` filter can't express directly (it's a single exact
 * match, not "any of these states") — see this module's `constants.ts`
 * docstring. Rather than firing one request per underlying status and
 * merging results, this fetches unfiltered-by-status (still filtered by
 * every other criterion) and the page groups client-side. Documented
 * simplification, not a hidden one: revisit if a `statuses` (plural)
 * backend filter is ever added and page sizes stop making a full fetch
 * reasonable.
 */
export function searchExporterProfiles(
  params: Omit<ExporterSearchParams, 'status'>,
): Promise<SearchExportersResult> {
  return apiRequest<SearchExportersResult>(
    `/onboarding/exporters?${buildQuery(params)}`,
  );
}

/**
 * `legal_name`/`incorporation_country`/`initial_user_email` must all be
 * present (the backend's `CreateExporterProfileRequest` validator rejects a
 * partial set) — this function's own parameter type requires all three for
 * the same reason, rather than leaving that rule undiscoverable until a 422.
 *
 * An `Idempotency-Key` is generated here, not left optional: the backend
 * requires the header for this path (a fresh `OnboardingRequest` row has no
 * other natural uniqueness to dedupe a retried submit against — see the
 * schema's own docstring).
 */
export function createExporterLead(
  payload: CreateExporterLeadRequest & {
    legal_name: string;
    incorporation_country: string;
    initial_user_email: string;
  },
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>('/onboarding/exporters', {
    method: 'POST',
    body: payload,
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  });
}

export function getExporterProfileDetail(
  customerId: string,
): Promise<ExporterProfileDetail> {
  return apiRequest<ExporterProfileDetail>(`/onboarding/exporters/${customerId}`);
}

export function listExporterContacts(customerId: string): Promise<{
  customer_id: string;
  contacts: import('../types').ExporterContact[];
}> {
  return apiRequest<{
    customer_id: string;
    contacts: import('../types').ExporterContact[];
  }>(`/onboarding/exporters/${customerId}/contacts`);
}

export function addExporterContact(
  customerId: string,
  payload: import('../types').AddExporterContactRequest,
): Promise<import('../types').ExporterContact> {
  return apiRequest<import('../types').ExporterContact>(`/onboarding/exporters/${customerId}/contacts`, {
    method: 'POST',
    body: payload,
  });
}

export function listExporterActivities(
  customerId: string,
  params: {
    activityType?: import('../types').ExporterActivityType;
    limit?: number;
    offset?: number;
  } = {},
): Promise<{
  customer_id: string;
  activities: import('../types').ExporterActivity[];
}> {
  const query = new URLSearchParams();
  if (params.activityType) query.set('activity_type', params.activityType);
  query.set('limit', String(params.limit ?? 10));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<{
    customer_id: string;
    activities: import('../types').ExporterActivity[];
  }>(`/onboarding/exporters/${customerId}/activities?${query.toString()}`);
}

export function logExporterActivity(
  customerId: string,
  payload: import('../types').LogExporterActivityRequest,
): Promise<import('../types').ExporterActivity> {
  return apiRequest<import('../types').ExporterActivity>(`/onboarding/exporters/${customerId}/activities`, {
    method: 'POST',
    body: payload,
  });
}


export function transitionExporterLifecycle(
  customerId: string,
  toStatus: import('../types').ExporterLifecycleStatus,
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>(`/onboarding/exporters/${customerId}/transition`, {
    method: 'POST',
    body: { to_status: toStatus },
  });
}

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

/**
 * Read-only: the document types this profile will be asked for, from the
 * GitOps-managed policy. Nothing stores a document yet, so there is no status
 * per document and no upload counterpart to this call — see the backend's
 * `document_requirements_router.py` module docstring.
 */
export function getDocumentRequirements(
  params: import('../types').DocumentRequirementsParams,
): Promise<import('../types').DocumentRequirementsResponse> {
  const query = new URLSearchParams({
    entity_type: params.entityType,
    registration_country: params.registrationCountry,
  });
  if (params.sectorCode) query.set('sector_code', params.sectorCode);
  if (params.corridorIntent) query.set('corridor_intent', params.corridorIntent);
  if (params.declaredMonthlyVolumeUsd !== undefined) {
    query.set('declared_monthly_volume_usd', String(params.declaredMonthlyVolumeUsd));
  }
  return apiRequest<import('../types').DocumentRequirementsResponse>(
    `/onboarding/document-requirements?${query.toString()}`,
  );
}
