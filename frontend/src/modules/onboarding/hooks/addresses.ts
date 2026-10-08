/**
 * A company's addresses. Query key `['companyAddresses', id]`; every write also
 * refreshes the company's history and its GST branches (one may now name an address).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addCompanyAddress,
  deactivateCompanyAddress,
  listCompanyAddresses,
  setDefaultCompanyAddress,
  updateCompanyAddress,
} from '../api';
import type { AddCompanyAddressRequest, UpdateCompanyAddressRequest } from '../types';

export function useCompanyAddresses(customerId: string | undefined) {
  return useQuery({
    queryKey: ['companyAddresses', customerId],
    queryFn: () => listCompanyAddresses(customerId!),
    enabled: Boolean(customerId),
  });
}

function useInvalidateAddresses(customerId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['companyAddresses', customerId] });
    void queryClient.invalidateQueries({ queryKey: ['gstRegistrations', customerId] });
    void queryClient.invalidateQueries({ queryKey: ['companyHistory', customerId] });
  };
}

export function useAddCompanyAddress(customerId: string) {
  const invalidate = useInvalidateAddresses(customerId);
  return useMutation({
    mutationFn: (body: AddCompanyAddressRequest) => addCompanyAddress(customerId, body),
    onSuccess: invalidate,
  });
}

export function useUpdateCompanyAddress(customerId: string) {
  const invalidate = useInvalidateAddresses(customerId);
  return useMutation({
    mutationFn: ({ addressId, body }: { addressId: string; body: UpdateCompanyAddressRequest }) =>
      updateCompanyAddress(addressId, body),
    onSuccess: invalidate,
  });
}

export function useSetDefaultCompanyAddress(customerId: string) {
  const invalidate = useInvalidateAddresses(customerId);
  return useMutation({
    mutationFn: (addressId: string) => setDefaultCompanyAddress(addressId),
    onSuccess: invalidate,
  });
}

export function useDeactivateCompanyAddress(customerId: string) {
  const invalidate = useInvalidateAddresses(customerId);
  return useMutation({
    mutationFn: ({ addressId, reason }: { addressId: string; reason: string | null }) =>
      deactivateCompanyAddress(addressId, reason),
    onSuccess: invalidate,
  });
}
