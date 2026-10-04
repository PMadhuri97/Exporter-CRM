import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

/**
 * A sheet of surface on the paper: a hairline and no shadow (resting surfaces
 * never float, §5.4). For a group that must read as one object — a receipt, a
 * party, a composer — not for wrapping every section.
 */
export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl border border-line bg-surface', className)} {...rest} />;
}

export interface PanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /** Buttons or links on the right of the heading. */
  actions?: ReactNode;
  /** Heading level for the title — `h2` on a page, `h3` inside a tab that
   * already sits under the page's `h2`s. */
  as?: 'h2' | 'h3';
  /** Kept for callers that ran a table edge to edge; sections have no padding
   * to remove any more. */
  flush?: boolean;
}

/**
 * A titled section of a page — paper, not panels (§5.1): structure comes from
 * the heading, whitespace and one hairline above, never from a box. Stacked
 * sections read as chapters of one page rather than a pile of cards.
 */
export function Panel({
  title,
  description,
  actions,
  as: Heading = 'h2',
  flush: _flush = false,
  className,
  children,
  ...rest
}: PanelProps) {
  return (
    <section className={cn('border-t border-line pt-4', className)} {...rest}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Heading className="text-lead font-semibold text-ink">{title}</Heading>
          {description && <p className="mt-0.5 text-secondary text-ink-2">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className="mt-3">{children}</div>
    </section>
  );
}
