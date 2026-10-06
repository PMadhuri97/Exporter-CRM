/**
 * Documents grouped by category (frontend-plan §8.5, §8.6): each file a row with its
 * name, type, size, source, when, and its scan status as a badge. A quarantined or
 * failed scan is **never** downloadable (the server says so with `is_downloadable`,
 * and the button is absent, not disabled). The "pass-through scanner" prototype label
 * sits once above the list, not on every file.
 *
 * Uploading (staff) is a drop zone: drop a file — or choose one — and a side panel
 * asks only for its category and type. On a deal, the list marks the categories a
 * handover requires as present or missing.
 */

import { useEffect, useState, type DragEvent } from 'react';

import { Button, EmptyLine, Sheet, Skeleton, Tag } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { formatDateTime, humanize } from '@/lib/format';

import type { CrmDocument, DocumentOwnerKind, DocumentScanStatus, UploadDocumentInput } from '../../types';
import { SOURCE_LABEL } from '../document-labels';
import { DocumentUpload } from '../DocumentUpload';
import { DocumentViewer } from '../DocumentViewer';
import { ScanStatusBadge } from '../ScanStatusBadge';
import { isViewable, saveObjectUrl, useOpenDocument } from '../useOpenDocument';

import { categoryLabel } from './categoryLabel';
const SCAN_TITLE: Record<DocumentScanStatus, string> = {
  PENDING_SCAN: 'Waiting for the scan',
  AVAILABLE: 'Available',
  QUARANTINED: 'Quarantined — never served',
  SCAN_FAILED: 'Scan failed — not served',
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Item({ document_ }: { document_: CrmDocument }) {
  const { open, view } = useOpenDocument();
  // The blob URL while this document is being read, and nothing when it is not. The row
  // owns it because the row opened it, so a session of opening one document after
  // another does not hold every one of them in memory.
  const [viewing, setViewing] = useState<string | null>(null);

  // Revoked when the viewer closes, and also when the row goes while it is open — the
  // user leaves the page, or a refetch drops the file — which a close handler alone
  // would miss, leaving the blob held for the life of the tab.
  useEffect(() => {
    if (!viewing) return undefined;
    return () => URL.revokeObjectURL(viewing);
  }, [viewing]);

  async function showInApp() {
    const url = await view(document_);
    if (url) setViewing(url);
  }

  return (
    <li className="flex min-w-0 items-center gap-3 py-2.5" data-testid="document-row">
      <Icon.document size={20} className="shrink-0 text-ink-3" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-body font-semibold text-ink [overflow-wrap:anywhere]">{document_.file_name}</p>
        <p className="mt-0.5 text-secondary text-ink-3">
          {document_.document_type.replaceAll('_', ' ')} · {formatSize(document_.size_bytes)} ·{' '}
          {SOURCE_LABEL[document_.source] ?? humanize(document_.source)} · {formatDateTime(document_.uploaded_at)}
        </p>
      </div>
      {/* The status alone. The scanner's name used to sit beside it on every row, so that
          "Available" could not be read as "a malware scan passed this"; the panel says
          "Prototype: pass-through scanner" once above the list, which makes the same point
          without repeating it on each line. */}
      <span className="shrink-0" data-scan={document_.scan_status} title={SCAN_TITLE[document_.scan_status]}>
        <ScanStatusBadge status={document_.scan_status} />
      </span>
      {/* Both gated on `is_downloadable`: viewing serves the same bytes as downloading,
          so a file the server refuses to serve has neither. View is offered only for the
          types a browser renders — on anything else it would just download, which the
          button beside it already does. */}
      {document_.is_downloadable && isViewable(document_) && (
        <Button
          size="sm"
          variant="subtle"
          className="shrink-0"
          onClick={() => void showInApp()}
          // The name carries the file, so rows are told apart by assistive tech; it opens
          // with the visible words, which is what a voice command will say.
          aria-label={`View document ${document_.file_name}`}
        >
          View document
        </Button>
      )}
      {document_.is_downloadable && (
        <Button
          size="sm"
          variant="subtle"
          className="w-7 shrink-0 px-0"
          onClick={() => void open(document_)}
          aria-label={`Download ${document_.file_name}`}
        >
          <Icon.download size={16} aria-hidden />
        </Button>
      )}

      {viewing && (
        <DocumentViewer
          document_={document_}
          url={viewing}
          onClose={() => setViewing(null)}
          // The bytes on screen are the file: saved as they are, not fetched again.
          onDownload={() => saveObjectUrl(viewing, document_.file_name)}
        />
      )}
    </li>
  );
}

export interface RequiredCategory {
  category: string;
  /** A required document type within the category, when the rule names one. */
  documentType?: string | null;
  label: string;
}

export function DocumentsByCategory({
  documents,
  isLoading,
  emptyMessage,
  required,
  upload,
}: {
  documents: CrmDocument[];
  isLoading: boolean;
  emptyMessage: string;
  /** The categories a handover needs (on a deal). */
  required?: RequiredCategory[];
  /** Present for a role that may upload here. */
  upload?: {
    owner: DocumentOwnerKind;
    onUpload: (input: UploadDocumentInput) => Promise<unknown>;
    isUploading: boolean;
  };
}) {
  const [composing, setComposing] = useState<{ file: File | null } | null>(null);
  const [dragging, setDragging] = useState(false);

  const byCategory = new Map<string, CrmDocument[]>();
  for (const document_ of documents) {
    byCategory.set(document_.category, [...(byCategory.get(document_.category) ?? []), document_]);
  }
  const passThrough = documents.some((document_) => document_.scanner_name === 'pass-through');

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) setComposing({ file });
  }

  return (
    <div className="space-y-5" data-testid="documents">
      {(passThrough || (required && required.length > 0)) && (
        <div className="flex flex-wrap items-center gap-2">
          {required?.map((entry) => {
            // Present means served: an AVAILABLE file of that category (and type), as the
            // handover guard counts it.
            const present = (byCategory.get(entry.category) ?? []).some(
              (file) =>
                file.scan_status === 'AVAILABLE' &&
                (!entry.documentType || file.document_type === entry.documentType),
            );
            return (
              <Tag
                key={entry.category}
                tone={present ? 'positive' : 'negative'}
                icon={present ? <Icon.check size={12} aria-hidden /> : <Icon.close size={12} aria-hidden />}
                data-testid={`required-category-${entry.category}${entry.documentType ? `-${entry.documentType}` : ''}`}
              >
                {entry.label}
                <span className="sr-only">{present ? ' — present' : ' — missing'}</span>
              </Tag>
            );
          })}
          {passThrough && (
            <Tag tone="attention" title="Files are marked available without being checked for malware.">
              Prototype: pass-through scanner
            </Tag>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : documents.length === 0 ? (
        <EmptyLine>{emptyMessage}</EmptyLine>
      ) : (
        [...byCategory.entries()].map(([category, files]) => (
          <div key={category} role="group" aria-label={categoryLabel(category)}>
            <h3 className="text-body font-semibold text-ink">
              {categoryLabel(category)}
              <span className="ml-1.5 font-normal tabular-nums text-ink-3">({files.length})</span>
            </h3>
            <ul className="mt-1 divide-y divide-line border-t border-line">
              {files.map((document_) => (
                <Item key={document_.id} document_={document_} />
              ))}
            </ul>
          </div>
        ))
      )}

      {upload && (
        <>
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-wrap items-center justify-between gap-3 rounded border border-dashed px-4 py-3 transition-colors duration-quick',
              dragging ? 'border-accent bg-accent-tint' : 'border-line-strong',
            )}
          >
            <p className="flex items-center gap-2 text-secondary text-ink-3">
              <Icon.upload size={16} aria-hidden />
              Drop a file here
            </p>
            <Button size="sm" variant="secondary" onClick={() => setComposing({ file: null })}>
              Upload a document
            </Button>
          </div>
          {/* The upload form has its own verb, so a plain sheet rather than a composer
              (which would wrap it in a second form). */}
          <Sheet
            open={composing !== null}
            onOpenChange={(open) => !open && setComposing(null)}
            title="Upload a document"
            description={composing?.file ? composing.file.name : undefined}
          >
            {composing && (
              <DocumentUpload
                owner={upload.owner}
                isUploading={upload.isUploading}
                onUpload={upload.onUpload}
                onDone={() => setComposing(null)}
                initialFile={composing.file}
              />
            )}
          </Sheet>
        </>
      )}
    </div>
  );
}
