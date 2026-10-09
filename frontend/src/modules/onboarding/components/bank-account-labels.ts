/** Words for a company bank account: its status, its type and how it was verified. */

import type { BadgeTone } from '@/components/ui/styles';

import type { BankAccountStatus, BankAccountType, BankVerificationMethod } from '../types';

export const BANK_STATUS_LABEL: Record<BankAccountStatus, string> = {
  PENDING_APPROVAL: 'Pending approval',
  PENDING_VERIFICATION: 'Pending verification',
  VERIFIED: 'Verified',
  REJECTED: 'Rejected',
  INACTIVE: 'Inactive',
};

export const BANK_STATUS_TONE: Record<BankAccountStatus, BadgeTone> = {
  PENDING_APPROVAL: 'attention',
  PENDING_VERIFICATION: 'progress',
  VERIFIED: 'positive',
  REJECTED: 'negative',
  INACTIVE: 'neutral',
};

export const BANK_TYPE_LABEL: Record<BankAccountType, string> = {
  CURRENT: 'Current',
  EEFC: 'EEFC',
  SAVINGS: 'Savings',
  OTHER: 'Other',
};

export const BANK_METHOD_LABEL: Record<BankVerificationMethod, string> = {
  CANCELLED_CHEQUE: 'Cancelled cheque',
  BANK_LETTER: 'Bank letter',
  PENNY_DROP: 'Penny drop',
};
