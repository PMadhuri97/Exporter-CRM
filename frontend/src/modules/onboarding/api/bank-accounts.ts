/**
 * A company's bank accounts: proposed, approved, verified. Numbers arrive masked; the
 * full number only from `revealBankAccount`, which the server audits.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  BankAccount,
  BankAccountList,
  PendingBankAccountList,
  ProposeBankAccountRequest,
  RevealedBankAccount,
  VerifyBankAccountRequest,
} from '../types';

export function listBankAccounts(customerId: string): Promise<BankAccountList> {
  return apiRequest<BankAccountList>(`/onboarding/exporters/${customerId}/bank-accounts`);
}

export function proposeBankAccount(
  customerId: string,
  body: ProposeBankAccountRequest,
): Promise<BankAccount> {
  return apiRequest<BankAccount>(`/onboarding/exporters/${customerId}/bank-accounts`, {
    method: 'POST',
    body,
  });
}

export function listPendingBankAccounts(): Promise<PendingBankAccountList> {
  return apiRequest<PendingBankAccountList>('/onboarding/bank-accounts/pending');
}

function act(accountId: string, action: string, body?: unknown): Promise<BankAccount> {
  return apiRequest<BankAccount>(`/onboarding/bank-accounts/${accountId}/${action}`, {
    method: 'POST',
    ...(body === undefined ? {} : { body }),
  });
}

export const approveBankAccount = (accountId: string) => act(accountId, 'approve');
export const rejectBankAccount = (accountId: string, reason: string) =>
  act(accountId, 'reject', { reason });
export const verifyBankAccount = (accountId: string, body: VerifyBankAccountRequest) =>
  act(accountId, 'verify', body);
export const setPrimaryBankAccount = (accountId: string) => act(accountId, 'primary');
export const deactivateBankAccount = (accountId: string, reason: string) =>
  act(accountId, 'deactivate', { reason });

export function revealBankAccount(accountId: string): Promise<RevealedBankAccount> {
  return apiRequest<RevealedBankAccount>(`/onboarding/bank-accounts/${accountId}/reveal`, {
    method: 'POST',
  });
}
