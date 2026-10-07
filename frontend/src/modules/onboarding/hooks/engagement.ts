/**
 * Contacts and the activity log.
 *
 * Split out of the single `hooks/index.ts`; the barrel re-exports everything,
 * so no component changed. Mechanical move — every hook below is
 * byte-identical to the one it replaced, query keys and invalidations
 * included.
 *
 * Both mutations invalidate the company detail as well as their own list,
 * because the detail response embeds contacts and recent activities. That
 * coupling is existing behaviour and is preserved exactly.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addExporterContact,
  updateExporterContact,
  getExporterConversation,
  listConversationHistory,
  listExporterActivities,
  listExporterContacts,
  logExporterActivity,
  setExporterConversation,
} from '../api';
import type {
  AddExporterContactRequest,
  ExporterActivityType,
  LogExporterActivityRequest,
  SetConversationRequest,
  UpdateExporterContactRequest,
} from '../types';

export function useExporterContacts(customerId: string | undefined) {
  return useQuery({
    queryKey: ['exporterContacts', customerId],
    queryFn: () => listExporterContacts(customerId!),
    enabled: Boolean(customerId),
  });
}

export function useAddExporterContact(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddExporterContactRequest) =>
      addExporterContact(customerId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['exporterContacts', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
    },
  });
}

export function useUpdateExporterContact(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      contactId,
      payload,
    }: {
      contactId: string;
      payload: UpdateExporterContactRequest;
    }) => updateExporterContact(customerId, contactId, payload),
    onSuccess: () => {
      // Both, as adding does: the contact list, and the profile — which embeds the
      // contacts and carries the primary one, so promoting somebody here changes it.
      void queryClient.invalidateQueries({
        queryKey: ['exporterContacts', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
    },
  });
}

export function useExporterActivities(
  customerId: string | undefined,
  params: { activityType?: ExporterActivityType; limit: number; offset: number },
) {
  return useQuery({
    queryKey: ['exporterActivities', customerId, params],
    queryFn: () => listExporterActivities(customerId!, params),
    enabled: Boolean(customerId),
  });
}

export function useLogExporterActivity(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LogExporterActivityRequest) =>
      logExporterActivity(customerId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['exporterActivities', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
    },
  });
}

// ── Conversation gauge ───────────────────────────────

export function useExporterConversation(customerId: string | undefined) {
  return useQuery({
    queryKey: ['exporterConversation', customerId],
    queryFn: () => getExporterConversation(customerId!),
    enabled: Boolean(customerId),
  });
}

export function useConversationHistory(customerId: string | undefined) {
  return useQuery({
    queryKey: ['conversationHistory', customerId],
    queryFn: () => listConversationHistory(customerId!),
    enabled: Boolean(customerId),
  });
}

/**
 * Move the gauge, then refresh what the move changed.
 *
 * Four invalidations, each for a reason:
 *
 * - `exporterConversation` — the value **and** the moves now available from it,
 *   which are different after every move.
 * - `conversationHistory` — the move just added a row.
 * - `followUps` — moving to or away from NOT_NOW adds or removes a check-back on
 *   the Follow-ups page. Engagement's own key.
 * - `exporterProfile` — the company's record changed. The company response does
 *   not carry the gauge today, but its `updated_at` does move, and any view built
 *   on that key should not show a stale record. This is the company record's query key,
 *   invalidated from an engagement mutation; the barrel's docstring notes that the
 *   engagement mutations already do this, and it is the existing convention rather
 *   than a new coupling.
 */
export function useSetExporterConversation(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SetConversationRequest) =>
      setExporterConversation(customerId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['exporterConversation', customerId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['conversationHistory', customerId],
      });
      void queryClient.invalidateQueries({ queryKey: ['followUps'] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
    },
  });
}
