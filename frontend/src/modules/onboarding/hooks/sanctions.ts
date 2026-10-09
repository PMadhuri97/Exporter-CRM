/**
 * Sanctions screening. Query keys `['sanctions', companyId]`, `['sanctionsLists']`,
 * `['sanctions', 'trueMatches']` and `['sanctions', 'rescreenDue']`; every write refreshes
 * the screening queries, the company's background check (its SANCTIONS check moved) and
 * history.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addSanctionsList,
  confirmTrueMatch,
  decideSanctionsHit,
  getCompanySanctions,
  listCompanySanctionsRuns,
  listPendingTrueMatches,
  listRescreenDue,
  listSanctionsLists,
  recordSanctionsRun,
  rejectTrueMatch,
  reviseSanctionsList,
} from '../api';
import type {
  AddSanctionsListRequest,
  RecordSanctionsRunRequest,
  ReviseSanctionsListRequest,
  SanctionsDisposition,
} from '../types';

export function useSanctionsLists() {
  return useQuery({ queryKey: ['sanctionsLists'], queryFn: () => listSanctionsLists() });
}

export function useAddSanctionsList() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddSanctionsListRequest) => addSanctionsList(body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['sanctionsLists'] }),
  });
}

export function useReviseSanctionsList() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ code, body }: { code: string; body: ReviseSanctionsListRequest }) =>
      reviseSanctionsList(code, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sanctionsLists'] });
      void queryClient.invalidateQueries({ queryKey: ['sanctions'] });
    },
  });
}

export function useCompanySanctions(companyId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['sanctions', companyId],
    queryFn: () => getCompanySanctions(companyId!),
    enabled: Boolean(companyId) && enabled,
  });
}

export function useCompanySanctionsRuns(companyId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['sanctions', companyId, 'runs'],
    queryFn: () => listCompanySanctionsRuns(companyId!),
    enabled: Boolean(companyId) && enabled,
  });
}

export function usePendingTrueMatches(enabled = true) {
  return useQuery({
    queryKey: ['sanctions', 'trueMatches'],
    queryFn: () => listPendingTrueMatches(),
    enabled,
  });
}

export function useRescreenDue(enabled = true) {
  return useQuery({ queryKey: ['sanctions', 'rescreenDue'], queryFn: () => listRescreenDue(), enabled });
}

function useRefresh(companyId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['sanctions'] });
    void queryClient.invalidateQueries({ queryKey: ['backgroundCheck', companyId] });
    void queryClient.invalidateQueries({ queryKey: ['verificationResults'] });
    void queryClient.invalidateQueries({ queryKey: ['companyHistory', companyId] });
    void queryClient.invalidateQueries({ queryKey: ['deal'] });
  };
}

export function useRecordSanctionsRun(companyId: string) {
  const onSuccess = useRefresh(companyId);
  return useMutation({
    mutationFn: (body: RecordSanctionsRunRequest) => recordSanctionsRun(companyId, body),
    onSuccess,
  });
}

export function useSanctionsHitAction(companyId: string) {
  const onSuccess = useRefresh(companyId);
  return useMutation({
    mutationFn: (
      vars:
        | {
            action: 'decide';
            hitId: string;
            disposition: Exclude<SanctionsDisposition, 'TRUE_MATCH_PROPOSED'>;
            reason: string | null;
          }
        | { action: 'confirm'; hitId: string }
        | { action: 'reject'; hitId: string; reason: string },
    ) => {
      switch (vars.action) {
        case 'decide':
          return decideSanctionsHit(vars.hitId, vars.disposition, vars.reason);
        case 'confirm':
          return confirmTrueMatch(vars.hitId);
        case 'reject':
          return rejectTrueMatch(vars.hitId, vars.reason);
      }
    },
    onSuccess,
  });
}
