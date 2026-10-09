/** Payment terms. Query key `['paymentTerms']`. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addPaymentTerm,
  listPaymentTerms,
  revisePaymentTerm,
  setDealTerms,
  setDefaultPaymentTerm,
} from '../api';
import type { AddPaymentTermRequest, RevisePaymentTermRequest, SetDealTermsRequest } from '../types';

export function usePaymentTerms() {
  return useQuery({ queryKey: ['paymentTerms'], queryFn: () => listPaymentTerms() });
}

export function useAddPaymentTerm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddPaymentTermRequest) => addPaymentTerm(body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['paymentTerms'] }),
  });
}

export function useRevisePaymentTerm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ code, body }: { code: string; body: RevisePaymentTermRequest }) =>
      revisePaymentTerm(code, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['paymentTerms'] }),
  });
}

export function useSetDefaultPaymentTerm(companyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paymentTermId: string | null) => setDefaultPaymentTerm(companyId, paymentTermId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['exporterProfile', companyId] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory', companyId] });
    },
  });
}

export function useSetDealTerms(dealId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetDealTermsRequest) => setDealTerms(dealId, body),
    onSuccess: (deal) => {
      queryClient.setQueryData(['deal', dealId], deal);
      void queryClient.invalidateQueries({ queryKey: ['deal', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['dealHistory', dealId] });
      void queryClient.invalidateQueries({ queryKey: ['deals'] });
      void queryClient.invalidateQueries({ queryKey: ['allDeals'] });
    },
  });
}
