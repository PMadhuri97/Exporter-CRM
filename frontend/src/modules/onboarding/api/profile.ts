/**
 * Company record — **owner: Developer 2**.
 *
 * The journey has no request here on purpose: it is never moved by hand. A
 * qualification outcome moves it (`api/qualification.ts`), and the move to
 * CUSTOMER will follow the background check (L2-11).
 */

import { apiRequest } from '@/lib/api/client';

import type {
  CreateExporterLeadRequest,
  ExporterProfile,
  ExporterProfileDetail,
  ExporterProfileListItem,
  ExporterSearchParams,
  SetMarkerRequest,
  UpdateExporterProfileRequest,
} from '../types';

export interface SearchExportersResult {
  profiles: ExporterProfileListItem[];
  limit: number;
  offset: number;
}

function buildQuery(params: ExporterSearchParams): string {
  const query = new URLSearchParams();
  const entries: [string, string | undefined][] = [
    ['name', params.name],
    ['gstin', params.gstin],
    ['pan', params.pan],
    ['iec', params.iec],
    ['source', params.source],
    ['journey', params.journey],
    ['qualification', params.qualification],
    ['marker', params.marker],
  ];
  for (const [key, value] of entries) if (value) query.set(key, value);
  query.set('limit', String(params.limit ?? 100));
  query.set('offset', String(params.offset ?? 0));
  return query.toString();
}

/**
 * Filters run on the server — journey, qualification and marker included.
 * The server also decides that ENDED companies leave the default list and
 * come back for a search or `marker=ENDED`; nothing here re-implements that.
 */
export function searchExporterProfiles(
  params: ExporterSearchParams,
): Promise<SearchExportersResult> {
  return apiRequest<SearchExportersResult>(`/onboarding/exporters?${buildQuery(params)}`);
}

/**
 * Creates a named company. `name` and `country` are required together — the
 * backend refuses one without the other — so this function's parameter type
 * requires both rather than leaving that rule undiscoverable until a 422. The
 * creator's own contact is never sent: the backend takes it from the session.
 *
 * An `Idempotency-Key` is generated here, not left optional: the backend
 * requires the header for a named company, so a retried submit returns the
 * first company instead of creating a second.
 */
export function createExporterLead(
  payload: CreateExporterLeadRequest & { name: string; country: string },
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>('/onboarding/exporters', {
    method: 'POST',
    body: payload,
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  });
}

export function getExporterProfileDetail(customerId: string): Promise<ExporterProfileDetail> {
  return apiRequest<ExporterProfileDetail>(`/onboarding/exporters/${customerId}`);
}

/** Only the fields in `changes` are touched; a field sent as `null` is cleared. */
export function updateExporterProfile(
  customerId: string,
  changes: UpdateExporterProfileRequest,
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>(`/onboarding/exporters/${customerId}`, {
    method: 'PATCH',
    body: changes,
  });
}

export function setExporterMarker(
  customerId: string,
  request: SetMarkerRequest,
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>(`/onboarding/exporters/${customerId}/marker`, {
    method: 'POST',
    body: request,
  });
}
