/**
 * Company record — **owner: Developer 2**.
 *
 * Query keys: `['exporterProfiles', params]` for lists, `['exporterProfile',
 * id]` for one company (Developer 3's engagement hooks invalidate the latter
 * too, because the detail embeds contacts and activities).
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addGstRegistration,
  deactivateGstRegistration,
  flagGstRegistration,
  listGstRegistrations,
  unflagGstRegistration,
  bringExporterIntoPipeline,
  createExporterLead,
  getExporterProfileDetail,
  listIdentityCompletion,
  searchExporterProfiles,
  setExporterMarker,
  updateExporterProfile,
} from '../api';
import type {
  AddGstRegistrationRequest,
  BringIntoPipelineRequest,
  ExporterSearchParams,
  SetMarkerRequest,
  UpdateExporterProfileRequest,
} from '../types';

/** IQ-7's completion list (R-28). Keyed under `exporterProfiles` so an edit that
 * completes a company — which invalidates the company queries — refreshes it too. */
export function useIdentityCompletion(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ['exporterProfiles', 'identityCompletion', params],
    queryFn: () => listIdentityCompletion(params),
  });
}

export function useExporterProfiles(params: ExporterSearchParams) {
  return useQuery({
    queryKey: ['exporterProfiles', params],
    queryFn: () => searchExporterProfiles(params),
    // A changed filter or a longer page keeps the rows on screen until the answer
    // arrives, instead of flashing back to skeletons.
    placeholderData: keepPreviousData,
  });
}

/** The most the list route returns in one page — the honest cap on a count. */
export const COUNT_CAP = 200;

/**
 * How many companies stand at one journey stage, up to `COUNT_CAP`: the list route
 * has no total yet (ask A2), so a full page reads "200+". Shares its cache with the
 * desk's pipeline counts.
 */
export function useJourneyCount(journey: ExporterSearchParams['journey']) {
  const query = useQuery({
    queryKey: ['exporterProfiles', { journey, limit: COUNT_CAP }],
    queryFn: () => searchExporterProfiles({ journey, limit: COUNT_CAP }),
  });
  return query.data ? query.data.profiles.length : undefined;
}

/**
 * Loads a company's dossier ahead of a click — on hover or focus of its row (§12.3).
 * Resolves `true` once the record is cached, so a morph can tell the dossier will
 * draw at once; it never rejects.
 */
export function usePrefetchCompany() {
  const queryClient = useQueryClient();
  return async (customerId: string): Promise<boolean> => {
    const queryKey = ['exporterProfile', customerId];
    await queryClient.prefetchQuery({
      queryKey,
      queryFn: () => getExporterProfileDetail(customerId),
      staleTime: 30_000,
    });
    return queryClient.getQueryData(queryKey) !== undefined;
  };
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

// ── GST registrations (tasks 3.13, 3.14, 3.17) ───────────────────────────────

export function useGstRegistrations(customerId: string | undefined) {
  return useQuery({
    queryKey: ['gstRegistrations', customerId],
    queryFn: () => listGstRegistrations(customerId!),
    enabled: Boolean(customerId),
  });
}

/**
 * Every write to a branch invalidates the company too, not just the list: the
 * company's GSTINs, its flagged-branch count and the handover guard's answer on each
 * of its deals all change with it.
 */
function invalidateBranches(queryClient: ReturnType<typeof useQueryClient>, customerId: string) {
  void queryClient.invalidateQueries({ queryKey: ['gstRegistrations', customerId] });
  invalidateCompany(queryClient, customerId);
  // A flag blocks the handover of deals invoiced through that branch, so their
  // `handover_blocked_reason` is now stale.
  void queryClient.invalidateQueries({ queryKey: ['deal'] });
}

export function useAddGstRegistration(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddGstRegistrationRequest) => addGstRegistration(customerId, body),
    onSuccess: () => invalidateBranches(queryClient, customerId),
  });
}

export function useDeactivateGstRegistration(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { registrationId: string; reason?: string }) =>
      deactivateGstRegistration(vars.registrationId, { reason: vars.reason ?? null }),
    onSuccess: () => invalidateBranches(queryClient, customerId),
  });
}

export function useSetGstRegistrationFlag(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { registrationId: string; reason: string; flagged: boolean }) =>
      vars.flagged
        ? flagGstRegistration(vars.registrationId, { reason: vars.reason })
        : unflagGstRegistration(vars.registrationId, { reason: vars.reason }),
    onSuccess: () => invalidateBranches(queryClient, customerId),
  });
}
