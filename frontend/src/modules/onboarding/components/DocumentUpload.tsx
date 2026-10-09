/**
 * Upload documents against a company or a deal — one file or several at once.
 *
 * One component for both owners: the only differences are which categories the
 * server offers and which upload hook runs, and both are passed in.
 *
 * **Several files, one form.** Every file needs a category and a type, so the form sets
 * them once for all the files (the two selects at the top) and lets any row differ (its
 * own two selects, filled from the top ones). Files go up one request each, two at a
 * time, each with its own status. A file that fails does not undo the ones that
 * succeeded: they stay uploaded, the failed ones stay listed with the server's reason,
 * and "Retry failed" sends only those again.
 *
 * **The categories come from the server** (`GET /documents/categories`), not from a
 * list in here. Which of the ten categories may be filed against a company and which
 * against a deal is a server rule (architecture §3.4), and the types inside each are
 * settings that change without a release — a copy here would go stale silently.
 *
 * **It says the scanner is a placeholder.** The catalogue returns `scanner_name`,
 * and while that reads `pass-through` this form says so in as many words: gate §7.6
 * blocks real exporter documents until a real scanner is behind the interface, and a
 * form that implied one had run would be the exact failure the placeholder
 * clean-up exists to prevent.
 */

import { useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button, Select } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { humanize } from '@/lib/format';

import { useDocumentCategories } from '../hooks';
import type { DocumentCategory, DocumentOwnerKind, UploadDocumentInput } from '../types';

/** Mirrors `MAX_DOCUMENT_BYTES` in `document_router.py`; the server is still the
 * one that enforces it. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** Most files one upload takes. Each is its own request, so this is about keeping the
 * list readable and the wait short, not a server limit. */
const MAX_UPLOAD_FILES = 10;

/** Files sent at the same time. */
const PARALLEL_UPLOADS = 2;

/** Mirrors the server's accepted content types — a picker hint, not the rule. */
const ACCEPTED_TYPES = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/tiff',
  'text/csv',
  'text/plain',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/msword',
  'application/zip',
].join(',');

type RowStatus = 'ready' | 'uploading' | 'done' | 'failed';

interface Row {
  key: string;
  file: File;
  category: DocumentCategory | '';
  documentType: string;
  status: RowStatus;
  error?: string;
}

const STATUS_TEXT: Record<RowStatus, string> = {
  ready: 'Ready',
  uploading: 'Uploading…',
  done: 'Uploaded',
  failed: 'Failed',
};

interface DocumentUploadProps {
  owner: DocumentOwnerKind;
  /** Whatever mutation this owner needs — `useUploadCompanyDocument` or
   * `useUploadDealDocument`. Passed in so this component knows nothing about
   * which owner it is serving beyond the categories it asks for. */
  onUpload: (input: UploadDocumentInput) => Promise<unknown>;
  onDone?: () => void;
  /** Files already chosen — dropped on the document list (frontend-plan §8.5). */
  initialFiles?: File[];
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

let rowCounter = 0;

/** Rows for newly chosen files: oversized ones are marked failed at once, so nothing
 * 25 MB is sent just to be refused, and the list never grows past the limit. */
function toRows(
  files: File[],
  existing: Row[],
  defaults: { category: DocumentCategory | ''; documentType: string },
): { rows: Row[]; skipped: number } {
  const seen = new Set(existing.map((row) => `${row.file.name}:${row.file.size}`));
  const rows: Row[] = [];
  let skipped = 0;
  for (const file of files) {
    const id = `${file.name}:${file.size}`;
    if (seen.has(id)) continue;
    if (existing.length + rows.length >= MAX_UPLOAD_FILES) {
      skipped += 1;
      continue;
    }
    seen.add(id);
    const tooLarge = file.size > MAX_UPLOAD_BYTES;
    rows.push({
      key: `upload-${(rowCounter += 1)}`,
      file,
      ...defaults,
      status: tooLarge ? 'failed' : 'ready',
      error: tooLarge
        ? `${formatSize(file.size)} is over the ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB limit`
        : undefined,
    });
  }
  return { rows, skipped };
}

export function DocumentUpload({ owner, onUpload, onDone, initialFiles = [] }: DocumentUploadProps) {
  const { data, isLoading } = useDocumentCategories(owner);
  const [category, setCategory] = useState<DocumentCategory | ''>('');
  const [documentType, setDocumentType] = useState('');
  const [rows, setRows] = useState<Row[]>(
    () => toRows(initialFiles, [], { category: '', documentType: '' }).rows,
  );
  const [running, setRunning] = useState(false);
  // The file input is uncontrolled, so choosing the same file twice would not fire
  // `change`; the ref lets the element be reset after each choice.
  const fileInput = useRef<HTMLInputElement>(null);

  const categories = useMemo(() => data?.categories ?? [], [data]);
  const typesFor = (value: DocumentCategory | '') =>
    categories.find((entry) => entry.category === value)?.types ?? [];
  const scannerName = data?.scanner_name;

  function addFiles(files: File[]) {
    const { rows: added, skipped } = toRows(files, rows, { category, documentType });
    if (skipped > 0) {
      toast.error(`At most ${MAX_UPLOAD_FILES} files at a time; ${skipped} not added.`);
    }
    setRows((current) => [...current, ...added]);
  }

  function update(key: string, change: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  }

  /** The selects at the top set every row that is still to be sent. */
  function setAll(change: { category?: DocumentCategory | ''; documentType?: string }) {
    if (change.category !== undefined) setCategory(change.category);
    if (change.documentType !== undefined) setDocumentType(change.documentType);
    setRows((current) =>
      current.map((row) =>
        row.status === 'done' || row.status === 'uploading'
          ? row
          : {
              ...row,
              ...(change.category !== undefined ? { category: change.category, documentType: '' } : {}),
              ...(change.documentType !== undefined ? { documentType: change.documentType } : {}),
            },
      ),
    );
  }

  const pending = rows.filter((row) => row.status === 'ready' || (row.status === 'failed' && row.file.size <= MAX_UPLOAD_BYTES));
  const incomplete = pending.some((row) => row.category === '' || row.documentType === '');
  const canSubmit = pending.length > 0 && !incomplete && !running;
  const failedCount = rows.filter((row) => row.status === 'failed').length;
  const doneCount = rows.filter((row) => row.status === 'done').length;

  async function uploadAll() {
    const queue = [...pending];
    setRunning(true);
    let succeeded = 0;
    let failed = 0;
    async function worker() {
      for (let row = queue.shift(); row; row = queue.shift()) {
        const { key, file, category: rowCategory, documentType: rowType } = row;
        update(key, { status: 'uploading', error: undefined });
        try {
          await onUpload({ file, category: rowCategory as DocumentCategory, documentType: rowType });
          update(key, { status: 'done' });
          succeeded += 1;
        } catch (error) {
          // The server words every refusal — an unaccepted file type, a category that
          // does not belong here, an empty file. Its message beats a guess.
          update(key, {
            status: 'failed',
            error: error instanceof Error ? error.message : 'Could not upload this file',
          });
          failed += 1;
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(PARALLEL_UPLOADS, queue.length) }, worker));
    setRunning(false);
    if (failed === 0) {
      toast.success(succeeded === 1 ? 'Document uploaded' : `${succeeded} documents uploaded`);
      onDone?.();
    } else {
      toast.error(
        `${failed} of ${succeeded + failed} ${succeeded + failed === 1 ? 'file' : 'files'} could not be uploaded`,
      );
    }
  }

  const several = rows.length > 1;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) void uploadAll();
      }}
      className="flex flex-col gap-3"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="document-category" className="mb-1 block text-caption font-medium text-ink-2">
            {several ? 'Category for all files' : 'Category'}
          </label>
          <Select
            id="document-category"
            value={category}
            disabled={isLoading || running}
            onChange={(event) =>
              // A type belongs to one category, so a category change clears it.
              setAll({ category: event.target.value as DocumentCategory | '', documentType: '' })
            }
          >
            <option value="">Choose a category…</option>
            {categories.map((entry) => (
              <option key={entry.category} value={entry.category}>
                {humanize(entry.category)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="document-type" className="mb-1 block text-caption font-medium text-ink-2">
            {several ? 'Type for all files' : 'Type'}
          </label>
          <Select
            id="document-type"
            value={documentType}
            disabled={category === '' || running}
            onChange={(event) => setAll({ documentType: event.target.value })}
          >
            <option value="">{category === '' ? 'Choose a category first' : 'Choose a type…'}</option>
            {typesFor(category).map((type) => (
              <option key={type.key} value={type.key}>
                {type.label}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div>
        <label htmlFor="document-file" className="mb-1 block text-caption font-medium text-ink-2">
          Files
        </label>
        <input
          id="document-file"
          type="file"
          multiple
          ref={fileInput}
          disabled={running}
          // The same types the server accepts (`CONTENT_TYPE_EXTENSIONS` in
          // `storage_service.py`). A hint, not the rule: the server still refuses
          // anything outside its allow-list, and a browser may send a type this
          // list does not name.
          accept={ACCEPTED_TYPES}
          onChange={(event) => {
            addFiles(Array.from(event.target.files ?? []));
            event.target.value = '';
          }}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-body text-ink file:mr-3 file:rounded-md file:border-0 file:bg-sunken file:px-3 file:py-1 file:text-sm file:text-ink-2"
        />
        <p className="mt-1 text-caption text-ink-3">
          Up to {MAX_UPLOAD_FILES} files, {MAX_UPLOAD_BYTES / (1024 * 1024)} MB each.
        </p>
      </div>

      {rows.length > 0 && (
        <ul aria-label="Files to upload" className="divide-y divide-line rounded border border-line">
          {rows.map((row) => {
            const locked = row.status === 'done' || row.status === 'uploading' || running;
            return (
              <li key={row.key} className="space-y-2 px-3 py-2" data-testid="upload-row" data-status={row.status}>
                <div className="flex items-center gap-2">
                  <Icon.document size={16} className="shrink-0 text-ink-3" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-body text-ink">{row.file.name}</span>
                  <span className="shrink-0 text-caption text-ink-3">{formatSize(row.file.size)}</span>
                  <span
                    className={cn(
                      'shrink-0 text-caption font-medium',
                      row.status === 'done' && 'text-positive',
                      row.status === 'failed' && 'text-negative',
                      (row.status === 'ready' || row.status === 'uploading') && 'text-ink-2',
                    )}
                  >
                    {STATUS_TEXT[row.status]}
                  </span>
                  {!locked && (
                    <button
                      type="button"
                      aria-label={`Remove ${row.file.name}`}
                      onClick={() => setRows((current) => current.filter((other) => other.key !== row.key))}
                      className="shrink-0 rounded p-1 text-ink-3 hover:bg-sunken hover:text-ink"
                    >
                      <Icon.close size={14} aria-hidden />
                    </button>
                  )}
                </div>
                {row.error && (
                  <p role="alert" className="text-caption text-negative">
                    {row.error}
                  </p>
                )}
                {several && row.status !== 'done' && row.file.size <= MAX_UPLOAD_BYTES && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Select
                      aria-label={`Category for ${row.file.name}`}
                      value={row.category}
                      disabled={locked}
                      onChange={(event) =>
                        update(row.key, {
                          category: event.target.value as DocumentCategory | '',
                          documentType: '',
                        })
                      }
                    >
                      <option value="">Choose a category…</option>
                      {categories.map((entry) => (
                        <option key={entry.category} value={entry.category}>
                          {humanize(entry.category)}
                        </option>
                      ))}
                    </Select>
                    <Select
                      aria-label={`Type for ${row.file.name}`}
                      value={row.documentType}
                      disabled={locked || row.category === ''}
                      onChange={(event) => update(row.key, { documentType: event.target.value })}
                    >
                      <option value="">{row.category === '' ? 'Choose a category first' : 'Choose a type…'}</option>
                      {typesFor(row.category).map((type) => (
                        <option key={type.key} value={type.key}>
                          {type.label}
                        </option>
                      ))}
                    </Select>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {scannerName === 'pass-through' && (
        <p className="rounded-lg border border-attention/30 bg-attention-tint px-3 py-2 text-caption text-ink-2">
          <span className="font-medium text-ink">No malware scanning yet.</span> This
          build records a <span className="">pass-through</span> result
          instead of scanning, so an uploaded file is marked available without being
          checked. Do not upload a real exporter document until a scanner is
          connected.
        </p>
      )}

      <div className="flex items-center justify-end gap-3">
        {doneCount > 0 && failedCount > 0 && !running && (
          <span className="text-caption text-ink-3">{doneCount} uploaded</span>
        )}
        {doneCount > 0 && failedCount > 0 && !running && onDone && (
          <Button type="button" variant="subtle" onClick={onDone}>
            Close
          </Button>
        )}
        <Button type="submit" variant="primary" disabled={!canSubmit} loading={running}>
          {!running && <Icon.upload size={15} />}
          {failedCount > 0 && doneCount > 0
            ? 'Retry failed'
            : pending.length > 1
              ? `Upload ${pending.length} files`
              : 'Upload'}
        </Button>
      </div>
    </form>
  );
}
