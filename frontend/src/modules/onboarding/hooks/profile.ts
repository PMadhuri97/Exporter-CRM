/**
 * Company record and journey — **owner: Developer 2**.
 *
 * Split out of the single `hooks/index.ts`; the barrel re-exports everything,
 * so no component changed. Mechanical move — every hook below is
 * byte-identical to the one it replaced, query keys and invalidations
 * included.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createExporterLead,
  getExporterProfileDetail,
  searchExporterProfiles,
  transitionExporterLifecycle,
} from '../api';
import type { ExporterLifecycleStatus, ExporterSearchParams } from '../types';

export function useExporterProfiles(
  params: Omit<ExporterSearchParams, 'status'>,
) {
  return useQuery({
    queryKey: ['exporterProfiles', params],
    queryFn: () => searchExporterProfiles(params),
  });
}

export function useExporterProfileDetail(customerId: string | undefined) {
  return useQuery({
    queryKey: ['exporterProfile', customerId],
    queryFn: () => getExporterProfileDetail(customerId!),
    enabled: Boolean(customerId),
  });
}

export function useCreateExporterLead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createExporterLead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] });
    },
  });
}

export function useTransitionExporterLifecycle(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (toStatus: ExporterLifecycleStatus) =>
      transitionExporterLifecycle(customerId, toStatus),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['exporterProfile', customerId],
      });
      void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] });
    },
  });
}
