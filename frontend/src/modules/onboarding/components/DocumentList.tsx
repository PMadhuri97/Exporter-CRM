/**
 * A list of documents, with a download control per row — **owner: Developer 3B**
 * (L3-11b).
 *
 * Shared by the company documents page and the deal detail page, because a document
 * row reads the same wherever it hangs.
 *
 * **Unscanned and quarantined documents are listed, not hidden.** Hiding them would
 * leave an operator wondering where a file went. What they do not get is a download
 * control: `is_downloadable` comes from the server, and the button is absent rather
 * than disabled for the same reason the reveal icon is absent for a role that may
 * never reveal — a disabled control still invites a click and implies the file is
 * one permission away.
 *
 * Downloading is three steps, and the third is the one the review caught: mint a
 * short-lived link, **fetch it with the access token**, then save the bytes. The
 * content route is role-gated, so `window.open(url)` sends no `Authorization`
 * header and every click returned 401 — a failure the backend test could not see,
 * because it adds the header itself.
 *
 * The link is still a credential: it is requested when the user asks, never
 * prefetched, and it expires.
 */

import { Download, FileText } from 'lucide-react';
import { toast } from 'sonner';

import { EmptySection } from '@/components';

import { fetchDocumentBlob } from '../api';
import { useDownloadDocument } from '../hooks';
import type { CrmDocument } from '../types';

import { ScanStatusBadge } from './ScanStatusBadge';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

export function DocumentList({
  documents,
  isLoading,
  emptyMessage,
}: {
  documents: CrmDocument[];
  isLoading: boolean;
  emptyMessage: string;
}) {
  const download = useDownloadDocument();

  async function handleDownload(document_: CrmDocument) {
    let objectUrl: string | null = null;
    try {
      const link = await download.mutateAsync(document_.id);
      // `url` is opaque (the port hides whether this is a local path or, later, a
      // presigned URL), so it is fetched rather than parsed or rebuilt.
      const blob = await fetchDocumentBlob(link.url);
      objectUrl = URL.createObjectURL(blob);
      const anchor = window.document.createElement('a');
      anchor.href = objectUrl;
      // The server also sends `Content-Disposition`, but a blob URL ignores it, so
      // the name is set here — from the row, which is where the original name
      // lives (it is deliberately not in the storage key).
      anchor.download = document_.file_name;
      anchor.rel = 'noopener';
      window.document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Could not open that document',
      );
    } finally {
      // Revoked on the next tick: revoking immediately can cancel the download in
      // some browsers, and never revoking leaks the blob for the life of the tab.
      if (objectUrl !== null) {
        const url = objectUrl;
        window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 2 }).map((_, index) => (
          <div key={index} className="h-14 animate-pulse rounded-lg bg-surface-sunken" />
        ))}
      </div>
    );
  }

  if (documents.length === 0) {
    return <EmptySection>{emptyMessage}</EmptySection>;
  }

  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {documents.map((document_) => (
        <li
          key={document_.id}
          className="flex flex-wrap items-start justify-between gap-3 px-4 py-3"
        >
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-medium text-ink">
              <FileText size={14} className="shrink-0 text-ink-faint" />
              <span className="truncate">{document_.file_name}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">
              {document_.category.replaceAll('_', ' ').toLowerCase()} ·{' '}
              {document_.document_type.replaceAll('_', ' ')} ·{' '}
              {formatSize(document_.size_bytes)}
            </p>
            <p className="mt-1 text-xs text-ink-faint">
              {document_.source.replaceAll('_', ' ').toLowerCase()} ·{' '}
              {formatDateTime(document_.uploaded_at)}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <ScanStatusBadge
              status={document_.scan_status}
              scannerName={document_.scanner_name}
            />
            {/* Absent, not disabled, when the file may not be served. */}
            {document_.is_downloadable && (
              <button
                type="button"
                onClick={() => void handleDownload(document_)}
                aria-label={`Download ${document_.file_name}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
              >
                <Download size={13} /> Download
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
