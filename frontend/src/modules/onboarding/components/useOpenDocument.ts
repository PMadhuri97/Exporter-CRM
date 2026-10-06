/**
 * Opens one document, either way round: `open` hands the browser the file to save under
 * its original name, `view` returns it as a URL to show inside the CRM without saving
 * anything. Shared by `DocumentList` and the `DocumentsByCategory`. A refusal is shown in
 * the server's words.
 *
 * Both take the same route — ask for a short-lived link, fetch it — because the content
 * is served to the browser, not linked to: the link is single-use and the request
 * carries the session. That is also why viewing cannot simply be an `<iframe>` pointed
 * at a document URL.
 */

import { toast } from 'sonner';

import { fetchDocumentBlob } from '../api';
import { useDownloadDocument } from '../hooks';
import type { CrmDocument } from '../types';

/**
 * The content types a browser renders itself, and that are safe to render from a blob
 * URL. Anything else — a .docx, a .zip — would "view" by downloading, so it is offered
 * as a download only rather than as a button that does something other than it says.
 *
 * `image/svg+xml` and `text/html` are deliberately absent. A blob URL inherits the
 * origin that made it, so a script inside an uploaded SVG or HTML file would run as this
 * application, against this user's session. Those two are downloads only.
 */
const VIEWABLE_TYPES = new Set([
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/avif',
  'image/bmp',
  'text/plain',
]);

/** Whether this document can be shown in a tab rather than saved. */
export function isViewable(document_: CrmDocument): boolean {
  // The parameters a type may carry ("text/plain; charset=utf-8") are not part of the
  // decision.
  const type = document_.content_type.split(';')[0]?.trim().toLowerCase() ?? '';
  return VIEWABLE_TYPES.has(type);
}

export function useOpenDocument() {
  const download = useDownloadDocument();

  /** Fetches the bytes, typed so the browser knows what it has. */
  async function load(document_: CrmDocument): Promise<Blob> {
    const link = await download.mutateAsync(document_.id);
    // `url` is opaque (the port hides whether this is a local path or, later, a
    // presigned URL), so it is fetched rather than parsed or rebuilt.
    const blob = await fetchDocumentBlob(link.url);
    // Re-typed from the record: a blob that arrives as `application/octet-stream` would
    // download in the viewing tab instead of rendering. The type used here is the one
    // `isViewable` gated on, so the tab shows what the button promised.
    return blob.type === document_.content_type
      ? blob
      : new Blob([blob], { type: document_.content_type });
  }

  async function open(document_: CrmDocument) {
    let objectUrl: string | null = null;
    try {
      objectUrl = URL.createObjectURL(await load(document_));
      const anchor = window.document.createElement('a');
      anchor.href = objectUrl;
      // A blob URL ignores `Content-Disposition`, so the name is set from the row —
      // where the original name lives (it is deliberately not in the storage key).
      anchor.download = document_.file_name;
      anchor.rel = 'noopener';
      window.document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open that document');
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
   * The bytes as a URL the viewer can point at, or `null` when they could not be
   * fetched — the refusal is already on screen by then.
   *
   * It deliberately does not open anything itself. The document is shown inside the
   * CRM, in a panel over the record it belongs to, so the caller owns both the panel
   * and the URL's life: whoever stops showing it must `URL.revokeObjectURL` it, or the
   * blob is held for as long as the tab lives.
   */
  async function view(document_: CrmDocument): Promise<string | null> {
    try {
      return URL.createObjectURL(await load(document_));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open that document');
      return null;
    }
  }

  return { open, view };
}
