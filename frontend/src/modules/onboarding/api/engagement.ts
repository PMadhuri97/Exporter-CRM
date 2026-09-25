/**
 * Contacts and the activity log — **owner: Developer 3**.
 *
 * These are the relationship's own records: who we talk to, and what was said
 * or done. They hang off the company rather than any one verification pass,
 * which is why they sit beside the conversation gauge in Developer 3's area
 * (architecture §9.3) rather than with the company record itself.
 *
 * Split out of the single `api/index.ts`; the barrel re-exports everything, so
 * no caller changed. Mechanical move — every function below is byte-identical
 * to the one it replaced.
 */

import { apiRequest } from '@/lib/api/client';

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
