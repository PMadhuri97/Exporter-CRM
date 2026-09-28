/**
 * An inline form opened inside a panel, with a title and a close button.
 *
 * Used for "Add contact" and "Log activity" today, and by whatever Developers
 * 3 and 4 add to the deal and background-check panels. Promoted verbatim out
 * of `ExporterDetailPage.tsx` during the panel split.
 *
 * The close button's `aria-label` includes the title (`Close Add contact`) so
 * two open forms on one page stay distinguishable to a screen reader.
 */

import { X } from 'lucide-react';

export function FormPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-4 rounded-lg border border-border bg-surface-subtle p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-ink-faint hover:bg-surface-sunken hover:text-ink"
          aria-label={`Close ${title}`}
        >
          <X size={16} />
        </button>
      </div>
      {children}
    </div>
  );
}
