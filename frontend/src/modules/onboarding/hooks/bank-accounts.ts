/**
 * A company's bank accounts. Query keys `['bankAccounts', id]` and
 * `['bankAccounts', 'pending']`; every write refreshes both, and the company's history.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  approveBankAccount,
  deactivateBankAccount,
  listBankAccounts,
  listPendingBankAccounts,
  proposeBankAccount,
  rejectBankAccount,
  revealBankAccount,
  setPrimaryBankAccount,
  verifyBankAccount,
} from '../api';
import type { ProposeBankAccountRequest, VerifyBankAccountRequest } from '../types';

export function useBankAccounts(customerId: string | undefined) {
  return useQuery({
    queryKey: ['bankAccounts', customerId],
    queryFn: () => listBankAccounts(customerId!),
    enabled: Boolean(customerId),
  });
}

export function usePendingBankAccounts(enabled = true) {
  return useQuery({
    queryKey: ['bankAccounts', 'pending'],
    queryFn: () => listPendingBankAccounts(),
    enabled,
  });
}

function useRefresh(customerId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['bankAccounts'] });
    void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
  };
}

export function useProposeBankAccount(customerId: string) {
  const onSuccess = useRefresh(customerId);
  return useMutation({
    mutationFn: (body: ProposeBankAccountRequest) => proposeBankAccount(customerId, body),
    onSuccess,
  });
}

export function useBankAccountAction(customerId: string) {
  const onSuccess = useRefresh(customerId);
  return useMutation({
    mutationFn: (
      vars:
        | { action: 'approve' | 'primary'; accountId: string }
        | { action: 'reject' | 'deactivate'; accountId: string; reason: string }
        | { action: 'verify'; accountId: string; body: VerifyBankAccountRequest },
    ) => {
      switch (vars.action) {
        case 'approve':
          return approveBankAccount(vars.accountId);
        case 'primary':
          return setPrimaryBankAccount(vars.accountId);
        case 'reject':
          return rejectBankAccount(vars.accountId, vars.reason);
        case 'deactivate':
          return deactivateBankAccount(vars.accountId, vars.reason);
        case 'verify':
          return verifyBankAccount(vars.accountId, vars.body);
      }
    },
    onSuccess,
  });
}

/** Not cached: a revealed number lives only in the component that asked for it. */
export function useRevealBankAccount() {
  return useMutation({ mutationFn: (accountId: string) => revealBankAccount(accountId) });
}
