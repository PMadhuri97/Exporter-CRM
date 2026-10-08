/**
 * Opens one document, either way round: `view` returns its on-screen form as a URL to
 * show inside the CRM, and `open` hands the browser the original to save. Shared by
 * `DocumentsByCategory` and `EvidenceList`. A refusal is shown in the server's words.
 *
 * **Reading and saving are different permissions.** Everyone who may see a document
 * reads it on screen (`documents:view`, the preview route): a PDF, an image or plain text
 * as it is, and a Word, Excel or PowerPoint file as the PDF the server converted it to.
 * Saving a copy is `documents:download` (COMPLIANCE by default) — the short-lived link,
 * fetched with the session. Both are recorded in the audit trail by the server.
 *
 * Neither can be an `<iframe>` pointed at a document URL: the content is served to the
 * request that carries the session, not linked to.
 */

import { toast } from 'sonner';

import { fetchDocumentBlob, fetchDocumentPreview } from '../api';
import { useDownloadDocument } from '../hooks';
import type { CrmDocument } from '../types';

/** What the viewer draws: the bytes as a URL, and what kind of thing they are. */
export interface DocumentPreview {
  url: string;
  /** `application/pdf`, an `image/*` type, or `text/plain`. */
  type: string;
}

/**
 * Hands the browser bytes already fetched, to save under `fileName`. It does not revoke
 * the URL: the caller that made it decides how long it lives.
 */
export function saveObjectUrl(objectUrl: string, fileName: string) {
  const anchor = window.document.createElement('a');
  anchor.href = objectUrl;
  // A blob URL ignores `Content-Disposition`, so the name is set from the row — where
  // the original name lives (it is deliberately not in the storage key).
  anchor.download = fileName;
  anchor.rel = 'noopener';
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export function useOpenDocument() {
  const download = useDownloadDocument();

  /** Saves the original — for a holder of `documents:download`. */
  async function open(document_: CrmDocument) {
    let objectUrl: string | null = null;
    try {
      const link = await download.mutateAsync(document_.id);
      // `url` is opaque (the port hides whether this is a local path or, later, a
      // presigned URL), so it is fetched rather than parsed or rebuilt.
      const blob = await fetchDocumentBlob(link.url);
      objectUrl = URL.createObjectURL(blob);
      saveObjectUrl(objectUrl, document_.file_name);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save that document');
    } finally {
      // Revoked on a later tick: revoking at once can cancel the download in some
      // browsers, and never revoking leaks the blob for the life of the tab.
      if (objectUrl !== null) {
        const url = objectUrl;
        window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }
    }
  }

  /**
   * The on-screen form as a URL, or `null` when it could not be fetched — the refusal
   * is already on screen by then ("Preview unavailable" for a conversion that failed).
   *
   * It deliberately opens nothing itself: the caller owns the viewer and the URL's life,
   * and must `URL.revokeObjectURL` it when it stops showing it.
   */
  async function view(document_: CrmDocument): Promise<DocumentPreview | null> {
    try {
      const blob = await fetchDocumentPreview(document_.id);
      const type = (blob.type || 'application/pdf').split(';')[0]!.trim().toLowerCase();
      return { url: URL.createObjectURL(blob), type };
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open that document');
      return null;
    }
  }

  return { open, view, isSaving: download.isPending };
}
