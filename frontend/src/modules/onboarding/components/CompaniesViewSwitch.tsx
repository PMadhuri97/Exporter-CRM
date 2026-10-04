/**
 * Companies has two views of one list (frontend-plan §8.3): the register (rows) and
 * the board (three journey columns). Two links on a sunken track, so each view is
 * its own URL — shareable, and the browser's back button moves between them.
 */

import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

import { paths } from '../paths';

const SEGMENT =
  'rounded px-3 py-1 text-secondary font-medium transition-colors duration-quick';

export function CompaniesViewSwitch({ view }: { view: 'register' | 'board' }) {
  return (
    <nav aria-label="Companies view" className="inline-flex gap-0.5 rounded-md bg-sunken p-0.5">
      <Link
        to={paths.companies}
        aria-current={view === 'register' ? 'page' : undefined}
        className={cn(
          SEGMENT,
          view === 'register' ? 'bg-surface text-ink ring-1 ring-line-strong' : 'text-ink-2 hover:text-ink',
        )}
      >
        Register
      </Link>
      <Link
        to={paths.board}
        aria-current={view === 'board' ? 'page' : undefined}
        className={cn(
          SEGMENT,
          view === 'board' ? 'bg-surface text-ink ring-1 ring-line-strong' : 'text-ink-2 hover:text-ink',
        )}
      >
        Board
      </Link>
    </nav>
  );
}
