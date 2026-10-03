/**
 * Company record — **owner: Developer 2**.
 *
 * Query keys: `['exporterProfiles', params]` for lists, `['exporterProfile',
 * id]` for one company (Developer 3's engagement hooks invalidate the latter
 * too, because the detail embeds contacts and activities).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  bringExporterIntoPipeline,
  createExporterLead,
  getExporterProfileDetail,
  searchExporterProfiles,
  setExporterMarker,
  updateExporterProfile,
} from '../api';
import type {
  BringIntoPipelineRequest,
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
  // Profile, marker and qualification changes each write a history row.
  void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
}

/**
 * Invalidate everything a move of the company's journey can show up in.
 *
 * A `CLEAR` background-check decision, or a `QUALIFIED` outcome for a lead whose
 * check is already `CLEAR`, makes the company a `CUSTOMER` in the same request
 * (architecture §5). Besides the company — its header, journey chip and the lists,
 * which Home's counts and the Pipeline read too — that changes whether its deals may
 * be handed over, which the deal list and each deal's page show. A deal's page is
 * keyed by the deal alone, so every cached one is refreshed.
 */
export function invalidateJourney(
  queryClient: ReturnType<typeof useQueryClient>,
  customerId: string,
) {
  invalidateCompany(queryClient, customerId);
  void queryClient.invalidateQueries({ queryKey: ['deals', customerId] });
  void queryClient.invalidateQueries({ queryKey: ['deal'] });
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

/** Bring a buyer-only company into the sales pipeline (task 3.11). */
export function useBringIntoPipeline(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BringIntoPipelineRequest = {}) =>
      bringExporterIntoPipeline(customerId, body),
    // The journey, the gauges and the lists all change meaning at once, so the
    // whole company is invalidated rather than one query.
    onSuccess: () => invalidateCompany(queryClient, customerId),
  });
}
