/**
 * A list of documents, with a download control per row.
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

import { Button, EmptySection, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDateTime, humanize } from '@/lib/format';

import type { CrmDocument } from '../types';

import { SOURCE_LABEL } from './document-labels';
import { ScanStatusBadge } from './ScanStatusBadge';
import { useOpenDocument } from './useOpenDocument';

/**
 * Where a document came from, in words (`document_enums.DocumentSource`). The stored
 * value stays as it is. `EXPORTER_UPLOAD` is what staff upload on the exporter's
 * behalf, so "Exporter upload" read as if the exporter had uploaded it themselves.
 */


function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
  const handleDownload = useOpenDocument();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 2 }).map((_, index) => (
          <Skeleton key={index} className="h-14 rounded-lg" />
        ))}
      </div>
    );
  }

  if (documents.length === 0) {
    return <EmptySection>{emptyMessage}</EmptySection>;
  }

  return (
    <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
      {documents.map((document_) => (
        <li
          key={document_.id}
          className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-paper"
        >
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-medium text-ink">
              <Icon.document size={14} className="shrink-0 text-ink-3" />
              <span className="truncate">{document_.file_name}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-2">
              {humanize(document_.category)} · {document_.document_type.replaceAll('_', ' ')} ·{' '}
              {formatSize(document_.size_bytes)}
            </p>
            <p className="mt-1 text-xs text-ink-3">
              {SOURCE_LABEL[document_.source] ?? humanize(document_.source)} ·{' '}
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
              <Button
                size="sm"
                onClick={() => void handleDownload(document_)}
                aria-label={`Download ${document_.file_name}`}
              >
                <Icon.download size={13} /> Download
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
