/**
 * What a verification result rests on (verification-and-screening.md §3, §9).
 *
 * Shows `evidence_note` and `evidence_refs` exactly as the server stored them. The
 * retired `evidence_reference` column is never shown: nothing writes it.
 *
 * A `document` reference is read on screen, in the CRM's own viewer, by everyone who
 * may see it (the preview route) — and saved only by a holder of `documents:download`
 * (`useOpenDocument().open`). The document row is read first for its file name and
 * whether it may be served; a refusal is shown, never worked around.
 *
 * Each cited document is also named by its file name on display, from the same
 * row through a cached query; the shortened id stands in until then.
 */

import { useEffect, useState } from 'react';

import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { useHasPermission } from '@/platform/access';

import { getDocument } from '../api';
import { useDocument } from '../hooks';
import type { CrmDocument, VerificationEvidenceRefStored } from '../types';

import { DocumentViewer } from './DocumentViewer';
import { type DocumentPreview, useOpenDocument } from './useOpenDocument';
import { isWebLink } from './verification-labels';

/**
 * A cited document by its file name, read through the same route the download
 * takes — so a role sees no more than it could already open. The shortened id
 * stands in while the row loads, and stays if the read is refused.
 */
function DocumentName({ documentId }: { documentId: string }) {
  const { data } = useDocument(documentId);
  return data ? (
    <span data-testid="evidence-document-name">{data.file_name}</span>
  ) : (
    <span>Document {documentId.slice(0, 8)}…</span>
  );
}

export function EvidenceList({
  note,
  refs,
}: {
  note: string | null;
  refs: VerificationEvidenceRefStored[];
}) {
  const { open: save, view, isSaving } = useOpenDocument();
  const mayDownload = useHasPermission('documents:download');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState<{ document_: CrmDocument; preview: DocumentPreview } | null>(
    null,
  );

  // The preview's URL lives exactly as long as the viewer shows it.
  useEffect(() => {
    if (!viewing) return undefined;
    return () => URL.revokeObjectURL(viewing.preview.url);
  }, [viewing]);

  if (!note && refs.length === 0) return null;

  async function servable(documentId: string): Promise<CrmDocument | null> {
    const document_ = await getDocument(documentId);
    if (!document_.is_downloadable) {
      setError(`${document_.file_name} cannot be opened (${document_.scan_status}).`);
      return null;
    }
    return document_;
  }

  async function read(documentId: string) {
    setError(null);
    setBusy(true);
    try {
      const document_ = await servable(documentId);
      if (!document_) return;
      if (!document_.has_preview) {
        setError(`${document_.file_name} has no on-screen preview.`);
        return;
      }
      const preview = await view(document_);
      if (preview) setViewing({ document_, preview });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not open that document.');
    } finally {
      setBusy(false);
    }
  }

  async function download(documentId: string) {
    setError(null);
    try {
      const document_ = await servable(documentId);
      if (document_) await save(document_);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not save that document.');
    }
  }

  return (
    <div data-testid="evidence" className="mt-3 text-caption">
      <p className="text-ink-3">Evidence</p>
      {note && <p className="mt-0.5 whitespace-pre-wrap text-ink">{note}</p>}
      {refs.length > 0 && (
        <ul className="mt-1 space-y-1 text-ink">
          {refs.map((ref) => (
            <li key={`${ref.type}:${ref.ref}`} className="break-all">
              {ref.type === 'document' ? (
                <span className="inline-flex flex-wrap items-center gap-2">
                  <DocumentName documentId={ref.ref} />
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 font-medium text-ink hover:underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() => void read(ref.ref)}
                    aria-label={`View evidence document ${ref.ref}`}
                  >
                    <Icon.reveal size={12} /> View
                  </button>
                  {mayDownload && (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 font-medium text-ink hover:underline disabled:opacity-50"
                      disabled={isSaving}
                      onClick={() => void download(ref.ref)}
                      aria-label={`Download evidence document ${ref.ref}`}
                    >
                      <Icon.download size={12} /> Download
                    </button>
                  )}
                </span>
              ) : ref.type === 'url' && isWebLink(ref.ref) ? (
                <a href={ref.ref} target="_blank" rel="noreferrer" className="underline">
                  {ref.ref}
                </a>
              ) : ref.type === 'url' ? (
                // Not an http(s) link (e.g. `javascript:`): shown, never made clickable.
                <span data-testid="evidence-unsafe-url">
                  {ref.ref} <span className="text-ink-3">(not a web link — not opened)</span>
                </span>
              ) : (
                // A type this build does not know: shown as stored, not dropped.
                `${ref.type}: ${ref.ref}`
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-1 text-negative">
          {error}
        </p>
      )}
      {viewing && (
        <DocumentViewer
          document_={viewing.document_}
          preview={viewing.preview}
          onClose={() => setViewing(null)}
          onDownload={mayDownload ? () => void save(viewing.document_) : undefined}
        />
      )}
    </div>
  );
}
