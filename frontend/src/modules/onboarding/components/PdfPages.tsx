/**
 * A PDF drawn page by page onto canvases with pdf.js — the CRM's own viewer, in place of
 * the browser's, which brings a save and a print button with it.
 *
 * pdf.js is loaded only when a PDF is opened (a dynamic import), so the rest of the CRM
 * never downloads it. Pages render one after another at the panel's width, sharp on a
 * high-density screen. Nothing here offers to save: the canvases carry no file, and the
 * context menu is turned off over them.
 */

import { useEffect, useRef, useState } from 'react';

import { Skeleton } from '@/components';

export function PdfPages({ url, title }: { url: string; title: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | undefined;
    const host = container.current;

    async function render() {
      const pdfjs = await import('pdfjs-dist');
      const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      const task = pdfjs.getDocument(url);
      destroy = () => void task.destroy();
      const pdf = await task.promise;
      if (cancelled || !host) return;
      host.replaceChildren();
      const width = host.clientWidth || 800;
      const ratio = window.devicePixelRatio || 1;
      for (let number = 1; number <= pdf.numPages; number += 1) {
        const page = await pdf.getPage(number);
        if (cancelled) return;
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: (width / base.width) * ratio });
        const canvas = window.document.createElement('canvas');
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
        canvas.className = 'mx-auto mb-3 block bg-surface shadow-sm';
        canvas.setAttribute('aria-label', `${title}, page ${number} of ${pdf.numPages}`);
        canvas.setAttribute('role', 'img');
        host.appendChild(canvas);
        const context = canvas.getContext('2d');
        if (context) await page.render({ canvasContext: context, viewport }).promise;
      }
      if (!cancelled) setState('ready');
    }

    render().catch(() => {
      if (!cancelled) setState('error');
    });
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [url, title]);

  return (
    <>
      {state === 'loading' && <Skeleton className="h-[60vh]" />}
      {state === 'error' && (
        <p role="alert" className="p-4 text-secondary text-negative">
          This PDF could not be shown.
        </p>
      )}
      <div ref={container} data-testid="pdf-pages" onContextMenu={(event) => event.preventDefault()} />
    </>
  );
}
