import {
  Kanban,
  LayoutDashboard,
  ListChecks,
  Settings,
  Users,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';

interface NavItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  /** Screens not built yet render as a disabled row with a "Soon" badge —
   * never a link to a route that renders nothing, per the design principle
   * against fake navigation. */
  status: 'ready' | 'soon';
}

// One row per later ticket in docs/exporter-crm-frontend-tickets.md's build
// sequence — flip `status` to 'ready' as each ticket lands, rather than
// adding the row from scratch.
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard, status: 'ready' },
  { label: 'Exporters', path: '/exporters', icon: Users, status: 'ready' },
  {
    label: 'Follow-ups',
    path: '/follow-ups',
    icon: ListChecks,
    status: 'soon',
  },
  { label: 'Pipeline', path: '/pipeline', icon: Kanban, status: 'ready' },
];

// Settings sits apart from the workflow rows above — it is where you go to
// stop working, not another stage of the work — so it is pinned to the bottom
// of the rail rather than added to NAV_ITEMS. Every role gets it: the page
// always has a profile tab, and the Users tab appears only for ADMIN.
const SETTINGS_ITEM: NavItem = {
  label: 'Settings',
  path: '/settings',
  icon: Settings,
  status: 'ready',
};

function NavRow({ item }: { item: NavItem }) {
  if (item.status === 'soon') {
    return (
      <div
        className="flex items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-ink-faint"
        aria-disabled="true"
      >
        <span className="flex items-center gap-2.5">
          <item.icon size={17} strokeWidth={2} />
          {item.label}
        </span>
        <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
          Soon
        </span>
      </div>
    );
  }

  return (
    <NavLink
      to={item.path}
      end={item.path === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
          isActive
            ? 'bg-brand-50 text-brand-600'
            : 'text-ink-muted hover:bg-surface-sunken hover:text-ink'
        }`
      }
    >
      <item.icon size={17} strokeWidth={2} />
      {item.label}
    </NavLink>
  );
}

export function Sidebar() {
  return (
    <nav className="flex w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-5">
      <div className="mb-6 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-brand-400">
          A
        </div>
        <div>
          <p className="text-sm font-semibold text-ink">ANER</p>
          <p className="text-xs text-ink-faint">Exporter CRM</p>
        </div>
      </div>

      <ul className="flex flex-1 flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <li key={item.path}>
            <NavRow item={item} />
          </li>
        ))}
      </ul>

      <ul className="mt-2 border-t border-border pt-2">
        <li>
          <NavRow item={SETTINGS_ITEM} />
        </li>
      </ul>
    </nav>
  );
}
