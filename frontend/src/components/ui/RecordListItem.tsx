import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

/**
 * One record in a list, without a table (frontend-plan §6.7): the title as a link
 * on the first line, one line of key facts under it, and the badges on the right.
 * No column headers and no sortable grid; the list's own controls filter it, on
 * the server. The same item serves companies, deals, users, follow-ups and
 * approvals — only the facts line and the badges differ.
 *
 * The whole row is the link (the title's link is stretched over it), so it sits in
 * normal tab order once. `aside` holds controls that must stay their own buttons
 * (*Mark done*), above the stretched link.
 */
export function RecordListItem({
  to,
  title,
  facts,
  badges,
  aside,
  muted = false,
  selected = false,
  onIntent,
  className,
  ...rest
}: {
  to: string;
  title: ReactNode;
  facts?: ReactNode;
  badges?: ReactNode;
  /** Controls on the far right that are not part of the link. */
  aside?: ReactNode;
  /** An ended relationship: the name greyed (§18.2). */
  muted?: boolean;
  /** The item open beside the list, in a split view (§6.13). */
  selected?: boolean;
  /** Hover or focus: a chance to prefetch what the link opens. */
  onIntent?: () => void;
  className?: string;
  'data-testid'?: string;
}) {
  return (
    <li
      className={cn(
        'relative flex min-h-14 items-center gap-4 px-4 py-2 transition-colors duration-quick',
        'focus-within:bg-sunken hover:bg-sunken',
        selected && 'bg-accent-tint shadow-[inset_3px_0_0_rgb(var(--accent-solid))] hover:bg-accent-tint',
        className,
      )}
      {...rest}
    >
      <div className="min-w-0 flex-1">
        <Link
          to={to}
          onMouseEnter={onIntent}
          onFocus={onIntent}
          aria-current={selected ? 'true' : undefined}
          className={cn(
            // The focus ring is drawn on the whole row (the stretched `::after`).
            'block truncate text-body font-semibold outline-none focus-visible:ring-0 focus-visible:ring-offset-0',
            'after:absolute after:inset-0 after:content-[""] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent',
            muted ? 'text-ink-3' : 'text-accent',
          )}
          data-row-link
        >
          {title}
        </Link>
        {facts && <p className="mt-0.5 truncate text-secondary text-ink-2">{facts}</p>}
      </div>
      {badges && <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">{badges}</div>}
      {aside && <div className="relative z-10 flex shrink-0 items-center gap-2">{aside}</div>}
    </li>
  );
}
