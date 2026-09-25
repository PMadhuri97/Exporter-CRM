/**
 * Company record and journey — **owner: Developer 2**.
 *
 * Split out of the single `api/index.ts` that carried all four developers'
 * request functions, so the company routes, the engagement routes and the
 * verification routes stop sharing one file (architecture §7.2, §8.1). The
 * barrel in `api/index.ts` re-exports everything, so no caller changed.
 *
 * Mechanical move: every function below is byte-identical to the one it
 * replaced, comments included.
 */

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

export function transitionExporterLifecycle(
  customerId: string,
  toStatus: import('../types').ExporterLifecycleStatus,
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>(`/onboarding/exporters/${customerId}/transition`, {
    method: 'POST',
    body: { to_status: toStatus },
  });
}
