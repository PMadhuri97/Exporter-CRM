/**
 * Opens (downloads) one document: asks for a short-lived link, fetches it, and hands
 * the browser the file under its original name. Shared by `DocumentList` and the
 * `Shelf`. A refusal is shown in the server's words.
 */

import { toast } from 'sonner';

import { fetchDocumentBlob } from '../api';
import { useDownloadDocument } from '../hooks';
import type { CrmDocument } from '../types';

export function useOpenDocument() {
  const download = useDownloadDocument();

  return async function open(document_: CrmDocument) {
    let objectUrl: string | null = null;
    try {
      const link = await download.mutateAsync(document_.id);
      // `url` is opaque (the port hides whether this is a local path or, later, a
      // presigned URL), so it is fetched rather than parsed or rebuilt.
      const blob = await fetchDocumentBlob(link.url);
      objectUrl = URL.createObjectURL(blob);
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
  };
}
