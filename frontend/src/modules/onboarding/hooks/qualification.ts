/**
 * Qualification — **owner: Developer 2**. Recording an outcome can move the
 * journey, so it invalidates the company as well as its qualification.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addCriterionVersion,
  createCriterion,
  getQualification,
  listCriteria,
  listCriterionVersions,
  listReasonCodes,
  recordQualificationOutcome,
  recordQualificationResults,
} from '../api';
import type {
  CreateCriterionRequest,
  CriterionDefinitionRequest,
  RecordOutcomeRequest,
  RecordResultsRequest,
} from '../types';

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

// ── Criteria ──
//
// A new criterion or version changes what every company's standings are
// measured against, so both invalidate every `['qualification', …]` entry.

export function useCriteria() {
  return useQuery({ queryKey: ['qualificationCriteria'], queryFn: listCriteria });
}

export function useCriterionVersions(key: string | null) {
  return useQuery({
    queryKey: ['qualificationCriteria', key, 'versions'],
    queryFn: () => listCriterionVersions(key!),
    enabled: key !== null,
  });
}

export function useCreateCriterion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateCriterionRequest) => createCriterion(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['qualificationCriteria'] });
      void queryClient.invalidateQueries({ queryKey: ['qualification'] });
    },
  });
}

export function useAddCriterionVersion(key: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CriterionDefinitionRequest) => addCriterionVersion(key, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['qualificationCriteria'] });
      void queryClient.invalidateQueries({ queryKey: ['qualification'] });
    },
  });
}
