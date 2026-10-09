/** Company intake: RXIL packages and bulk import (CSV or Excel). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { importCompanies, previewCompanyImport, submitRxilPackage } from '../api';

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

/**
 * The server's reading of a chosen file, before it is imported. Keyed by the file
 * itself, so choosing another file reads that one; never retried, since a file
 * that cannot be read will not read on a second try.
 */
export function useCompanyImportPreview(file: File | null) {
  return useQuery({
    queryKey: ['companyImportPreview', file?.name, file?.size, file?.lastModified],
    queryFn: () => previewCompanyImport(file as File),
    enabled: file !== null,
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
  });
}
