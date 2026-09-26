/**
 * Qualification — **owner: Developer 2**. Recording an outcome can move the
 * journey, so it invalidates the company as well as its qualification.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getQualification,
  listReasonCodes,
  recordQualificationOutcome,
  recordQualificationResults,
} from '../api';
import type { RecordOutcomeRequest, RecordResultsRequest } from '../types';

import { invalidateCompany } from './profile';

export function useQualification(customerId: string | undefined) {
  return useQuery({
    queryKey: ['qualification', customerId],
    queryFn: () => getQualification(customerId!),
    enabled: Boolean(customerId),
  });
}

export function useReasonCodes() {
  return useQuery({
    queryKey: ['qualificationReasonCodes'],
    queryFn: listReasonCodes,
    staleTime: 5 * 60_000,
  });
}

export function useRecordQualificationResults(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: RecordResultsRequest) =>
      recordQualificationResults(customerId, request),
    onSuccess: (data) => {
      queryClient.setQueryData(['qualification', customerId], data);
    },
  });
}

export function useRecordQualificationOutcome(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: RecordOutcomeRequest) =>
      recordQualificationOutcome(customerId, request),
    onSuccess: (data) => {
      queryClient.setQueryData(['qualification', customerId], data);
      invalidateCompany(queryClient, customerId);
    },
  });
}
