/**
 * Documents and their content.
 *
 * Created as a stub, together with its
 * `export * from './documents'` line in `api/index.ts`, and filled here — so the
 * barrel, which every area shares, was never opened twice.
 *
 * Uploads go through `apiRequest` like everything else. An earlier version of this
 * file called `fetch` directly, with a comment claiming `apiRequest` would force a
 * JSON content type — that was written against an older `client.ts` and is wrong:
 * it detects a `FormData` body, passes it through untouched, and lets the browser
 * set the multipart boundary. Bypassing it cost the upload its token refresh and
 * its one 401 retry, which is exactly what the review caught.
 */

import { apiRequest } from '@/lib/api/client';

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

function uploadTo(path: string, input: UploadDocumentInput): Promise<CrmDocument> {
  const form = new FormData();
  form.append('file', input.file);
  form.append('category', input.category);
  form.append('document_type', input.documentType);
  if (input.source) form.append('source', input.source);
  return apiRequest<CrmDocument>(path, { method: 'POST', body: form });
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

/**
 * Fetch a document's bytes and hand back an object URL to save.
 *
 * **Why not just open the link.** The content route is role-gated, so
 * `window.open(url)` — which sends no `Authorization` header — gets a 401 and the
 * download silently fails for every document. That is what the review found, and
 * the backend test missed it because the test adds the header by hand.
 *
 * So the link is fetched like any other request (token, refresh, one retry) and the
 * response becomes a blob the caller saves through a temporary anchor. The
 * signature on the URL still does its own job: it scopes a link to one key and
 * expires it, so a leaked URL is not a permanent grant.
 *
 * The alternative — making the signature the only credential, the way S3 presigned
 * URLs work — would let `window.open` work directly, at the cost of a URL that
 * anyone holding it can fetch unauthenticated. That is a security trade worth
 * deciding deliberately rather than falling into, and it is recorded in
 * `docs/contracts/storage-and-documents.md` §6.
 */
export async function fetchDocumentBlob(url: string): Promise<Blob> {
  // `url` arrives absolute (it carries the API prefix), and `apiRequest` prepends
  // that prefix itself, so the prefix is stripped before handing it over.
  const path = url.replace(/^\/api\/v1/, '');
  return apiRequest<Blob>(path, { parseAs: 'blob' });
}

/**
 * A document as a reader sees it on screen: a PDF, an image or plain text — a Word,
 * Excel or PowerPoint file arrives already converted to PDF. Needs only
 * `documents:view`; saving a copy is the download link (`documents:download`). Fetched
 * with the access token like every request; the server records the view.
 */
export function fetchDocumentPreview(documentId: string): Promise<Blob> {
  return apiRequest<Blob>(`/onboarding/documents/${documentId}/preview`, { parseAs: 'blob' });
}
