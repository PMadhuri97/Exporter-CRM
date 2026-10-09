/** Payment terms (Settings → Payment terms), a company's default, and a deal's terms. */

import { apiRequest } from '@/lib/api/client';

import type {
  AddPaymentTermRequest,
  Deal,
  PaymentTerm,
  PaymentTermList,
  RevisePaymentTermRequest,
  SetDealTermsRequest,
} from '../types';

export function listPaymentTerms(): Promise<PaymentTermList> {
  return apiRequest<PaymentTermList>('/onboarding/settings/payment-terms');
}

export function addPaymentTerm(body: AddPaymentTermRequest): Promise<PaymentTerm> {
  return apiRequest<PaymentTerm>('/onboarding/settings/payment-terms', { method: 'POST', body });
}

/** Writes the next version of the term; `active: false` retires it. */
export function revisePaymentTerm(code: string, body: RevisePaymentTermRequest): Promise<PaymentTerm> {
  return apiRequest<PaymentTerm>(`/onboarding/settings/payment-terms/${code}`, {
    method: 'PATCH',
    body,
  });
}

export function setDefaultPaymentTerm(
  companyId: string,
  paymentTermId: string | null,
): Promise<PaymentTerm | null> {
  return apiRequest<PaymentTerm | null>(`/onboarding/exporters/${companyId}/default-payment-term`, {
    method: 'PUT',
    body: { payment_term_id: paymentTermId },
  });
}

/** A partial edit of a deal's value, currency and payment term. */
export function setDealTerms(dealId: string, body: SetDealTermsRequest): Promise<Deal> {
  return apiRequest<Deal>(`/onboarding/deals/${dealId}/terms`, { method: 'PATCH', body });
}
