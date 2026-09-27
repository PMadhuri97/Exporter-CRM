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
 * Downloading is two steps by design: mint a short-lived link, then follow it. The
 * link is a credential, so it is requested when the user asks for it and never
 * prefetched.
 */

import { Download, FileText } from 'lucide-react';
import { toast } from 'sonner';

import { EmptySection } from '@/components';

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
    try {
      const link = await download.mutateAsync(document_.id);
      // `url` is opaque (the port hides whether it is a local path or a presigned
      // URL), so it is followed rather than parsed or rebuilt.
      window.open(link.url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Could not open that document',
      );
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
