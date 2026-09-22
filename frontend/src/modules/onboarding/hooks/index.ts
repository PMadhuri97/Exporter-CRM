import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addExporterContact,
  createExporterLead,
  getExporterProfileDetail,
  getBankActivity,
  getScreeningReview,
  listExporterActivities,
  listExporterContacts,
  listVerificationResults,
  logExporterActivity,
  reviewVerification,
  searchExporterProfiles,
  transitionExporterLifecycle,
  triggerVerification,
  updateScreeningReviewItem,
} from '../api';
import type {
  AddExporterContactRequest,
  ExporterActivityType,
  ExporterSearchParams,
  LogExporterActivityRequest,
  ExporterLifecycleStatus,
  RecordVerificationReviewRequest,
  TriggerVerificationRequest,
  VerificationEntityType,
  ScreeningChecklistStatus,
} from '../types';

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

export function useVerificationResults(
  entityType: VerificationEntityType,
  entityReference: string | undefined,
) {
  return useQuery({
    queryKey: ['verificationResults', entityType, entityReference],
    queryFn: () => listVerificationResults(entityType, entityReference!),
    enabled: Boolean(entityReference),
  });
}

export function useTriggerVerification(
  entityType: VerificationEntityType,
  entityReference: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<TriggerVerificationRequest, 'entity_type' | 'entity_reference'>) =>
      triggerVerification({
        ...payload,
        entity_type: entityType,
        entity_reference: entityReference,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['verificationResults', entityType, entityReference],
      });
    },
  });
}

export function useReviewVerification(
  entityType: VerificationEntityType,
  entityReference: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      verificationResultId,
      payload,
    }: {
      verificationResultId: string;
      payload: RecordVerificationReviewRequest;
    }) => reviewVerification(verificationResultId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['verificationResults', entityType, entityReference],
      });
    },
  });
}


export function useScreeningReview(customerId: string | undefined) {
  return useQuery({
    queryKey: ['screeningReview', customerId],
    queryFn: () => getScreeningReview(customerId!),
    enabled: Boolean(customerId),
  });
}

export function useUpdateScreeningReviewItem(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      itemKey,
      status,
      comment,
    }: {
      itemKey: string;
      status: ScreeningChecklistStatus;
      comment: string | null;
    }) => updateScreeningReviewItem(customerId, itemKey, { status, comment }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['screeningReview', customerId] });
    },
  });
}

export function useBankActivity(customerId: string | undefined) {
  return useQuery({
    queryKey: ['bankActivity', customerId],
    queryFn: () => getBankActivity(customerId!),
    enabled: Boolean(customerId),
  });
}
