/** Company intake — **owner: Developer 2**: RXIL packages and CSV import. */

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { importCompanies, submitRxilPackage } from '../api';

export function useSubmitRxilPackage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pkg: unknown) => submitRxilPackage(pkg),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] }),
  });
}

export function useImportCompanies() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => importCompanies(file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['exporterProfiles'] }),
  });
}
