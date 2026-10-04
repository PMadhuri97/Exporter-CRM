/**
 * The rail (frontend-plan §7.1): the role's work modules, a gap, then Settings at
 * the foot. 64 px of icons; it widens to 232 px while hovered or while the keyboard
 * is in it, or for good when pinned (kept per viewer). Keyboard focus, not any focus:
 * a clicked row keeps focus after the click, and the rail would stay open over the
 * page after the pointer had left. The active row is an ink bar and ink text —
 * never a tinted fill or a hue.
 *
 * The rows come from the module table (`routes/modules.ts`), filtered by what the
 * role may use (R-33, G1), so the rail never offers a screen the router would
 * refuse. Labels stay in the DOM when narrow (visually hidden), so every row keeps
 * its accessible name.
 */

import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { navRowForPath, navRowsFor, type NavRow } from '@/routes/modules';

const PINNED_KEY = 'aner.rail.pinned';

function readPinned(): boolean {
  try {
    return window.localStorage.getItem(PINNED_KEY) === '1';
  } catch {
    return false;
  }
}

function storePinned(pinned: boolean): void {
  try {
    window.localStorage.setItem(PINNED_KEY, pinned ? '1' : '0');
  } catch {
    // The rail's state just won't outlive this page view.
  }
}

/** Visually hidden while narrow; shown when the rail widens or is pinned. */
function labelClass(pinned: boolean) {
  return pinned
    ? 'truncate'
    : 'sr-only group-hover/rail:not-sr-only group-hover/rail:truncate group-has-[:focus-visible]/rail:not-sr-only group-has-[:focus-visible]/rail:truncate';
}

function RailRow({ row, active, pinned }: { row: NavRow; active: boolean; pinned: boolean }) {
  const Glyph = Icon[row.icon];
  return (
    <li>
      <NavLink
        to={row.to}
        end={row.to === '/'}
        aria-current={active ? 'page' : false}
        className={() =>
          cn(
            'relative flex h-10 items-center gap-3 rounded-md px-3 text-body transition-colors duration-quick',
            active
              ? 'font-semibold text-ink before:absolute before:-left-2 before:top-2 before:h-6 before:w-0.5 before:rounded-full before:bg-ink'
              : 'text-ink-2 hover:bg-sunken hover:text-ink',
          )
        }
      >
        <Glyph size={20} weight={active ? 'fill' : 'regular'} className="shrink-0" aria-hidden />
        <span className={labelClass(pinned)}>{row.label}</span>
      </NavLink>
    </li>
  );
}

export function Rail({ role }: { role: UserRole }) {
  const { pathname } = useLocation();
  const [pinned, setPinned] = useState(readPinned);
  const rows = navRowsFor(role);
  const main = rows.filter((row) => row.group === 'main');
  const settings = rows.filter((row) => row.group === 'settings');
  const active = navRowForPath(rows, pathname)?.to;

  return (
    <div className={cn('relative hidden shrink-0 lg:block', pinned ? 'w-[14.5rem]' : 'w-16')}>
      <nav
        aria-label="Main"
        className={cn(
          'group/rail absolute inset-y-0 left-0 z-30 flex flex-col overflow-hidden border-r border-line bg-surface px-2 py-3',
          'transition-[width,box-shadow] duration-pop ease-enter',
          pinned
            ? 'w-[14.5rem]'
            : 'w-16 hover:w-[14.5rem] hover:shadow-float hover:delay-150 has-[:focus-visible]:w-[14.5rem] has-[:focus-visible]:shadow-float',
        )}
      >
        <div className="mb-5 flex h-10 items-center px-2">
          <BrandMark size="md" wordmark={false} />
          <span
            className={cn(
              'ml-2.5 whitespace-nowrap text-body font-semibold text-ink',
              pinned ? '' : 'hidden group-hover/rail:inline group-has-[:focus-visible]/rail:inline',
            )}
            aria-hidden
          >
            Aner Labs
          </span>
        </div>

        <ul className="flex flex-col gap-0.5">
          {main.map((row) => (
            <RailRow key={row.to} row={row} active={row.to === active} pinned={pinned} />
          ))}
        </ul>

        <div className="mt-auto flex flex-col gap-0.5 border-t border-line pt-3">
          <ul className="flex flex-col gap-0.5">
            {settings.map((row) => (
              <RailRow key={row.to} row={row} active={row.to === active} pinned={pinned} />
            ))}
          </ul>
          <button
            type="button"
            aria-pressed={pinned}
            onClick={() => {
              storePinned(!pinned);
              setPinned(!pinned);
            }}
            className="flex h-9 items-center gap-3 rounded-md px-3 text-secondary text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink"
          >
            {pinned ? (
              <Icon.railCollapse size={18} className="shrink-0" aria-hidden />
            ) : (
              <Icon.railExpand size={18} className="shrink-0" aria-hidden />
            )}
            <span className={labelClass(pinned)}>{pinned ? 'Collapse the menu' : 'Keep the menu open'}</span>
          </button>
        </div>
      </nav>
    </div>
  );
}
