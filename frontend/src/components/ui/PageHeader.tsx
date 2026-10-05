import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '@/design/icons';

/** The title block every page starts with. */
export function PageHeader({
  title,
  description,
  actions,
  back,
  meta,
  as: Heading = 'h1',
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** A back link above the title — `{ to: '/companies', label: 'Companies' }`. */
  back?: { to: string; label: string };
  /** Chips or other small facts beside the title. */
  meta?: ReactNode;
  /** `h2` for a section drawn inside another page's frame (a Settings section). */
  as?: 'h1' | 'h2';
}) {
  return (
    <div className={Heading === 'h1' ? 'mb-6' : 'mb-4'}>
      {back && (
        <Link
          to={back.to}
          className="mb-3 inline-flex items-center gap-1.5 text-secondary font-medium text-ink-3 transition-colors duration-quick hover:text-ink"
        >
          <Icon.back size={14} aria-hidden />
          {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <Heading className={Heading === 'h1' ? 'text-title font-semibold text-ink' : 'text-heading font-semibold text-ink'}>
              {title}
            </Heading>
            {meta}
          </div>
          {description && <p className="mt-1.5 max-w-3xl text-body text-ink-2">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
