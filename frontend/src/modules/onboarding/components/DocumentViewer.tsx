/**
 * One document, read inside the CRM rather than saved.
 *
 * A panel over the record the file belongs to, so reading a document does not cost the
 * page someone was on. What it draws is the server's on-screen form (the preview
 * route): a PDF through the CRM's own pdf.js viewer — no browser toolbar, so no save or
 * print button — an image, or plain text. A Word, Excel or PowerPoint file arrives as
 * the PDF the server converted it to.
 *
 * Every page carries the reader's name and the time (`DocumentWatermark`). **Download**
 * is offered only to a holder of `documents:download`; everyone else reads. Nothing in a
 * browser stops a screenshot — the watermark is what makes one traceable.
 */

import { useEffect, useState } from 'react';

import { Button, Sheet, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDateTime } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';

import type { CrmDocument } from '../types';

import { DocumentWatermark } from './DocumentWatermark';
import { PdfPages } from './PdfPages';
import type { DocumentPreview } from './useOpenDocument';

export interface DocumentViewerProps {
  document_: CrmDocument;
  /** From `useOpenDocument().view`; the caller owns revoking its URL. */
  preview: DocumentPreview;
  onClose: () => void;
  /** Saves the original; absent for a reader without `documents:download`. */
  onDownload?: () => void;
}

function TextPreview({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void fetch(url)
      .then((response) => response.text())
      .then((value) => {
        if (!cancelled) setText(value);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  if (text === null) return <Skeleton className="h-40" />;
  return <pre className="whitespace-pre-wrap break-words p-3 font-mono text-secondary text-ink">{text}</pre>;
}

export function DocumentViewer({ document_, preview, onClose, onDownload }: DocumentViewerProps) {
  const user = useCurrentUser();
  // Fixed when the panel opens: a mark that ticked would read as a live feed rather than
  // "who opened this, and when".
  const [openedAt] = useState(() => new Date().toISOString());
  const mark = `${user.full_name || user.email} · ${formatDateTime(openedAt)}`;

  return (
    <Sheet
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={document_.file_name}
      description={document_.document_type.replaceAll('_', ' ')}
      // Wider than a form sheet: this one holds a page of a document, and the default
      // 30rem would set a PDF at a size nobody can read.
      className="md:w-[min(60rem,92vw)]"
      footer={
        <div className="flex items-center justify-end gap-2">
          <span className="mr-auto text-caption text-ink-3">
            {onDownload ? 'Downloads are recorded.' : 'Read on screen. Views are recorded.'}
          </span>
          <Button size="sm" variant="subtle" onClick={onClose}>
            Close
          </Button>
          {onDownload && (
            <Button size="sm" onClick={onDownload}>
              <Icon.download size={14} aria-hidden /> Download
            </Button>
          )}
        </div>
      }
    >
      <div
        className="relative flex-1 select-none overflow-auto rounded border border-line bg-sunken p-2"
        onContextMenu={(event) => event.preventDefault()}
        data-testid="document-viewer"
      >
        <DocumentWatermark text={mark} />
        {preview.type === 'application/pdf' ? (
          <PdfPages url={preview.url} title={document_.file_name} />
        ) : preview.type.startsWith('image/') ? (
          // `max-w-full` and nothing else: an image is shown at its own size up to the
          // panel's width, so a scan stays legible instead of being fitted to the box.
          <img
            src={preview.url}
            alt={document_.file_name}
            className="mx-auto max-w-full"
            draggable={false}
          />
        ) : (
          <TextPreview url={preview.url} />
        )}
      </div>
    </Sheet>
  );
}
