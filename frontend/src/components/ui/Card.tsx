import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

/** A surface: border, background and the one card shadow. */
export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-lg border border-border bg-surface shadow-card', className)}
      {...rest}
    />
  );
}

export interface PanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /** Buttons or links on the right of the header. */
  actions?: ReactNode;
  /** Heading level for the title — `h2` on a page, `h3` inside a tab that
   * already sits under the page's `h2`s. */
  as?: 'h2' | 'h3';
  /** Removes the body padding, for a table that runs edge to edge. */
  flush?: boolean;
}

/** A titled section of a page: a card with a header row and a body. */
export function Panel({
  title,
  description,
  actions,
  as: Heading = 'h2',
  flush = false,
  className,
  children,
  ...rest
}: PanelProps) {
  return (
    <section
      className={cn('rounded-lg border border-border bg-surface shadow-card', className)}
      {...rest}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <Heading className="font-semibold text-ink">{title}</Heading>
          {description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={flush ? 'mt-3' : 'px-5 pb-5 pt-3'}>{children}</div>
    </section>
  );
}
