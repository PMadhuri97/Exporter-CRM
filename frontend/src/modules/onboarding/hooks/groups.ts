/** Parent and child companies. Query key `['companyGroup', id]`. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getCompanyGroup, listGroupSuggestions, setParentCompany } from '../api';
import type { SetParentCompanyRequest } from '../types';

export function useCompanyGroup(companyId: string | undefined) {
  return useQuery({
    queryKey: ['companyGroup', companyId],
    queryFn: () => getCompanyGroup(companyId!),
    enabled: Boolean(companyId),
  });
}

export function useGroupSuggestions(companyId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['companyGroup', companyId, 'suggestions'],
    queryFn: () => listGroupSuggestions(companyId!),
    enabled: Boolean(companyId) && enabled,
  });
}

export function useSetParentCompany(companyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetParentCompanyRequest) => setParentCompany(companyId, body),
    onSuccess: () => {
      // A link changes the group of every member, and both companies' history.
      void queryClient.invalidateQueries({ queryKey: ['companyGroup'] });
      void queryClient.invalidateQueries({ queryKey: ['companyHistory'] });
    },
  });
}
