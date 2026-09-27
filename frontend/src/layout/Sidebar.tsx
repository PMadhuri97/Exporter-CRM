import { Home, Kanban, ListChecks, SlidersHorizontal, Building2 } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { isAdminRole } from '@/platform/auth';

interface NavItem {
  label: string;
  path: string;
  icon: typeof Home;
}

/**
 * The main rows. Deals and documents are reached from a company's page, not
 * from here: the server has no cross-company deal or document list, and a row
 * that could only say "pick a company first" would be fake navigation.
 */
const NAV_ITEMS: NavItem[] = [
  { label: 'Home', path: '/', icon: Home },
  { label: 'Companies', path: '/companies', icon: Building2 },
  { label: 'Follow-ups', path: '/follow-ups', icon: ListChecks },
  { label: 'Pipeline', path: '/pipeline', icon: Kanban },
];

/** Rows only ADMIN sees — the server refuses these screens to anyone else. */
const ADMIN_ITEMS: NavItem[] = [
  { label: 'Qualification criteria', path: '/settings/qualification-criteria', icon: SlidersHorizontal },
];

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
 */
function activePath(items: NavItem[], pathname: string): string | undefined {
  return items
    .filter((item) => matches(item.path, pathname))
    .map((item) => item.path)
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
        to={item.path}
        end={item.path === '/'}
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
  const adminItems = isAdminRole(role) ? ADMIN_ITEMS : [];
  const active = activePath([...NAV_ITEMS, ...adminItems], pathname);

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
            <p className="text-sm font-semibold leading-tight text-ink">ANER</p>
            <p className="text-xs text-ink-faint">Exporter CRM</p>
          </div>
        )}
      </div>

      <ul className="flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <NavRow
            key={item.path}
            item={item}
            active={item.path === active}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </ul>

      {adminItems.length > 0 && (
        <div className="mt-6">
          <p
            className={cn(
              'mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint',
              collapsed && 'sr-only',
            )}
          >
            Settings
          </p>
          <ul className="flex flex-col gap-0.5">
            {adminItems.map((item) => (
              <NavRow
                key={item.path}
                item={item}
                active={item.path === active}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        </div>
      )}
    </nav>
  );
}
