/**
 * A company's addresses: listed and added under the company, changed by their own id.
 * There is no delete — an address is deactivated.
 */

import { apiRequest } from '@/lib/api/client';

import type {
  AddCompanyAddressRequest,
  CompanyAddress,
  CompanyAddressList,
  UpdateCompanyAddressRequest,
} from '../types';

export function listCompanyAddresses(customerId: string): Promise<CompanyAddressList> {
  return apiRequest<CompanyAddressList>(`/onboarding/exporters/${customerId}/addresses`);
}

export function addCompanyAddress(
  customerId: string,
  body: AddCompanyAddressRequest,
): Promise<CompanyAddress> {
  return apiRequest<CompanyAddress>(`/onboarding/exporters/${customerId}/addresses`, {
    method: 'POST',
    body,
  });
}

/** A partial edit: send only the fields that change. */
export function updateCompanyAddress(
  addressId: string,
  body: UpdateCompanyAddressRequest,
): Promise<CompanyAddress> {
  return apiRequest<CompanyAddress>(`/onboarding/addresses/${addressId}`, {
    method: 'PATCH',
    body,
  });
}

export function setDefaultCompanyAddress(addressId: string): Promise<CompanyAddress> {
  return apiRequest<CompanyAddress>(`/onboarding/addresses/${addressId}/default`, {
    method: 'POST',
  });
}

export function deactivateCompanyAddress(
  addressId: string,
  reason: string | null,
): Promise<CompanyAddress> {
  return apiRequest<CompanyAddress>(`/onboarding/addresses/${addressId}/deactivate`, {
    method: 'POST',
    body: { reason },
  });
}
