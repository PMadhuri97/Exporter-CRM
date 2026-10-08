/**
 * Company record.
 *
 * The journey has no request here on purpose: it is never moved by hand. A
 * qualification outcome moves it (`api/qualification.ts`), and the move to
 * CUSTOMER will follow the background check.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  AddGstRegistrationRequest,
  AssignRelationshipManagerRequest,
  BulkReassignRequest,
  BulkReassignResult,
  PickableRole,
  StaffList,
  FlagGstRegistrationRequest,
  GstRegistration,
  GstRegistrationList,
  BringIntoPipelineRequest,
  CompanyMatch,
  CompanyMatchRequest,
  CreateExporterLeadRequest,
  ExporterProfile,
  ExporterProfileDetail,
  ExporterProfileListItem,
  ExporterSearchParams,
  IdentityCompletionList,
  SetMarkerRequest,
  UpdateExporterProfileRequest,
} from '../types';

export interface SearchExportersResult {
  profiles: ExporterProfileListItem[];
  limit: number;
  offset: number;
  /** How many companies the filters match, behind this page. */
  total: number;
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
    ['pipeline_status', params.pipeline_status],
    ['country', params.country],
    ['industry', params.industry],
    ['background_check', params.background_check],
    ['trade_role', params.trade_role],
    ['relationship_manager', params.relationship_manager],
  ];
  for (const [key, value] of entries) if (value) query.set(key, value);
  // Separately, because `false` is a filter ("companies with no open deal") and the
  // loop above drops every falsy value.
  if (params.has_open_deals !== undefined) {
    query.set('has_open_deals', String(params.has_open_deals));
  }
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
function generateIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
    bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function createExporterLead(
  payload: CreateExporterLeadRequest & { name: string; country: string },
): Promise<ExporterProfile> {
  return apiRequest<ExporterProfile>('/onboarding/exporters', {
    method: 'POST',
    body: payload,
    headers: { 'Idempotency-Key': generateIdempotencyKey() },
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

// ── Relationship manager ─────────────────────────────

/**
 * Set, change or clear the company's relationship manager. `seen_user_id` is the RM
 * the screen showed (`null` for none): if someone changed it since, the server refuses
 * (409 `RELATIONSHIP_MANAGER_CHANGED`) rather than overwrite them. Which of claim,
 * assign, change and clear this user may make is served on the company
 * (`relationship_manager_actions`); a change or clear needs a reason. Returns the
 * company's detail.
 */
export function assignRelationshipManager(
  customerId: string,
  body: AssignRelationshipManagerRequest,
): Promise<ExporterProfileDetail> {
  return apiRequest<ExporterProfileDetail>(
    `/onboarding/exporters/${customerId}/relationship-manager`,
    { method: 'POST', body },
  );
}

/** Move one RM's companies to another — all, a chosen list, or one journey stage.
 * `dry_run` reports what would move and writes nothing. ADMIN or exporters:assign_rm. */
export function reassignRelationshipManagers(body: BulkReassignRequest): Promise<BulkReassignResult> {
  return apiRequest<BulkReassignResult>('/onboarding/relationship-managers/reassign', {
    method: 'POST',
    body,
  });
}

/** Active staff in the given roles, by name, with what each already holds — the
 * picker for an RM (`OPERATIONS`) or a reviewer (`COMPLIANCE`, `ADMIN`). */
export function listStaff(roles: readonly PickableRole[]): Promise<StaffList> {
  const query = new URLSearchParams();
  for (const role of roles) query.append('role', role);
  return apiRequest<StaffList>(`/onboarding/staff?${query.toString()}`);
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

// ── "Do we already have this company?" ────────────────

/**
 * Find the company a name and identifiers belong to.
 *
 * `POST` rather than `GET` because the body carries full tax identifiers, and a
 * query string lands in access logs, browser history and every proxy in between —
 * for exactly the values the rest of the CRM masks.
 *
 * A full PAN, GSTIN or `(country, registration_number)` names the company that
 * holds it, even for a role that sees identifiers masked; the
 * response never carries an identifier back, and every such lookup is audited.
 * Partial identifiers are refused: send the whole value or none.
 */
/**
 * The companies the CRM cannot identify yet: no PAN and no registration number
 * (the identity completion list). Required gaps first. Carries no identifiers.
 */
export function listIdentityCompletion(
  params: { limit?: number; offset?: number } = {},
): Promise<IdentityCompletionList> {
  const query = new URLSearchParams();
  query.set('limit', String(params.limit ?? 50));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<IdentityCompletionList>(
    `/onboarding/companies/identity-completion?${query.toString()}`,
  );
}

export function matchCompany(body: CompanyMatchRequest): Promise<CompanyMatch> {
  return apiRequest<CompanyMatch>('/onboarding/companies/match', {
    method: 'POST',
    body,
  });
}

// ── Into the sales pipeline ──────────────────────────────────────

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

// ── GST registrations: a company's branches ─────────

/** A company's branches, newest last, deactivated ones included. */
export function listGstRegistrations(customerId: string): Promise<GstRegistrationList> {
  return apiRequest<GstRegistrationList>(
    `/onboarding/exporters/${customerId}/gst-registrations`,
  );
}

/**
 * Record a GST registration. The state is derived from the GSTIN by the server and
 * is not sent; a GSTIN another company also holds comes back in `also_held_by` as a
 * warning, never a refusal.
 */
export function addGstRegistration(
  customerId: string,
  body: AddGstRegistrationRequest,
): Promise<GstRegistration> {
  return apiRequest<GstRegistration>(
    `/onboarding/exporters/${customerId}/gst-registrations`,
    { method: 'POST', body },
  );
}

/** Stop using a branch, keeping its record. There is no delete. */
export function deactivateGstRegistration(
  registrationId: string,
  body: { reason?: string | null } = {},
): Promise<GstRegistration> {
  return apiRequest<GstRegistration>(
    `/onboarding/gst-registrations/${registrationId}/deactivate`,
    { method: 'POST', body },
  );
}

/** Flag a branch (COMPLIANCE, ADMIN). The reason is what a blocked handover says. */
export function flagGstRegistration(
  registrationId: string,
  body: FlagGstRegistrationRequest,
): Promise<GstRegistration> {
  return apiRequest<GstRegistration>(
    `/onboarding/gst-registrations/${registrationId}/flag`,
    { method: 'POST', body },
  );
}

/** Lift a branch's flag (COMPLIANCE, ADMIN). A reason is required here too. */
export function unflagGstRegistration(
  registrationId: string,
  body: FlagGstRegistrationRequest,
): Promise<GstRegistration> {
  return apiRequest<GstRegistration>(
    `/onboarding/gst-registrations/${registrationId}/unflag`,
    { method: 'POST', body },
  );
}
