/**
 * Company record — **owner: Developer 2**.
 *
 * The journey has no request here on purpose: it is never moved by hand. A
 * qualification outcome moves it (`api/qualification.ts`), and the move to
 * CUSTOMER will follow the background check (L2-11).
 */

import { apiRequest } from '@/lib/api/client';

import type {
  BringIntoPipelineRequest,
  CompanyMatch,
  CompanyMatchRequest,
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

// ── "Do we already have this company?" (task 3.10, plan P4-3) ────────────────

/**
 * Find the company a name and identifiers belong to.
 *
 * `POST` rather than `GET` because the body carries full tax identifiers, and a
 * query string lands in access logs, browser history and every proxy in between —
 * for exactly the values the rest of the CRM masks.
 *
 * A full PAN, GSTIN or `(country, registration_number)` names the company that
 * holds it, even for a role that sees identifiers masked (decision BQ-2); the
 * response never carries an identifier back, and every such lookup is audited.
 * Partial identifiers are refused: send the whole value or none.
 */
export function matchCompany(body: CompanyMatchRequest): Promise<CompanyMatch> {
  return apiRequest<CompanyMatch>('/onboarding/companies/match', {
    method: 'POST',
    body,
  });
}

// ── Into the sales pipeline (task 3.11) ──────────────────────────────────────

/**
 * Bring a buyer-only company into the sales pipeline: the one way in.
 *
 * A company that exists only because it was somebody's buyer is
 * `NOT_IN_PIPELINE` — kept out of the working list and of pipeline counts, and
 * refused by qualification and the conversation gauge. This sets
 * `pipeline_status` to `IN_PIPELINE` and starts the company's journey history at
 * `LEAD`; from then on it is an ordinary lead.
 *
 * A company already in the pipeline is a 409: there is nothing to do, and a
 * second call would append a second `LEAD` row, making the history read as a
 * restart.
 */
export function bringExporterIntoPipeline(
  customerId: string,
  body: BringIntoPipelineRequest = {},
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>(`/onboarding/exporters/${customerId}/pipeline`, {
    method: 'POST',
    body,
  });
}
