/**
 * Upload a document against a company or a deal.
 *
 * One component for both owners: the only differences are which categories the
 * server offers and which upload hook runs, and both are passed in.
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
import { humanize } from '@/lib/format';

import { useDocumentCategories } from '../hooks';
import type {
  DocumentCategory,
  DocumentOwnerKind,
  UploadDocumentInput,
} from '../types';

/** Mirrors `MAX_DOCUMENT_BYTES` in `document_router.py`; the server is still the
 * one that enforces it. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

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

interface DocumentUploadProps {
  owner: DocumentOwnerKind;
  /** Whatever mutation this owner needs — `useUploadCompanyDocument` or
   * `useUploadDealDocument`. Passed in so this component knows nothing about
   * which owner it is serving beyond the categories it asks for. */
  onUpload: (input: UploadDocumentInput) => Promise<unknown>;
  isUploading: boolean;
  onDone?: () => void;
  /** A file already chosen — dropped on the document list (frontend-plan §8.5). */
  initialFile?: File | null;
}

export function DocumentUpload({
  owner,
  onUpload,
  isUploading,
  onDone,
  initialFile = null,
}: DocumentUploadProps) {
  const { data, isLoading } = useDocumentCategories(owner);
  const [category, setCategory] = useState<DocumentCategory | ''>('');
  const [documentType, setDocumentType] = useState('');
  const [file, setFile] = useState<File | null>(initialFile);
  // The file input is uncontrolled, so clearing the state does not clear what it
  // shows: after an upload it kept displaying the old file name beside a disabled
  // button. The ref lets the element itself be reset.
  const fileInput = useRef<HTMLInputElement>(null);

  const categories = useMemo(() => data?.categories ?? [], [data]);
  const types = useMemo(
    () => categories.find((entry) => entry.category === category)?.types ?? [],
    [categories, category],
  );
  const scannerName = data?.scanner_name;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (file === null || category === '' || documentType === '') return;
    try {
      await onUpload({ file, category, documentType });
      toast.success('Document uploaded');
      setFile(null);
      setDocumentType('');
      if (fileInput.current) fileInput.current.value = '';
      onDone?.();
    } catch (error) {
      // The server words every refusal — an unaccepted file type, a category that
      // does not belong here, an empty file. Showing its message beats guessing.
      toast.error(
        error instanceof Error ? error.message : 'Could not upload the document',
      );
    }
  }

  const canSubmit =
    file !== null && category !== '' && documentType !== '' && !isUploading;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label
            htmlFor="document-category"
            className="mb-1 block text-caption font-medium text-ink-2"
          >
            Category
          </label>
          <Select
            id="document-category"
            value={category}
            disabled={isLoading}
            onChange={(event) => {
              setCategory(event.target.value as DocumentCategory);
              // A type belongs to one category, so a category change invalidates it.
              setDocumentType('');
            }}
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
          <label
            htmlFor="document-type"
            className="mb-1 block text-caption font-medium text-ink-2"
          >
            Type
          </label>
          <Select
            id="document-type"
            value={documentType}
            disabled={category === ''}
            onChange={(event) => setDocumentType(event.target.value)}
          >
            <option value="">
              {category === '' ? 'Choose a category first' : 'Choose a type…'}
            </option>
            {types.map((type) => (
              <option key={type.key} value={type.key}>
                {type.label}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div>
        <label
          htmlFor="document-file"
          className="mb-1 block text-caption font-medium text-ink-2"
        >
          File
        </label>
        <input
          id="document-file"
          type="file"
          ref={fileInput}
          // The same types the server accepts (`CONTENT_TYPE_EXTENSIONS` in
          // `storage_service.py`). A hint, not the rule: the server still refuses
          // anything outside its allow-list, and a browser may send a type this
          // list does not name.
          accept={ACCEPTED_TYPES}
          onChange={(event) => {
            const chosen = event.target.files?.[0] ?? null;
            if (chosen !== null && chosen.size > MAX_UPLOAD_BYTES) {
              // Caught here so a 25 MB file is not uploaded just to be refused.
              toast.error(
                `That file is ${Math.round(chosen.size / (1024 * 1024))} MB; the limit is ${
                  MAX_UPLOAD_BYTES / (1024 * 1024)
                } MB`,
              );
              event.target.value = '';
              setFile(null);
              return;
            }
            setFile(chosen);
          }}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-body text-ink file:mr-3 file:rounded-md file:border-0 file:bg-sunken file:px-3 file:py-1 file:text-sm file:text-ink-2"
        />
      </div>

      {scannerName === 'pass-through' && (
        <p className="rounded-lg border border-attention/30 bg-attention-tint px-3 py-2 text-caption text-ink-2">
          <span className="font-medium text-ink">No malware scanning yet.</span> This
          build records a <span className="">pass-through</span> result
          instead of scanning, so an uploaded file is marked available without being
          checked. Do not upload a real exporter document until a scanner is
          connected.
        </p>
      )}

      <div className="flex justify-end">
        <Button type="submit" variant="primary" disabled={!canSubmit} loading={isUploading}>
          {!isUploading && <Icon.upload size={15} />}
          Upload
        </Button>
      </div>
    </form>
  );
}
