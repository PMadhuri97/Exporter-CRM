import { NavLink, useLocation } from 'react-router-dom';

import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { navRowsFor, type NavRow as NavItem } from '@/routes/modules';

/*
 * The rows come from the module table (`routes/modules.ts`), filtered by what the role
 * may use (R-33, G1): the router and the rail read the same list, so a row is never
 * offered for a screen the route would refuse. Deals and documents have no row — they
 * are reached from a company, as the server has no cross-company list of either.
 * Settings is for every role; the Users and Roles tabs inside it follow the server's
 * permissions, and the criteria and required-documents rows are the administrator's.
 */

/** Whether `pathname` is inside `path`: an exact match for the root, otherwise
 * the path itself or anything below it — `NavLink`'s own rule. */
function matches(path: string, pathname: string): boolean {
  if (path === '/') return pathname === '/';
  return pathname === path || pathname.startsWith(`${path}/`);
}

/**
 * The one row to highlight: the **most specific** row that matches. Plain
 * `NavLink` matching lights every prefix; the longest match is the page the
 * user is actually on.
 *
 * This is what keeps `/settings` and `/settings/qualification-criteria` apart:
 * on the criteria page only the criteria row lights, not both.
 */
function activePath(items: NavItem[], pathname: string): string | undefined {
  return items
    .filter((item) => matches(item.to, pathname))
    .map((item) => item.to)
    .sort((a, b) => b.length - a.length)[0];
}

function NavRow({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === '/'}
        onClick={onNavigate}
        title={collapsed ? item.label : undefined}
        aria-current={active ? 'page' : false}
        className={() =>
          cn(
            'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
            collapsed && 'justify-center px-0',
            active
              ? 'bg-brand-50 text-brand-700'
              : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
          )
        }
      >
        <item.icon size={17} strokeWidth={2} className="shrink-0" />
        <span className={collapsed ? 'sr-only' : undefined}>{item.label}</span>
      </NavLink>
    </li>
  );
}

export function Sidebar({
  role,
  collapsed = false,
  onNavigate,
}: {
  role: UserRole;
  /** The icon-only rail. */
  collapsed?: boolean;
  /** Called after a row is followed — the narrow-screen drawer closes itself. */
  onNavigate?: () => void;
}) {
  const { pathname } = useLocation();
  const rows = navRowsFor(role);
  const mainItems = rows.filter((row) => row.group === 'main');
  const settingsItems = rows.filter((row) => row.group === 'settings');
  const active = activePath(rows, pathname);

  return (
    <nav
      aria-label="Main"
      className={cn(
        'flex h-full shrink-0 flex-col border-r border-border bg-surface py-5 transition-[width] duration-150',
        collapsed ? 'w-16 px-2' : 'w-60 px-3',
      )}
    >
      <div className={cn('mb-6 flex items-center gap-2.5 px-2', collapsed && 'justify-center px-0')}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white dark:text-surface">
          A
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-tight text-ink">Aner Labs</p>
            <p className="text-xs text-ink-faint">Exporter CRM</p>
          </div>
        )}
      </div>

      <ul className="flex flex-col gap-0.5">
        {mainItems.map((item) => (
          <NavRow
            key={item.to}
            item={item}
            active={item.to === active}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </ul>

      {/* `mt-auto` pins this group to the foot of the rail. Settings is where
          you go to stop working, not another stage of the work, so it sits
          apart from the workflow rows rather than below them in the same list.
          The nav is `h-full` and a flex column, which is what makes the push
          work at any viewport height. */}
      <div className="mt-auto border-t border-border pt-4">
        <p
          className={cn(
            'mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint',
            collapsed && 'sr-only',
          )}
        >
          Settings
        </p>
        <ul className="flex flex-col gap-0.5">
          {settingsItems.map((item) => (
            <NavRow
              key={item.to}
              item={item}
              active={item.to === active}
              collapsed={collapsed}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      </div>
    </nav>
  );
}
