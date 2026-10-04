/**
 * The context bar (frontend-plan §7.1), 52 px: where you are as a breadcrumb
 * trail, ⌘K, and the avatar menu. A page sets its own trail with `useCrumbs`;
 * otherwise the trail is the module's rail label.
 */

import { Link, useLocation } from 'react-router-dom';

import { Kbd } from '@/components';
import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { commandKeyLabel, useShellState, type Crumb } from '@/platform/shell';
import { navRowForPath, navRowsFor } from '@/routes/modules';

import { AvatarMenu } from './AvatarMenu';

function defaultCrumbs(role: UserRole, pathname: string): Crumb[] {
  const row = navRowForPath(navRowsFor(role), pathname);
  if (!row) return [];
  return pathname === row.to ? [{ label: row.label }] : [{ label: row.label, to: row.to }];
}

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  if (crumbs.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5 text-body">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
              {index > 0 && (
                <span aria-hidden className="text-ink-4">
                  /
                </span>
              )}
              {crumb.to && !last ? (
                <Link
                  to={crumb.to}
                  className="truncate text-ink-3 transition-colors duration-quick hover:text-ink"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? 'page' : undefined}
                  className="truncate font-medium text-ink"
                >
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function ContextBar({
  role,
  onOpenCommand,
}: {
  role: UserRole;
  onOpenCommand: () => void;
}) {
  const { pathname } = useLocation();
  const { crumbs } = useShellState();
  const trail = crumbs ?? defaultCrumbs(role, pathname);

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-4 border-b border-line bg-paper px-4 sm:px-6">
      <Link to="/" className="rounded-md lg:hidden" aria-label="Desk">
        <BrandMark size="sm" wordmark={false} />
      </Link>
      <div className="min-w-0 flex-1">
        <Breadcrumbs crumbs={trail} />
      </div>
      <button
        type="button"
        onClick={onOpenCommand}
        aria-label="Find or go to"
        aria-keyshortcuts="Control+K Meta+K"
        className="flex h-8 items-center gap-2 rounded-md border border-line-strong bg-surface pl-2.5 pr-1.5 text-secondary text-ink-3 transition-colors duration-quick hover:border-ink-3 hover:text-ink"
      >
        <Icon.search size={15} aria-hidden />
        <span className="hidden pr-6 sm:inline">Find…</span>
        <span className="hidden items-center gap-0.5 sm:flex" aria-hidden>
          <Kbd>{commandKeyLabel()}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
      <AvatarMenu role={role} />
    </header>
  );
}
