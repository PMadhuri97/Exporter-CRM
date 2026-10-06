/**
 * React Query hooks for documents — **owner: Developer 3B** (L3-09).
 *
 * Created as a stub in the seam commit with its barrel line in `hooks/index.ts`,
 * and filled here, so the barrel was never opened twice.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createDownloadLink,
  getDocument,
  getDocumentCategories,
  listCompanyDocuments,
  listDealDocuments,
  uploadCompanyDocument,
  uploadDealDocument,
} from '../api';
import type {
  DocumentListParams,
  DocumentOwnerKind,
  UploadDocumentInput,
} from '../types';

/** The filing catalogue for wherever the user is standing. Cached for longer than
 * the default: categories are fixed in code and types change on deploy. */
export function useDocumentCategories(owner: DocumentOwnerKind) {
  return useQuery({
    queryKey: ['documentCategories', owner],
    queryFn: () => getDocumentCategories(owner),
    staleTime: 5 * 60_000,
  });
}

export function useCompanyDocuments(
  customerId: string | undefined,
  params: DocumentListParams = {},
) {
  return useQuery({
    queryKey: ['documents', 'company', customerId, params],
    queryFn: () => listCompanyDocuments(customerId!, params),
    enabled: Boolean(customerId),
  });
}

export function useDealDocuments(
  dealId: string | undefined,
  params: DocumentListParams = {},
) {
  return useQuery({
    queryKey: ['documents', 'deal', dealId, params],
    queryFn: () => listDealDocuments(dealId!, params),
    enabled: Boolean(dealId),
  });
}

/**
 * One document's row, for naming it where it is cited (verification evidence).
 *
 * Fetched only when a component that cites it mounts, and cached: a file name does
 * not change, and several results citing the same document share one read. A
 * refusal (403/404) is not retried — the caller keeps showing the id. Downloading
 * still reads the row afresh, since the scan status can move.
 */
export function useDocument(documentId: string | undefined) {
  return useQuery({
    queryKey: ['document', documentId],
    queryFn: () => getDocument(documentId!),
    enabled: Boolean(documentId),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useUploadCompanyDocument(customerId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadDocumentInput) =>
      uploadCompanyDocument(customerId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['documents', 'company', customerId],
      });
    },
  });
}

export function useUploadDealDocument(dealId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadDocumentInput) => uploadDealDocument(dealId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['documents', 'deal', dealId],
      });
    },
  });
}

/**
 * Mint a download link, then open it.
 *
 * A mutation rather than a query, because it is a `POST` that mints a credential:
 * a query would cache it, refetch it on focus, and keep handing out a URL that
 * expires in minutes.
 *
 * The link is only worth requesting when `document.is_downloadable` is true; a
 * screen that offers the control anyway will get the server's refusal, which it
 * should show rather than reword.
 */
export function useDownloadDocument() {
  return useMutation({
    mutationFn: (documentId: string) => createDownloadLink(documentId),
  });
}
