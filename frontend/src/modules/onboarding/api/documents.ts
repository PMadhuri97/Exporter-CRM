/**
 * Documents and their content — **owner: Developer 3B** (L3-09).
 *
 * Created as a stub in the seam commit, together with its
 * `export * from './documents'` line in `api/index.ts`, and filled here — so the
 * barrel, which every owner shares, was never opened twice.
 *
 * Uploads are `multipart/form-data`, so they do **not** go through `apiRequest`:
 * that helper sets `Content-Type: application/json` and serialises the body. The
 * one thing it owns that matters here — a fresh access token — is taken from the
 * same place it takes it, so an upload still refreshes like any other call.
 */

import { apiRequest } from '@/lib/api/client';
import { ApiError, parseErrorResponse } from '@/lib/api/errors';
import { getAccessToken } from '@/lib/api/tokenStorage';

import type {
  CrmDocument,
  DocumentCategoryList,
  DocumentDownloadLink,
  DocumentList,
  DocumentListParams,
  DocumentOwnerKind,
  UploadDocumentInput,
} from '../types';

function listQuery(params: DocumentListParams): string {
  const query = new URLSearchParams();
  for (const category of params.categories ?? []) query.append('category', category);
  query.set('limit', String(params.limit ?? 50));
  query.set('offset', String(params.offset ?? 0));
  return query.toString();
}

/**
 * Which categories may be filed where the user is standing, and the types each
 * accepts.
 *
 * Asked of the server rather than hard-coded: the ten categories each belong to a
 * company, a deal, or both (architecture §3.4), and the types inside them are
 * settings that change without a release. `scanner_name` comes back too, so the
 * upload control can say which scanner will judge the file — `pass-through` in the
 * prototype, which a screen must show rather than imply a real scan.
 */
export function getDocumentCategories(
  owner: DocumentOwnerKind,
): Promise<DocumentCategoryList> {
  return apiRequest<DocumentCategoryList>(
    `/onboarding/documents/categories?owner=${owner}`,
  );
}

export function listCompanyDocuments(
  companyId: string,
  params: DocumentListParams = {},
): Promise<DocumentList> {
  return apiRequest<DocumentList>(
    `/onboarding/exporters/${companyId}/documents?${listQuery(params)}`,
  );
}

export function listDealDocuments(
  dealId: string,
  params: DocumentListParams = {},
): Promise<DocumentList> {
  return apiRequest<DocumentList>(
    `/onboarding/deals/${dealId}/documents?${listQuery(params)}`,
  );
}

export function getDocument(documentId: string): Promise<CrmDocument> {
  return apiRequest<CrmDocument>(`/onboarding/documents/${documentId}`);
}

/**
 * Mint a short-lived link to a document's content.
 *
 * `POST`, because it mints a credential rather than reading a resource. Refused
 * for a document that has not passed the scan step — for every role — so a caller
 * should check `is_downloadable` before offering the control at all, and show the
 * server's message if it still refuses.
 */
export function createDownloadLink(
  documentId: string,
): Promise<DocumentDownloadLink> {
  return apiRequest<DocumentDownloadLink>(
    `/onboarding/documents/${documentId}/download-link`,
    { method: 'POST' },
  );
}

async function uploadTo(path: string, input: UploadDocumentInput): Promise<CrmDocument> {
  const form = new FormData();
  form.append('file', input.file);
  form.append('category', input.category);
  form.append('document_type', input.documentType);
  if (input.source) form.append('source', input.source);

  const token = getAccessToken();
  const response = await fetch(`/api/v1${path}`, {
    method: 'POST',
    // No `Content-Type`: the browser sets it with the multipart boundary, and
    // setting it by hand produces a body the server cannot parse.
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });

  if (!response.ok) throw await parseErrorResponse(response);
  return (await response.json()) as CrmDocument;
}

/** Upload a document against a company. The category must be one that belongs on a
 * company — ask `getDocumentCategories('COMPANY')` rather than guessing. */
export function uploadCompanyDocument(
  companyId: string,
  input: UploadDocumentInput,
): Promise<CrmDocument> {
  return uploadTo(`/onboarding/exporters/${companyId}/documents`, input);
}

/** Upload a document against a deal. */
export function uploadDealDocument(
  dealId: string,
  input: UploadDocumentInput,
): Promise<CrmDocument> {
  return uploadTo(`/onboarding/deals/${dealId}/documents`, input);
}

export { ApiError };
