/**
 * Contacts and the activity log — **owner: Developer 3**.
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
  listExporterActivities,
  listExporterContacts,
  logExporterActivity,
} from '../api';
import type {
  AddExporterContactRequest,
  ExporterActivityType,
  LogExporterActivityRequest,
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
