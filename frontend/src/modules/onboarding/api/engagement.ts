/**
 * Contacts, the activity log and the conversation gauge.
 *
 * These are the relationship's own records: who we talk to, what was said or
 * done, and how the conversation is going. They hang off the company rather than
 * any one verification pass, which is why they sit together in the engagement area
 * (architecture §9.3) rather than with the company record itself.
 *
 * The contact and activity functions were split out of the single `api/index.ts`
 * unchanged; the conversation functions came later.
 *
 * `listConversationHistory` calls the shared history route with
 * `?dimension=conversation`. The gauge writes into the one shared history log
 * (`docs/contracts/history-row.md`), so a second table of engagement's own would be
 * the duplication that contract exists to prevent — and a request function is a
 * caller, not a claim of ownership.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  Conversation,
  HistoryList,
  SetConversationRequest,
} from '../types';

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

/**
 * A partial edit: send only the fields that change.
 *
 * A key left out of `payload` is untouched; a key sent as `null` is cleared. The two
 * are different requests, so a caller building this must not fill absent fields with
 * `null` to make the object uniform. The server refuses a body with no keys at all.
 */
export function updateExporterContact(
  customerId: string,
  contactId: string,
  payload: import('../types').UpdateExporterContactRequest,
): Promise<import('../types').ExporterContact> {
  return apiRequest<import('../types').ExporterContact>(
    `/onboarding/exporters/${customerId}/contacts/${contactId}`,
    { method: 'PATCH', body: payload },
  );
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

// ── Conversation gauge ───────────────────────────────

/**
 * The gauge, the check-back date, and the moves this user may make.
 *
 * One request for all three: `allowed_moves` comes back with the value, so the
 * panel never needs a second call to know what to offer. (The server also serves
 * the moves on their own, at `/conversation/moves`, for a caller that wants
 * nothing else — this is not that caller.)
 */
export function getExporterConversation(customerId: string): Promise<Conversation> {
  return apiRequest<Conversation>(`/onboarding/exporters/${customerId}/conversation`);
}

/**
 * Move the gauge.
 *
 * No actor: who did it comes from the login session on the server, never from
 * this body. Every refusal — a reason or check-back date missing, a date in the
 * past, a move on a LEAD — comes back as the server worded it, and the caller
 * shows that rather than second-guessing it.
 */
export function setExporterConversation(
  customerId: string,
  payload: SetConversationRequest,
): Promise<Conversation> {
  return apiRequest<Conversation>(`/onboarding/exporters/${customerId}/conversation`, {
    method: 'POST',
    body: payload,
  });
}

/** This company's conversation history, newest first — the shared
 * history route, narrowed to one dimension. */
export function listConversationHistory(
  customerId: string,
  params: { limit?: number } = {},
): Promise<HistoryList> {
  const query = new URLSearchParams({ dimension: 'conversation' });
  query.set('limit', String(params.limit ?? 20));
  return apiRequest<HistoryList>(
    `/onboarding/exporters/${customerId}/history?${query.toString()}`,
  );
}
