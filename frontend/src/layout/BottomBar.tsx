/**
 * Narrow screens (<1024 px, frontend-plan §7.1): the rail becomes a bottom bar of
 * up to five of the role's work modules. Settings moves into the avatar menu.
 * Rows come from the module table, so it offers exactly what the rail would.
 */

import { NavLink, useLocation } from 'react-router-dom';

import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { navRowForPath, navRowsFor } from '@/routes/modules';

export function BottomBar({ role }: { role: UserRole }) {
  const { pathname } = useLocation();
  const rows = navRowsFor(role);
  const main = rows.filter((row) => row.group === 'main').slice(0, 5);
  const active = navRowForPath(rows, pathname)?.to;

  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      <ul className="flex">
        {main.map((row) => {
          const Glyph = Icon[row.icon];
          const current = row.to === active;
          return (
            <li key={row.to} className="flex-1">
              <NavLink
                to={row.to}
                end={row.to === '/'}
                aria-current={current ? 'page' : false}
                className={cn(
                  'flex h-14 flex-col items-center justify-center gap-0.5 text-caption',
                  current ? 'font-semibold text-ink' : 'text-ink-3',
                )}
              >
                <Glyph size={20} weight={current ? 'fill' : 'regular'} aria-hidden />
                {row.label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
