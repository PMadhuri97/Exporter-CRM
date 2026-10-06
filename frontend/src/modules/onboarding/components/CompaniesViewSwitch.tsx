/**
 * Companies has two views of one list (frontend-plan §8.3): the list (rows) and
 * the board (three journey columns). Two links on a sunken track, so each view is
 * its own URL — shareable, and the browser's back button moves between them.
 */

import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

import { paths } from '../paths';

const SEGMENT =
  'rounded-sm px-2.5 py-1 text-secondary transition-colors duration-quick';

export function CompaniesViewSwitch({ view }: { view: 'list' | 'board' }) {
  return (
    <nav aria-label="Companies view" className="inline-flex gap-0.5 rounded border border-line-strong bg-surface p-0.5">
      <Link
        to={paths.companies}
        aria-current={view === 'list' ? 'page' : undefined}
        className={cn(
          SEGMENT,
          view === 'list' ? 'bg-accent-tint font-semibold text-accent' : 'text-ink-2 hover:bg-sunken hover:text-ink',
        )}
      >
        List
      </Link>
      <Link
        to={paths.board}
        aria-current={view === 'board' ? 'page' : undefined}
        className={cn(
          SEGMENT,
          view === 'board' ? 'bg-accent-tint font-semibold text-accent' : 'text-ink-2 hover:bg-sunken hover:text-ink',
        )}
      >
        Pipeline
      </Link>
    </nav>
  );
}
