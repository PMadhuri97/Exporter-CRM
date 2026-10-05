/**
 * The shelf: documents by category (frontend-plan §6.8); replaces the document
 * list's table-like rows.
 *
 * Each category is a row of file tiles: name, type, size, when, and the scan state
 * as a lamp. A file waiting on the scanner pulses slowly; a quarantined or failed
 * scan is negative and **never** downloadable (the server says so with
 * `is_downloadable`, and the button is absent, not disabled). The "pass-through
 * scanner" prototype label sits once on the shelf, not on every file.
 *
 * Uploading (staff) is a drop zone: drop a file — or choose one — and a composer asks
 * only for its category and type. On a deal, the shelf marks the categories a
 * handover requires as present or missing.
 */

import { useState, type DragEvent } from 'react';

import { Button, EmptyLine, Sheet, Skeleton, Tag } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { formatDateTime, humanize } from '@/lib/format';

import type { CrmDocument, DocumentOwnerKind, DocumentScanStatus, UploadDocumentInput } from '../../types';
import { SOURCE_LABEL } from '../document-labels';
import { DocumentUpload } from '../DocumentUpload';
import { ScanStatusBadge } from '../ScanStatusBadge';
import { useOpenDocument } from '../useOpenDocument';

import { categoryLabel } from './categoryLabel';
import { Lamp } from './Lamp';
import type { LampShape, Meaning } from './lamps';

const SCAN_LOOK: Record<DocumentScanStatus, { shape: LampShape; meaning: Meaning; label: string }> = {
  PENDING_SCAN: { shape: 'quarter', meaning: 'progress', label: 'Waiting for the scan' },
  AVAILABLE: { shape: 'full', meaning: 'positive', label: 'Available' },
  QUARANTINED: { shape: 'triangle', meaning: 'negative', label: 'Quarantined — never served' },
  SCAN_FAILED: { shape: 'cross', meaning: 'negative', label: 'Scan failed — not served' },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Tile({ document_ }: { document_: CrmDocument }) {
  const open = useOpenDocument();
  const scan = SCAN_LOOK[document_.scan_status];
  return (
    <li
      className="flex min-w-0 flex-col justify-between gap-3 rounded-xl border border-line bg-surface p-3.5"
      data-testid="shelf-file"
    >
      <div className="min-w-0">
        <p className="flex items-start gap-2 text-body font-medium text-ink">
          <Icon.document size={16} className="mt-0.5 shrink-0 text-ink-3" aria-hidden />
          <span className="min-w-0 [overflow-wrap:anywhere]">{document_.file_name}</span>
        </p>
        <p className="mt-1 text-caption text-ink-3">
          {document_.document_type.replaceAll('_', ' ')} · {formatSize(document_.size_bytes)} ·{' '}
          {formatDateTime(document_.uploaded_at)}
        </p>
        <p className="mt-0.5 text-caption text-ink-3">
          {SOURCE_LABEL[document_.source] ?? humanize(document_.source)}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2">
        {/* The status and the scanner that decided it: in this build that is the
            pass-through, which checks nothing — so a file never reads as scanned. */}
        <span
          className={cn('inline-flex items-center gap-1.5', document_.scan_status === 'PENDING_SCAN' && 'animate-scan-pulse')}
          data-scan={document_.scan_status}
          title={scan.label}
        >
          <Lamp shape={scan.shape} meaning={scan.meaning} size={12} />
          <ScanStatusBadge status={document_.scan_status} scannerName={document_.scanner_name} />
        </span>
        {document_.is_downloadable && (
          <Button
            size="sm"
            variant="quiet"
            className="h-7 px-2"
            onClick={() => void open(document_)}
            aria-label={`Download ${document_.file_name}`}
          >
            <Icon.download size={15} aria-hidden />
          </Button>
        )}
      </div>
    </li>
  );
}

export interface RequiredCategory {
  category: string;
  /** A required document type within the category, when the rule names one. */
  documentType?: string | null;
  label: string;
}

export function Shelf({
  documents,
  isLoading,
  emptyMessage,
  required,
  upload,
}: {
  documents: CrmDocument[];
  isLoading: boolean;
  emptyMessage: string;
  /** The categories a handover needs (a deal's shelf). */
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
    <div className="space-y-5" data-testid="shelf">
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
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
      ) : documents.length === 0 ? (
        <EmptyLine>{emptyMessage}</EmptyLine>
      ) : (
        [...byCategory.entries()].map(([category, files]) => (
          <div key={category} role="group" aria-label={categoryLabel(category)}>
            <h3 className="flex items-center gap-3 text-caption font-medium text-ink-3">
              {categoryLabel(category)}
              <span aria-hidden className="h-px flex-1 bg-line" />
              <span className="tabular-nums">{files.length}</span>
            </h3>
            <ul className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {files.map((document_) => (
                <Tile key={document_.id} document_={document_} />
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
              'flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed px-4 py-3 transition-colors duration-quick',
              dragging ? 'border-ink bg-sunken' : 'border-line-strong',
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
