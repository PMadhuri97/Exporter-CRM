/** Words for a payment term's kind, and which kinds run for a number of days. */

import type { PaymentTerm } from '../types';

export const PAYMENT_KIND_LABEL: Record<string, string> = {
  ADVANCE: 'Advance payment',
  LC_SIGHT: 'Letter of credit at sight',
  LC_USANCE: 'Letter of credit, usance',
  DP: 'Documents against payment',
  DA: 'Documents against acceptance',
  OPEN_ACCOUNT: 'Open account',
};

export const PAYMENT_KINDS_WITH_DAYS: ReadonlySet<string> = new Set(['LC_USANCE', 'DA', 'OPEN_ACCOUNT']);

/** "DA 90 days", with "(retired)" when the term is no longer offered. */
export function termLabel(term: PaymentTerm | null | undefined): string {
  if (!term) return 'Not set';
  return term.active && term.is_current ? term.label : `${term.label} (no longer offered)`;
}

/** A value with its currency: "USD 125,000.50". */
export function moneyLabel(amount: string | number | null | undefined, currency: string | null | undefined): string | null {
  if (amount === null || amount === undefined || amount === '') return null;
  const value = Number(amount);
  const text = Number.isFinite(value)
    ? value.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
    : String(amount);
  return currency ? `${currency} ${text}` : text;
}
