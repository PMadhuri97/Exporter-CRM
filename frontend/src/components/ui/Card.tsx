import type { HTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

import { LINK_CLASSES } from './styles';

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  /** The header row's title. Without a title or actions the card is a plain box. */
  title?: ReactNode;
  /** A count after the title ("Deals (2)"), already capped by the caller. */
  count?: ReactNode;
  /** Buttons or links on the right of the header row. */
  actions?: ReactNode;
  /** A line under the title. */
  description?: ReactNode;
  /** The footer: a link ("View all" on a related-list card, §6.6) or any content. */
  footer?: { label: string; to: string } | ReactNode;
  /** Heading level for the title — `h2` on a page, `h3` inside a tab. */
  as?: 'h2' | 'h3';
  /** Drops the body's padding, for a list whose items run edge to edge. */
  flush?: boolean;
}

function isLink(footer: CardProps['footer']): footer is { label: string; to: string } {
  return typeof footer === 'object' && footer !== null && 'to' in footer && 'label' in footer;
}

/**
 * The one container (frontend-plan §5.4, §6.6): white, a 1px border, 4px corners and
 * no shadow, on the grey page. A 48px header row holds the title, an optional count
 * and the card's actions on the right. A card never holds another card; inside one,
 * headings and dividers give the structure (§5.1).
 */
export function Card({
  title,
  count,
  actions,
  description,
  footer,
  as: Heading = 'h2',
  flush = false,
  className,
  children,
  ...rest
}: CardProps) {
  const hasHeader = title !== undefined || actions !== undefined;
  const hasBody = children !== undefined && children !== null && children !== false;
  return (
    <section className={cn('rounded border border-line bg-surface', className)} {...rest}>
      {hasHeader && (
        <header className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2">
          <div className="min-w-0">
            {title !== undefined && (
              <Heading className="text-heading font-semibold text-ink">
                {title}
                {count !== undefined && (
                  <span className="ml-1.5 font-normal tabular-nums text-ink-3">({count})</span>
                )}
              </Heading>
            )}
            {description && <p className="text-secondary text-ink-3">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {hasBody && (
        <div className={cn(!flush && 'px-4 pb-4', !flush && !hasHeader && 'pt-4')}>{children}</div>
      )}
      {footer && (
        <footer className="border-t border-line px-4 py-2.5 text-center text-secondary">
          {isLink(footer) ? (
            <Link to={footer.to} className={LINK_CLASSES}>
              {footer.label}
            </Link>
          ) : (
            footer
          )}
        </footer>
      )}
    </section>
  );
}

export interface PanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /** Buttons or links on the right of the heading. */
  actions?: ReactNode;
  as?: 'h2' | 'h3';
  flush?: boolean;
}

/** A titled section of a page: a `Card` with a header row. */
export function Panel({ title, description, actions, as = 'h2', flush = false, ...rest }: PanelProps) {
  return <Card title={title} description={description} actions={actions} as={as} flush={flush} {...rest} />;
}
