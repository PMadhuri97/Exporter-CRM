/**
 * The side navigation (frontend-plan §6.2, §7.3): the role's modules as labelled
 * rows with an icon, Settings at the foot, then *Collapse*. 224px wide; the button
 * collapses it to 56px of icons with tooltips, and the choice is remembered per
 * viewer. Under 1024px it is hidden, and the same rows open as a drawer from the
 * header's menu button (`NavDrawer`).
 *
 * The selected row has a blue tint, a 3px blue bar on the left and blue text. The
 * rows come from the module table (`routes/modules.ts`), filtered by what the role
 * may use, so the navigation never offers a screen the router would refuse.
 */

import * as Tooltip from '@radix-ui/react-tooltip';
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { Sheet } from '@/components';
import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { navRowForPath, navRowsFor, type NavRow } from '@/routes/modules';

const COLLAPSED_KEY = 'aner.nav.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function storeCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) window.localStorage.setItem(COLLAPSED_KEY, '1');
    else window.localStorage.removeItem(COLLAPSED_KEY);
  } catch {
    // The choice just won't outlive this page view.
  }
}

function NavItem({
  row,
  active,
  collapsed,
  onNavigate,
}: {
  row: NavRow;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const Glyph = Icon[row.icon];
  const link = (
    // A plain Link: which row is current is decided once, by `navRowForPath`, so the
    // Companies board marks Pipeline and not Companies.
    <Link
      to={row.to}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex h-9 items-center gap-3 rounded px-3 text-body transition-colors duration-quick',
        active
          ? 'bg-accent-tint font-semibold text-accent before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-r before:bg-accent'
          : 'text-ink-2 hover:bg-sunken hover:text-ink',
        collapsed && 'justify-center px-0',
      )}
    >
      <Glyph size={20} weight={active ? 'fill' : 'regular'} className="shrink-0" aria-hidden />
      <span className={collapsed ? 'sr-only' : 'truncate'}>{row.label}</span>
    </Link>
  );
  if (!collapsed) return <li>{link}</li>;
  return (
    <li>
      <Tooltip.Root delayDuration={300}>
        <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="right"
            sideOffset={8}
            className="z-50 rounded bg-ink px-2 py-1 text-caption font-semibold text-surface shadow-float"
          >
            {row.label}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </li>
  );
}

/** The rows, main then settings. Shared by the side navigation and the drawer. */
function NavRows({
  role,
  collapsed = false,
  onNavigate,
}: {
  role: UserRole;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { pathname, search } = useLocation();
  const rows = navRowsFor(role);
  // A settings section sits under the Settings row, so the row stays current there.
  const current = navRowForPath(rows, pathname, search);
  const active = current?.sideNav === false ? '/settings' : current?.to;
  const main = rows.filter((row) => row.group === 'main');
  const settings = rows.filter((row) => row.group === 'settings' && row.sideNav !== false);
  return (
    <>
      <ul className="flex flex-col gap-0.5">
        {main.map((row) => (
          <NavItem key={row.to} row={row} active={row.to === active} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </ul>
      <ul className="mt-auto flex flex-col gap-0.5 border-t border-line pt-2">
        {settings.map((row) => (
          <NavItem key={row.to} row={row} active={row.to === active} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </ul>
    </>
  );
}

export function SideNav({ role }: { role: UserRole }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  return (
    <Tooltip.Provider>
      <nav
        aria-label="Main"
        className={cn(
          'hidden shrink-0 flex-col border-r border-line bg-surface px-2 py-3 lg:flex',
          collapsed ? 'w-14' : 'w-56',
        )}
      >
        <NavRows role={role} collapsed={collapsed} />
        <button
          type="button"
          aria-pressed={collapsed}
          aria-label={collapsed ? 'Expand the navigation' : 'Collapse the navigation'}
          onClick={() => {
            storeCollapsed(!collapsed);
            setCollapsed(!collapsed);
          }}
          className={cn(
            'mt-0.5 flex h-9 items-center gap-3 rounded px-3 text-body text-ink-2 transition-colors duration-quick hover:bg-sunken hover:text-ink',
            collapsed && 'justify-center px-0',
          )}
        >
          {collapsed ? (
            <Icon.navExpand size={20} className="shrink-0" aria-hidden />
          ) : (
            <Icon.navCollapse size={20} className="shrink-0" aria-hidden />
          )}
          {!collapsed && <span aria-hidden>Collapse</span>}
        </button>
      </nav>
    </Tooltip.Provider>
  );
}

/** Under 1024px: the same rows, in a drawer from the left. */
export function NavDrawer({
  role,
  open,
  onOpenChange,
}: {
  role: UserRole;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Navigation" side="left">
      <nav aria-label="Main" className="flex h-full flex-col px-2 pb-3">
        <div className="flex h-12 items-center px-2">
          <BrandMark />
        </div>
        <NavRows role={role} onNavigate={() => onOpenChange(false)} />
      </nav>
    </Sheet>
  );
}
