import { Link } from 'react-router-dom';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

export interface Crumb {
  label: string;
  /** Absent on the last crumb, the page you are on. */
  to?: string;
}

/**
 * Where a page sits (frontend-plan §6.3, §7.2): each page header carries its own,
 * as enterprise apps do. Every crumb but the last is a link.
 */
export function Breadcrumbs({ items, className }: { items: readonly Crumb[]; className?: string }) {
  return (
    <nav aria-label="Breadcrumb" className={cn('min-w-0', className)}>
      <ol className="flex min-w-0 flex-wrap items-center gap-1 text-secondary text-ink-3">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-1">
              {item.to && !last ? (
                <Link
                  to={item.to}
                  className="truncate text-accent underline-offset-2 transition-colors duration-quick hover:underline"
                >
                  {item.label}
                </Link>
              ) : (
                <span className="truncate text-ink-2" aria-current={last ? 'page' : undefined}>
                  {item.label}
                </span>
              )}
              {!last && <Icon.caretRight size={12} className="shrink-0" aria-hidden />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
