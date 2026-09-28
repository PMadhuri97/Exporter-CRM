/**
 * What a verification result rests on — **owner: Developer 4B** (4b-task.md §5.3,
 * §5.10; 4B-7).
 *
 * Shows `evidence_note` and `evidence_refs` exactly as the server stored them. The
 * retired `evidence_reference` column is never shown: nothing writes it.
 *
 * A `document` reference is opened through Developer 3B's download flow, the same
 * three steps `DocumentList` takes: mint a short-lived link (`createDownloadLink`,
 * via `useDownloadDocument`), fetch it **with the access token**
 * (`fetchDocumentBlob`), save the bytes. The document row is read first for its file
 * name and whether it may be served; a refusal is shown, never worked around.
 */

import { Download } from 'lucide-react';
import { useState } from 'react';

import { ApiError } from '@/lib/api/errors';

import { fetchDocumentBlob, getDocument } from '../api';
import { useDownloadDocument } from '../hooks';
import type { VerificationEvidenceRefStored } from '../types';

import { isWebLink } from './verification-labels';

export function EvidenceList({
  note,
  refs,
}: {
  note: string | null;
  refs: VerificationEvidenceRefStored[];
}) {
  const download = useDownloadDocument();
  const [error, setError] = useState<string | null>(null);

  if (!note && refs.length === 0) return null;

  async function open(documentId: string) {
    setError(null);
    let objectUrl: string | null = null;
    try {
      const document_ = await getDocument(documentId);
      if (!document_.is_downloadable) {
        setError(`${document_.file_name} cannot be opened (${document_.scan_status}).`);
        return;
      }
      const link = await download.mutateAsync(documentId);
      const blob = await fetchDocumentBlob(link.url);
      objectUrl = URL.createObjectURL(blob);
      const anchor = window.document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = document_.file_name;
      anchor.rel = 'noopener';
      window.document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not open that document.');
    } finally {
      // Revoked later, as `DocumentList` does: revoking at once can cancel the save.
      if (objectUrl !== null) {
        const url = objectUrl;
        window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }
    }
  }

  return (
    <div data-testid="evidence" className="mt-3 text-xs">
      <p className="text-ink-faint">Evidence</p>
      {note && <p className="mt-0.5 whitespace-pre-wrap text-ink">{note}</p>}
      {refs.length > 0 && (
        <ul className="mt-1 space-y-1 text-ink">
          {refs.map((ref) => (
            <li key={`${ref.type}:${ref.ref}`} className="break-all">
              {ref.type === 'document' ? (
                <span className="inline-flex flex-wrap items-center gap-2">
                  <span>Document {ref.ref.slice(0, 8)}…</span>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline disabled:opacity-50"
                    disabled={download.isPending}
                    onClick={() => void open(ref.ref)}
                    aria-label={`Download evidence document ${ref.ref}`}
                  >
                    <Download size={12} /> Download
                  </button>
                </span>
              ) : ref.type === 'url' && isWebLink(ref.ref) ? (
                <a href={ref.ref} target="_blank" rel="noreferrer" className="underline">
                  {ref.ref}
                </a>
              ) : ref.type === 'url' ? (
                // Not an http(s) link (e.g. `javascript:`): shown, never made clickable.
                <span data-testid="evidence-unsafe-url">
                  {ref.ref} <span className="text-ink-faint">(not a web link — not opened)</span>
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
        <p role="alert" className="mt-1 text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
