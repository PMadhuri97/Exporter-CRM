/**
 * One document, shown inside the CRM rather than saved or opened elsewhere.
 *
 * It is a panel over the record the file belongs to, so reading a document does not cost
 * the page someone was on — the point of viewing rather than downloading. The bytes come
 * from the same served route as a download (`useOpenDocument`), fetched once by the
 * caller and handed here as a blob URL.
 *
 * Only the types `isViewable` admits reach this component, so there is no "cannot
 * display this" state to fall into: a file a browser would not render is offered as a
 * download and never as a view.
 */

import { Button, Sheet } from '@/components';
import { Icon } from '@/design/icons';

import type { CrmDocument } from '../types';

export interface DocumentViewerProps {
  document_: CrmDocument;
  /** The blob URL from `useOpenDocument().view`; the caller owns revoking it. */
  url: string;
  onClose: () => void;
  /** Saves the file, for when reading it is not enough. */
  onDownload: () => void;
}

export function DocumentViewer({ document_, url, onClose, onDownload }: DocumentViewerProps) {
  const isImage = document_.content_type.toLowerCase().startsWith('image/');
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
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="subtle" onClick={onClose}>
            Close
          </Button>
          <Button size="sm" onClick={onDownload}>
            <Icon.download size={14} aria-hidden /> Download
          </Button>
        </div>
      }
    >
      <div className="flex-1 overflow-auto rounded border border-line bg-sunken p-2">
        {isImage ? (
          // `max-w-full` and nothing else: an image is shown at its own size up to the
          // panel's width, so a scan stays legible instead of being fitted to the box.
          <img src={url} alt={document_.file_name} className="mx-auto max-w-full" />
        ) : (
          // A PDF or a text file: the browser's own viewer, which brings paging, zoom and
          // find with it. `title` is what a screen reader announces for the frame.
          <iframe src={url} title={document_.file_name} className="h-full min-h-[70vh] w-full" />
        )}
      </div>
    </Sheet>
  );
}
