/**
 * Company record — **owner: Developer 2**.
 *
 * Query keys: `['exporterProfiles', params]` for lists, `['exporterProfile',
 * id]` for one company (Developer 3's engagement hooks invalidate the latter
 * too, because the detail embeds contacts and activities).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createExporterLead,
  getExporterProfileDetail,
  searchExporterProfiles,
  setExporterMarker,
  updateExporterProfile,
} from '../api';
import type {
  ExporterSearchParams,
  SetMarkerRequest,
  UpdateExporterProfileRequest,
} from '../types';

export function useExporterProfiles(params: ExporterSearchParams) {
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

/** Invalidate everything a change to one company can show up in. */
export function invalidateCompany(
  queryClient: ReturnType<typeof useQueryClient>,
  customerId: string,
) {
  void queryClient.invalidateQueries({ queryKey: ['exporterProfile', customerId] });
  void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] });
}

export function useUpdateExporterProfile(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: UpdateExporterProfileRequest) =>
      updateExporterProfile(customerId, changes),
    onSuccess: () => invalidateCompany(queryClient, customerId),
  });
}

export function useSetExporterMarker(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: SetMarkerRequest) => setExporterMarker(customerId, request),
    onSuccess: () => invalidateCompany(queryClient, customerId),
  });
}
