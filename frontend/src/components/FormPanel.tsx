/**
 * A form opened from a page — now a composer surface (frontend-plan §6.10): a sheet
 * from the right on a wide screen, from the bottom on a narrow one, instead of a box
 * in the middle of the page. The form inside keeps its own fields and verb; Escape
 * or the close button calls `onClose`, and focus returns to what opened it.
 *
 * Kept under its old name so every caller moved at once; new code uses `Composer`.
 */

import { useEffect, useState } from 'react';

import { Sheet } from './ui/Dialog';

const WIDE = '(min-width: 1024px)';

function isWide(): boolean {
  return typeof window === 'undefined' || !window.matchMedia ? true : window.matchMedia(WIDE).matches;
}

export function FormPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const [wide, setWide] = useState(isWide);
  useEffect(() => {
    if (!window.matchMedia) return;
    const query = window.matchMedia(WIDE);
    const update = () => setWide(query.matches);
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      side={wide ? 'right' : 'bottom'}
    >
      {children}
    </Sheet>
  );
}
